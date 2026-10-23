"""Everything you should look at before trusting the strategy with money.

`evaluate` runs:

1. The configured strategy, at the configured costs.
2. Two benchmarks through the same engine and costs: buy-and-hold of the
   benchmark ticker, and an equal-weight portfolio of the universe rebalanced
   monthly. A strategy that does not beat these after costs is not worth the
   effort of running it.
3. The strategy at 2x and 3x costs. If the result depends on costs being low,
   it will disappoint live.
4. A grid of reasonable variants. Every variant is a trial, and the number of
   trials feeds the Deflated Sharpe Ratio.
5. Walk-forward selection: each year, pick the variant with the best Sharpe
   over the previous five years and record how it did in the year it had not
   seen. The stitched result is the honest estimate; the full-sample best is
   the optimistic one.
6. Returns year by year, so a single good stretch cannot hide a weak decade.
"""
from __future__ import annotations

import copy
import itertools
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest, metrics, strategy
from .config import Config
from .data import Prices

GRID = {
    "lookbacks": [(21, 63, 126, 252), (63, 126, 252), (126, 252), (21, 63, 126)],
    "rebalance": ["weekly", "monthly"],
    "band": [0.02, 0.05],
}


def run_strategy(prices: Prices, cfg: Config) -> backtest.BacktestResult:
    dates = strategy.rebalance_dates(prices.close.index, cfg.execution.rebalance)
    targets = strategy.target_weights(prices, cfg.strategy, dates)
    return backtest.run(prices, targets, cfg.execution, cfg.backtest.initial_capital)


def live_window(result: backtest.BacktestResult) -> pd.Timestamp:
    """First day the strategy held anything; before that it is warming up."""
    invested = result.weights.abs().sum(axis=1) > 0
    return invested.idxmax() if invested.any() else result.equity.index[0]


def _variant(cfg: Config, **changes) -> Config:
    c = copy.deepcopy(cfg)
    for k, v in changes.items():
        if k == "lookbacks":
            c.strategy.lookbacks = tuple(v)
        elif k in ("rebalance", "band"):
            setattr(c.execution, k, v)
        else:
            raise KeyError(k)
    return c


def _costs(cfg: Config, mult: float) -> Config:
    c = copy.deepcopy(cfg)
    c.execution.slippage_bps *= mult
    c.execution.commission_per_order *= mult
    c.execution.commission_bps *= mult
    return c


def walk_forward(returns_by_trial: dict[str, pd.Series], train_years: int = 5) -> tuple[pd.Series, list[dict]]:
    frame = pd.DataFrame(returns_by_trial).dropna(how="all")
    years = sorted(set(frame.index.year))
    pieces, choices = [], []
    for y in years:
        train = frame[(frame.index.year >= y - train_years) & (frame.index.year < y)]
        if len(set(train.index.year)) < train_years:
            continue
        scores = {k: metrics.sharpe(train[k].dropna()) for k in frame.columns}
        best = max(scores, key=lambda k: -np.inf if np.isnan(scores[k]) else scores[k])
        test = frame.loc[frame.index.year == y, best]
        pieces.append(test)
        choices.append({"year": y, "chosen": best, "train_sharpe": scores[best],
                        "test_return": float((1 + test).prod() - 1)})
    oos = pd.concat(pieces) if pieces else pd.Series(dtype=float)
    return oos, choices


def evaluate(prices: Prices, cfg: Config, grid: dict | None = None) -> dict:
    grid = GRID if grid is None else grid
    base = run_strategy(prices, cfg)
    start = live_window(base)
    window = base.equity.index[base.equity.index >= start]

    def stats(res: backtest.BacktestResult) -> dict:
        eq = res.equity.loc[window]
        return metrics.summary(eq.pct_change().dropna(), eq, res.turnover(), res.costs.loc[window])

    report = {"config": asdict(cfg), "strategy": stats(base)}

    monthly = strategy.rebalance_dates(prices.close.index, "monthly")
    bench = {cfg.benchmark: 1.0}
    bh = backtest.run(prices, backtest.constant_weights(prices, bench, monthly),
                      cfg.execution, cfg.backtest.initial_capital)
    ew = {t: 1.0 / len(cfg.universe) for t in cfg.universe}
    eqw = backtest.run(prices, backtest.constant_weights(prices, ew, monthly),
                       cfg.execution, cfg.backtest.initial_capital)
    report["benchmarks"] = {f"buy_and_hold_{cfg.benchmark}": stats(bh),
                            "equal_weight_monthly": stats(eqw)}

    report["cost_sensitivity"] = {}
    for mult in (2, 3):
        report["cost_sensitivity"][f"{mult}x_costs"] = stats(run_strategy(prices, _costs(cfg, mult)))

    trials = {}
    keys = list(grid)
    for combo in itertools.product(*(grid[k] for k in keys)):
        label = ", ".join(f"{k}={v}" for k, v in zip(keys, combo))
        res = run_strategy(prices, _variant(cfg, **dict(zip(keys, combo))))
        trials[label] = res.equity.loc[window].pct_change().dropna()
    trial_sharpes = {k: metrics.sharpe(v) for k, v in trials.items()}
    sr_var = float(np.nanvar(list(trial_sharpes.values()), ddof=1)) if len(trials) > 1 else 0.0
    n_trials = len(trials) + 1                      # the grid plus the base config
    base_rets = base.equity.loc[window].pct_change().dropna()
    report["overfitting"] = {
        "n_trials": n_trials,
        "trial_sharpes": trial_sharpes,
        "expected_max_sharpe_if_no_skill": metrics.expected_max_sharpe(n_trials, sr_var),
        "deflated_sharpe_ratio": metrics.deflated_sharpe(base_rets, n_trials, sr_var),
    }

    oos, choices = walk_forward(trials)
    report["walk_forward"] = {"choices": choices,
                              "out_of_sample": metrics.summary(oos) if len(oos) > 252 else None}
    report["calendar_returns"] = {
        "strategy": metrics.calendar_returns(base_rets).to_dict(),
        f"buy_and_hold_{cfg.benchmark}": metrics.calendar_returns(
            bh.equity.loc[window].pct_change().dropna()).to_dict(),
    }
    report["_series"] = {"strategy": base.equity.loc[window], "buy_and_hold": bh.equity.loc[window],
                         "equal_weight": eqw.equity.loc[window], "trades": base.trades}
    return report


# --- presentation -----------------------------------------------------------

def _fmt(key: str, v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    pct = {"cagr", "ann_vol", "max_drawdown", "worst_day", "best_day", "pct_positive_months",
           "cost_drag_per_year", "psr_vs_0"}
    if key in pct:
        return f"{v:.1%}"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


ROWS = ["start", "end", "years", "cagr", "ann_vol", "sharpe", "sharpe_ci95_low", "sharpe_ci95_high",
        "sortino", "max_drawdown", "longest_drawdown_days", "calmar", "worst_day",
        "pct_positive_months", "psr_vs_0", "turnover_per_year", "cost_drag_per_year"]


def to_markdown(report: dict) -> str:
    cols = {"Strategy": report["strategy"], **{k: v for k, v in report["benchmarks"].items()},
            **report["cost_sensitivity"]}
    wf = report["walk_forward"]["out_of_sample"]
    if wf:
        cols["Walk-forward OOS"] = wf
    lines = ["# Backtest report", "",
             "| | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for r in ROWS:
        lines.append(f"| {r} | " + " | ".join(_fmt(r, c.get(r)) for c in cols.values()) + " |")

    o = report["overfitting"]
    lines += ["", "## Overfitting check", "",
              f"- Variants tried: **{o['n_trials']}**",
              f"- Best Sharpe expected from that many tries with no skill: **{o['expected_max_sharpe_if_no_skill']:.2f}**",
              f"- Deflated Sharpe Ratio (probability the edge is real after accounting for the tries): "
              f"**{_fmt('psr_vs_0', o['deflated_sharpe_ratio'])}**",
              "", "Read it this way: below about 90%, the backtest does not separate the strategy from luck.",
              "", "| Variant | Sharpe |", "|---|---|"]
    for k, v in sorted(o["trial_sharpes"].items(), key=lambda kv: -np.nan_to_num(kv[1], nan=-9)):
        lines.append(f"| {k} | {_fmt('sharpe', v)} |")

    lines += ["", "## Walk-forward choices", "", "| Year | Chosen variant | Train Sharpe | Test-year return |",
              "|---|---|---|---|"]
    for c in report["walk_forward"]["choices"]:
        lines.append(f"| {c['year']} | {c['chosen']} | {c['train_sharpe']:.2f} | {c['test_return']:.1%} |")

    cal = report["calendar_returns"]
    names = list(cal)
    years = sorted(set().union(*[set(v) for v in cal.values()]))
    lines += ["", "## Calendar returns", "", "| Year | " + " | ".join(names) + " |",
              "|---|" + "---|" * len(names)]
    for y in years:
        lines.append(f"| {y} | " + " | ".join(_fmt("cagr", cal[n].get(y)) for n in names) + " |")
    return "\n".join(lines) + "\n"


def save(report: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(to_markdown(report))
    plain = {k: v for k, v in report.items() if not k.startswith("_")}
    (out / "report.json").write_text(json.dumps(plain, indent=2, default=str))
    s = report["_series"]
    pd.DataFrame({"strategy": s["strategy"], "buy_and_hold": s["buy_and_hold"],
                  "equal_weight": s["equal_weight"]}).to_csv(out / "equity.csv")
    s["trades"].to_csv(out / "trades.csv", index=False)
    return out / "report.md"
