"""Performance statistics, and the statistics that say how far to trust them.

A backtest Sharpe ratio is an estimate with a wide error bar, and it is biased
upward whenever several variants were tried and the best was kept. So besides
the usual numbers this reports:

* a block-bootstrap confidence interval for the Sharpe ratio, which respects
  the fact that returns cluster in time;
* the Probabilistic Sharpe Ratio: the probability the true Sharpe exceeds a
  benchmark given the sample length, skew and fat tails;
* the Deflated Sharpe Ratio: the same probability, after raising the bar to
  the best Sharpe you would expect from N tries of a worthless strategy.

Bailey & López de Prado, "The Sharpe Ratio Efficient Frontier" (2012) and
"The Deflated Sharpe Ratio" (2014).
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

ANN = 252
EULER = 0.5772156649015329
_N = NormalDist()


def cagr(returns: pd.Series) -> float:
    growth = float((1 + returns).prod())
    years = len(returns) / ANN
    return growth ** (1 / years) - 1 if years > 0 and growth > 0 else float("nan")


def ann_vol(returns: pd.Series) -> float:
    return float(returns.std(ddof=1) * math.sqrt(ANN))


def sharpe(returns: pd.Series, rf: float = 0.0) -> float:
    ex = returns - rf / ANN
    sd = ex.std(ddof=1)
    return float(ex.mean() / sd * math.sqrt(ANN)) if sd > 0 else float("nan")


def sortino(returns: pd.Series, rf: float = 0.0) -> float:
    ex = returns - rf / ANN
    downside = np.sqrt((np.minimum(ex, 0) ** 2).mean())
    return float(ex.mean() / downside * math.sqrt(ANN)) if downside > 0 else float("nan")


def drawdown(returns: pd.Series) -> pd.Series:
    wealth = (1 + returns).cumprod()
    return wealth / wealth.cummax() - 1


def max_drawdown(returns: pd.Series) -> float:
    return float(drawdown(returns).min())


def longest_drawdown_days(returns: pd.Series) -> int:
    under = drawdown(returns) < 0
    longest = run = 0
    for flag in under:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return longest


def calendar_returns(returns: pd.Series) -> pd.Series:
    return (1 + returns).groupby(returns.index.year).prod() - 1


def probabilistic_sharpe(returns: pd.Series, sr_benchmark_ann: float = 0.0) -> float:
    """P(true Sharpe > benchmark). Works in per-period units internally."""
    r = returns.dropna()
    t = len(r)
    if t < 30 or r.std(ddof=1) == 0:
        return float("nan")
    sr = r.mean() / r.std(ddof=1)
    sr_star = sr_benchmark_ann / math.sqrt(ANN)
    skew = float(r.skew())
    kurt = float(r.kurt()) + 3.0          # pandas gives excess kurtosis
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        return float("nan")
    z = (sr - sr_star) * math.sqrt(t - 1) / math.sqrt(denom)
    return _N.cdf(z)


def expected_max_sharpe(n_trials: int, sharpe_var_ann: float) -> float:
    """Expected best annualised Sharpe among n_trials strategies with zero true skill."""
    if n_trials < 2:
        return 0.0
    sd = math.sqrt(max(sharpe_var_ann, 0.0))
    return sd * ((1 - EULER) * _N.inv_cdf(1 - 1 / n_trials)
                 + EULER * _N.inv_cdf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(returns: pd.Series, n_trials: int, sharpe_var_ann: float) -> float:
    return probabilistic_sharpe(returns, expected_max_sharpe(n_trials, sharpe_var_ann))


def bootstrap_sharpe_ci(returns: pd.Series, block: int = 21, n: int = 2000,
                        alpha: float = 0.05, seed: int = 0) -> tuple[float, float]:
    """Moving-block bootstrap interval for the annualised Sharpe ratio."""
    r = returns.dropna().to_numpy()
    t = len(r)
    if t < block * 4:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    blocks = int(np.ceil(t / block))
    out = np.empty(n)
    for k in range(n):
        starts = rng.integers(0, t - block + 1, blocks)
        sample = np.concatenate([r[s:s + block] for s in starts])[:t]
        sd = sample.std(ddof=1)
        out[k] = sample.mean() / sd * math.sqrt(ANN) if sd > 0 else np.nan
    lo, hi = np.nanquantile(out, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def summary(returns: pd.Series, equity: pd.Series | None = None,
            turnover: float | None = None, costs: pd.Series | None = None) -> dict:
    r = returns.dropna()
    out = {
        "start": r.index[0].date().isoformat(),
        "end": r.index[-1].date().isoformat(),
        "years": round(len(r) / ANN, 1),
        "cagr": cagr(r),
        "ann_vol": ann_vol(r),
        "sharpe": sharpe(r),
        "sortino": sortino(r),
        "max_drawdown": max_drawdown(r),
        "longest_drawdown_days": longest_drawdown_days(r),
        "calmar": cagr(r) / abs(max_drawdown(r)) if max_drawdown(r) < 0 else float("nan"),
        "worst_day": float(r.min()),
        "best_day": float(r.max()),
        "skew": float(r.skew()),
        "excess_kurtosis": float(r.kurt()),
        "pct_positive_months": float(((1 + r).groupby(r.index.to_period("M")).prod() > 1).mean()),
        "psr_vs_0": probabilistic_sharpe(r, 0.0),
    }
    lo, hi = bootstrap_sharpe_ci(r)
    out["sharpe_ci95_low"], out["sharpe_ci95_high"] = lo, hi
    if turnover is not None:
        out["turnover_per_year"] = turnover
    if costs is not None and equity is not None:
        out["cost_drag_per_year"] = float((costs / equity.shift(1)).fillna(0).sum() / (len(r) / ANN))
    return out
