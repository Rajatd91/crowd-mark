"""Turn the latest signal into orders, check them, and (only if asked) send them.

Run it once a day after the market closes, or on rebalance days only. It is
idempotent: it compares targets with what the account actually holds, so
running it twice does not double the trades.

The default is a dry run that prints the plan. Orders go out only with
`--execute`, and to a live account only with `--live` and
`broker.allow_live = true` in the config.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import alerts, risk, strategy
from .broker import Order
from .config import Config
from .data import Prices

log = logging.getLogger(__name__)


NY = ZoneInfo("America/New_York")


def completed_bars(prices: Prices, now: datetime | None = None) -> Prices:
    """Drop today's bar while the US session is still running: its 'close' is
    just the latest trade, and a signal built on it would change by the bell."""
    now = (now or datetime.now(timezone.utc)).astimezone(NY)
    today = pd.Timestamp(now.date())
    if now.hour * 60 + now.minute < 16 * 60 + 15:
        keep = prices.close.index < today
        return Prices(prices.open.loc[keep], prices.close.loc[keep])
    return prices


def _period(day: pd.Timestamp, how: str) -> str:
    if how == "daily":
        return day.date().isoformat()
    return str(day.to_period({"weekly": "W-FRI", "monthly": "M"}[how]))


def schedule_due(last_bar: pd.Timestamp, today: pd.Timestamp, how: str, state_dir: Path) -> tuple[bool, str]:
    """Trade once per period, on the first run after the period's last bar,
    which is what the backtest does (signal at the period's final close, fill
    at the next open)."""
    period = _period(last_bar, how)
    if how != "daily" and period == _period(today, how):
        return False, f"{how} period {period} is not finished yet"
    marker = state_dir / "last_rebalance.txt"
    if marker.exists() and marker.read_text().strip() == period:
        return False, f"already rebalanced for {period}"
    return True, period


def plan_orders(target: pd.Series, holdings: dict[str, float], equity: float,
                last: pd.Series, cfg: Config) -> tuple[list[Order], list[str]]:
    """Orders that move the account from `holdings` to `target` weights."""
    exe, buf = cfg.execution, cfg.risk.limit_buffer_bps / 1e4
    plan, notes = [], []
    symbols = sorted(set(target.index) | set(holdings))
    for s in symbols:
        px = float(last.get(s, np.nan))
        if not np.isfinite(px) or px <= 0:
            notes.append(f"{s}: no price, skipped")
            continue
        have = holdings.get(s, 0.0)
        w_now = have * px / equity
        w_want = float(target.get(s, 0.0))
        exiting = w_want == 0 and have != 0
        if abs(w_want - w_now) < exe.band and not exiting:
            continue
        qty = -have if exiting else (w_want * equity - have * px) / px
        if not exe.fractional:
            qty = float(np.trunc(qty))
        if qty == 0 or (abs(qty * px) < exe.min_trade_value and not exiting):
            notes.append(f"{s}: change too small to trade")
            continue
        limit = px * (1 + buf) if qty > 0 else px * (1 - buf)
        plan.append(Order(s, qty, round(limit, 2), qty * limit))
    plan.sort(key=lambda o: o.qty)          # sells first
    return plan, notes


def rebalance(cfg: Config, prices: Prices, broker, execute: bool = False,
              today: pd.Timestamp | None = None, require_open: bool = True,
              force: bool = False) -> dict:
    today = today or pd.Timestamp.now().normalize()
    state_dir = Path(cfg.broker.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    last_bar = prices.close.index[-1]
    due, period = schedule_due(last_bar, today, cfg.execution.rebalance, state_dir)
    target = strategy.target_weights(prices, cfg.strategy, pd.DatetimeIndex([last_bar])).iloc[0]
    target = target.reindex(cfg.universe).fillna(0.0)
    last = prices.close.iloc[-1]
    marks = {s: float(last[s]) for s in prices.tickers if np.isfinite(last[s])}

    acct = broker.account(marks)
    holdings = broker.positions()
    plan, notes = plan_orders(target, holdings, acct.equity, last, cfg)
    if not due and not force:
        notes.append(f"not a rebalance day: {period}")
        plan = []

    blocks = (risk.kill_switch(cfg.risk, state_dir)
              + risk.staleness(last_bar, today, cfg.risk)
              + risk.price_sanity(prices.close, cfg.universe, cfg.risk)
              + risk.daily_loss(acct.equity, acct.last_equity, cfg.risk)
              + risk.weights(target, cfg.strategy.max_weight, cfg.strategy.max_gross)
              + risk.orders(plan, acct.equity, cfg.risk))
    if execute and require_open and not broker.market_open():
        blocks.append("market is closed; limit prices would be stale at the next open")

    record = {
        "time": datetime.now(timezone.utc).isoformat(),
        "signal_date": last_bar.date().isoformat(),
        "equity": acct.equity,
        "cash": acct.cash,
        "target": {k: round(v, 4) for k, v in target.items() if v},
        "holdings": holdings,
        "orders": [o.__dict__ for o in plan],
        "notes": notes,
        "blocked": blocks,
        "executed": False,
        "results": [],
    }

    if execute and not blocks:
        for o in plan:
            res = broker.submit(o)
            record["results"].append(res)
            if res.get("status") == "rejected":
                log.error("order rejected: %s", res)
        record["executed"] = True
        broker.mark_close(marks)
        if due:
            (state_dir / "last_rebalance.txt").write_text(period)

    with open(state_dir / "journal.jsonl", "a") as fh:
        fh.write(json.dumps(record, default=str) + "\n")

    alerts.notify(summary_text(record))
    return record


def summary_text(record: dict) -> str:
    lines = [f"trendbot {record['signal_date']}  equity {record['equity']:,.2f}"]
    if record["blocked"]:
        lines.append("BLOCKED: " + "; ".join(record["blocked"]))
    for o in record["orders"]:
        lines.append(f"  {'BUY ' if o['qty'] > 0 else 'SELL'} {abs(o['qty']):g} {o['symbol']} "
                     f"@ {o['limit_price']:.2f}  ({o['value']:,.0f})")
    if not record["orders"]:
        lines.append("  no trades needed")
    if record["executed"]:
        lines.append("executed")
    else:
        lines.append("nothing sent (blocked)" if record["blocked"] else "dry run: nothing sent")
    return "\n".join(lines)
