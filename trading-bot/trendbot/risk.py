"""Checks that stand between a computed plan and a broker.

Each check returns a list of reasons to refuse. The runner submits nothing if
any list is non-empty. They guard against the failures that actually cost
retail bots money: trading on stale or broken data, a bug that sizes an order
far too large, running on after a bad day, and being unable to stop it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .config import RiskConfig


def kill_switch(cfg: RiskConfig, state_dir: str | Path) -> list[str]:
    path = Path(state_dir) / cfg.kill_switch_file
    return [f"kill switch present: {path} (delete it to resume)"] if path.exists() else []


def staleness(last_bar: pd.Timestamp, today: pd.Timestamp, cfg: RiskConfig) -> list[str]:
    age = int(np.busday_count(last_bar.date(), today.date()))
    if age > cfg.max_staleness_days:
        return [f"latest price is {age} business days old ({last_bar.date()})"]
    return []


def price_sanity(close: pd.DataFrame, tickers: list[str], cfg: RiskConfig) -> list[str]:
    problems = []
    last = close.iloc[-1]
    prev = close.iloc[-2] if len(close) > 1 else last
    for t in tickers:
        p, q = last.get(t), prev.get(t)
        if p is None or not np.isfinite(p) or p <= 0:
            problems.append(f"{t}: no valid latest price")
        elif q and np.isfinite(q) and abs(p / q - 1) > cfg.max_price_jump:
            problems.append(f"{t}: moved {p / q - 1:.0%} in a day; refusing until checked")
    return problems


def daily_loss(equity: float, last_equity: float | None, cfg: RiskConfig) -> list[str]:
    if not last_equity or last_equity <= 0:
        return []
    change = equity / last_equity - 1
    if change < -cfg.max_daily_loss:
        return [f"equity down {change:.1%} since the last close, beyond the {cfg.max_daily_loss:.0%} limit"]
    return []


def orders(plan: list, equity: float, cfg: RiskConfig) -> list[str]:
    problems = []
    if len(plan) > cfg.max_orders:
        problems.append(f"{len(plan)} orders exceeds the limit of {cfg.max_orders}")
    for o in plan:
        if abs(o.value) > cfg.max_order_fraction * equity:
            problems.append(f"{o.symbol}: order of {abs(o.value):,.0f} is more than "
                            f"{cfg.max_order_fraction:.0%} of equity")
        if o.qty == 0 or not np.isfinite(o.qty):
            problems.append(f"{o.symbol}: invalid quantity {o.qty}")
    return problems


def weights(target: pd.Series, max_weight: float, max_gross: float) -> list[str]:
    problems = []
    if (target.abs() > max_weight + 1e-9).any():
        problems.append("a target weight exceeds max_weight")
    if target.abs().sum() > max_gross + 1e-9:
        problems.append("target gross exposure exceeds max_gross")
    if target.isna().any():
        problems.append("target weights contain NaN")
    return problems
