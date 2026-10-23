"""A daily backtest that keeps books the way a broker would.

The account holds a number of shares of each asset and some cash. Targets
decided at the close of day t are traded at the open of day t+1, at a price
worse than the open by the slippage, plus commission. Sells go first so their
cash pays for the buys; if the buys still cost more than the cash available
(an overnight gap can do that), every buy is scaled down rather than letting
cash go negative. With `fractional = false` share counts are whole, which
matters for a small account.

The engine knows nothing about the strategy. It takes a frame of target
weights indexed by the dates on which they were decided, so the same engine
runs the strategy, buy-and-hold and any benchmark at identical costs.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import ExecutionConfig
from .data import Prices


@dataclass
class BacktestResult:
    equity: pd.Series          # end-of-day account value
    cash: pd.Series
    holdings: pd.DataFrame     # shares held at each close
    weights: pd.DataFrame      # actual weights at each close
    trades: pd.DataFrame       # one row per fill
    costs: pd.Series           # commission + slippage paid each day

    @property
    def returns(self) -> pd.Series:
        return self.equity.pct_change().fillna(0.0)

    def turnover(self) -> float:
        """Annualised one-way turnover as a multiple of equity."""
        if self.trades.empty:
            return 0.0
        traded = self.trades.groupby("date")["value"].apply(lambda v: v.abs().sum())
        daily = (traded / self.equity.reindex(traded.index)).sum()
        years = len(self.equity) / 252
        return float(daily / 2 / years)


def run(prices: Prices, targets: pd.DataFrame, exe: ExecutionConfig,
        initial_capital: float) -> BacktestResult:
    opens = prices.open.to_numpy(dtype=float)
    closes = prices.close.to_numpy(dtype=float)
    dates = prices.close.index
    tickers = prices.tickers
    targets = targets.reindex(columns=tickers).fillna(0.0)
    target_rows = {d: targets.loc[d].to_numpy(dtype=float) for d in targets.index}

    n = len(tickers)
    shares = np.zeros(n)
    cash = float(initial_capital)
    slip = exe.slippage_bps / 1e4
    comm_bps = exe.commission_bps / 1e4

    eq_out = np.empty(len(dates))
    cash_out = np.empty(len(dates))
    hold_out = np.empty((len(dates), n))
    cost_out = np.zeros(len(dates))
    trades = []
    pending = None
    last_mark = np.full(n, np.nan)

    for i, day in enumerate(dates):
        o, c = opens[i], closes[i]

        if pending is not None:
            tradable = ~np.isnan(o)
            mark = np.where(tradable, o, last_mark)
            held_value = np.nansum(shares * mark)
            nav = cash + held_value
            if nav > 0:
                cur_w = np.where(np.isnan(mark), 0.0, shares * np.nan_to_num(mark)) / nav
                want = pending * nav
                delta_val = np.zeros(n)
                for j in range(n):
                    if not tradable[j]:
                        continue
                    exiting = pending[j] == 0 and shares[j] != 0
                    if abs(pending[j] - cur_w[j]) < exe.band and not exiting:
                        continue
                    delta_val[j] = want[j] - shares[j] * o[j]

                qty = np.zeros(n)
                for j in np.nonzero(delta_val)[0]:
                    q = delta_val[j] / o[j]
                    if not exe.fractional:
                        q = np.trunc(q)
                    if pending[j] == 0:
                        q = -shares[j]                      # a full exit closes everything
                    if q == 0 or (abs(q * o[j]) < exe.min_trade_value and pending[j] != 0):
                        continue
                    qty[j] = q

                # Sells first.
                for j in np.nonzero(qty < 0)[0]:
                    px = o[j] * (1 - slip)
                    value = qty[j] * px                     # negative
                    fee = exe.commission_per_order + comm_bps * abs(value)
                    cash += -value - fee
                    shares[j] += qty[j]
                    cost_out[i] += fee + abs(qty[j]) * o[j] * slip
                    trades.append((day, tickers[j], qty[j], px, value, fee))

                buys = np.nonzero(qty > 0)[0]
                if len(buys):
                    px = o[buys] * (1 + slip)
                    gross = qty[buys] * px
                    fees = exe.commission_per_order + comm_bps * gross
                    need = float((gross + fees).sum())
                    if need > cash:
                        scale = max(cash, 0.0) / need
                        q = qty[buys] * scale
                        qty[buys] = q if exe.fractional else np.floor(q)
                    for j in buys:
                        if qty[j] <= 0:
                            continue
                        p = o[j] * (1 + slip)
                        value = qty[j] * p
                        fee = exe.commission_per_order + comm_bps * value
                        if value + fee > cash + 1e-9:
                            continue
                        cash -= value + fee
                        shares[j] += qty[j]
                        cost_out[i] += fee + qty[j] * o[j] * slip
                        trades.append((day, tickers[j], qty[j], p, value, fee))
            pending = None

        last_mark = np.where(np.isnan(c), last_mark, c)
        held = np.nansum(shares * np.nan_to_num(last_mark))
        eq_out[i] = cash + held
        cash_out[i] = cash
        hold_out[i] = shares

        if day in target_rows:
            pending = target_rows[day]

    equity = pd.Series(eq_out, dates, name="equity")
    holdings = pd.DataFrame(hold_out, dates, tickers)
    marks = prices.close.ffill()
    weights = (holdings * marks).div(equity, axis=0).fillna(0.0)
    trade_df = pd.DataFrame(trades, columns=["date", "ticker", "qty", "price", "value", "fee"])
    return BacktestResult(equity, pd.Series(cash_out, dates, name="cash"), holdings,
                          weights, trade_df, pd.Series(cost_out, dates, name="costs"))


def constant_weights(prices: Prices, weights: dict[str, float],
                     dates: pd.DatetimeIndex) -> pd.DataFrame:
    """A fixed-weight portfolio rebalanced on `dates`; assets join once they have data."""
    rows = {}
    for d in dates:
        alive = prices.close.loc[d].notna()
        w = pd.Series({t: v for t, v in weights.items() if alive.get(t, False)}, dtype=float)
        if w.sum() > 0:
            w = w / w.sum() * sum(weights.values())
        rows[d] = w
    return pd.DataFrame(rows).T.reindex(columns=prices.tickers).fillna(0.0)
