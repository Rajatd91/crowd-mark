"""Diversified trend following with volatility targeting.

The idea is old and well documented: assets that have risen over the past
months tend to keep rising for a while, across equities, bonds and commodities
(Moskowitz, Ooi & Pedersen, "Time Series Momentum", 2012; Hurst, Ooi &
Pedersen, "A Century of Evidence on Trend-Following Investing", 2017). It is
not a secret and it does not always work: it loses in choppy, trendless years
and when trends reverse sharply. Its value is that it tends to cut exposure in
prolonged sell-offs.

At each rebalance close:
  1. Score each asset's trend over several horizons as a t-statistic
     (return divided by the volatility expected over that horizon), clip, and
     average. Score in [-1, 1].
  2. Size each asset inversely to its own volatility, so a calm bond fund and
     a volatile equity fund carry similar risk.
  3. Scale the whole book so its forecast volatility, using an EWMA covariance
     matrix, equals the target.
  4. Cap single-asset weight and gross exposure.

Everything at date t uses data up to the close of t and nothing later. The
backtest fills at the open of t+1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .data import Prices

ANN = 252


def ewma_vol(returns: pd.DataFrame, span: int) -> pd.DataFrame:
    return np.sqrt((returns ** 2).ewm(span=span, min_periods=span).mean() * ANN)


def trend_score(close: pd.DataFrame, vol: pd.DataFrame, lookbacks, cap: float) -> pd.DataFrame:
    parts = []
    for n in lookbacks:
        log_ret = np.log(close / close.shift(n))
        t_stat = log_ret / (vol * np.sqrt(n / ANN))
        parts.append(t_stat.clip(-cap, cap) / cap)
    # Mean of the horizons, missing if any horizon is missing: an asset needs a
    # full year of history before it can be held.
    return sum(parts) / len(parts)


def ewma_cov(returns: pd.DataFrame, span: int) -> pd.DataFrame:
    """Annualised EWMA covariance, one matrix per day, as a (date, asset) x asset frame."""
    return returns.ewm(span=span, min_periods=span).cov() * ANN


def _weights(score: np.ndarray, vol: np.ndarray, cov: np.ndarray,
             cfg: StrategyConfig) -> np.ndarray:
    out = np.zeros(len(score))
    ok = np.isfinite(score) & np.isfinite(vol) & (vol > 0)
    raw = np.zeros(len(score))
    raw[ok] = score[ok] / vol[ok]
    if cfg.long_only:
        raw = np.maximum(raw, 0.0)
    held = np.nonzero(raw)[0]
    if len(held) == 0:
        return out
    r = raw[held]
    sub = cov[np.ix_(held, held)]
    if not np.isfinite(sub).all():
        # No usable covariance yet: fall back to treating assets as independent.
        port_var = float(np.sum(r ** 2 * vol[held] ** 2))
    else:
        port_var = float(r @ sub @ r)
    if port_var <= 0:
        return out
    w = np.clip(r * (cfg.target_vol / np.sqrt(port_var)), -cfg.max_weight, cfg.max_weight)
    gross = np.abs(w).sum()
    if gross > cfg.max_gross:
        w *= cfg.max_gross / gross
    out[held] = w
    return out


def weights_for_day(score: pd.Series, vol: pd.Series, cov: pd.DataFrame,
                    cfg: StrategyConfig) -> pd.Series:
    cols = score.index
    w = _weights(score.to_numpy(float), vol.reindex(cols).to_numpy(float),
                 cov.reindex(index=cols, columns=cols).to_numpy(float), cfg)
    return pd.Series(w, index=cols)


def rebalance_dates(index: pd.DatetimeIndex, how: str) -> pd.DatetimeIndex:
    """The last trading day of each period, so a weekly book trades Monday open
    on Friday's close."""
    if how == "daily":
        return index
    period = {"weekly": "W-FRI", "monthly": "M"}[how]
    s = index.to_series()
    last = s.groupby(index.to_period(period)).max()
    return pd.DatetimeIndex(last.values)


def target_weights(prices: Prices, cfg: StrategyConfig,
                   dates: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Target weights at each of `dates` (default: every day)."""
    rets = prices.returns()
    vol = ewma_vol(rets, cfg.vol_span)
    score = trend_score(prices.close, vol, cfg.lookbacks, cfg.signal_cap)
    n = len(prices.tickers)
    cov = ewma_cov(rets, cfg.cov_span).to_numpy(float).reshape(len(rets), n, n)
    pos = pd.Series(np.arange(len(rets)), index=rets.index)
    dates = prices.close.index if dates is None else dates
    s, v = score.to_numpy(float), vol.to_numpy(float)
    rows = np.zeros((len(dates), n))
    for k, d in enumerate(dates):
        i = pos[d]
        rows[k] = _weights(s[i], v[i], cov[i], cfg)
    return pd.DataFrame(rows, index=dates, columns=prices.tickers)


def diagnostics(prices: Prices, cfg: StrategyConfig) -> pd.DataFrame:
    """Latest score, volatility and target weight per asset, for humans."""
    rets = prices.returns()
    vol = ewma_vol(rets, cfg.vol_span)
    score = trend_score(prices.close, vol, cfg.lookbacks, cfg.signal_cap)
    last = prices.close.index[-1]
    w = target_weights(prices, cfg, pd.DatetimeIndex([last])).iloc[0]
    return pd.DataFrame({
        "close": prices.close.loc[last],
        "trend_score": score.loc[last],
        "ann_vol": vol.loc[last],
        "target_weight": w,
    }).sort_values("target_weight", ascending=False)
