"""Command line.

    python -m trendbot backtest   [--config FILE] [--data SOURCE]
    python -m trendbot research   [--config FILE] [--data SOURCE] [--out DIR]
    python -m trendbot signal     [--config FILE]
    python -m trendbot rebalance  [--config FILE] [--execute] [--live] [--force]
    python -m trendbot stop | resume
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from . import data, live, metrics, research, strategy
from .broker import AlpacaBroker, PaperBroker
from .config import load_config


def _load(args):
    cfg = load_config(args.config)
    if getattr(args, "data", None):
        cfg.data.source = args.data
    return cfg


def cmd_backtest(args) -> int:
    cfg = _load(args)
    prices = data.load(cfg, refresh=args.refresh)
    res = research.run_strategy(prices, cfg)
    start = research.live_window(res)
    eq = res.equity.loc[start:]
    stats = metrics.summary(eq.pct_change().dropna(), eq, res.turnover(), res.costs.loc[start:])
    for k in research.ROWS:
        print(f"{k:>24}: {research._fmt(k, stats.get(k))}")
    print(f"{'final equity':>24}: {eq.iloc[-1]:,.2f} from {cfg.backtest.initial_capital:,.2f}")
    print(f"{'trades':>24}: {len(res.trades)}")
    return 0


def cmd_research(args) -> int:
    cfg = _load(args)
    prices = data.load(cfg, refresh=args.refresh)
    report = research.evaluate(prices, cfg)
    path = research.save(report, args.out)
    print(research.to_markdown(report))
    print(f"saved to {path.parent}/")
    return 0


def cmd_signal(args) -> int:
    cfg = _load(args)
    prices = live.completed_bars(data.load(cfg, refresh=True))
    print(f"signal as of close {prices.close.index[-1].date()}")
    table = strategy.diagnostics(prices, cfg.strategy).loc[cfg.universe]
    with pd.option_context("display.float_format", "{:.3f}".format):
        print(table.sort_values("target_weight", ascending=False))
    print(f"gross exposure {table['target_weight'].abs().sum():.1%}, rest in cash")
    return 0


def _broker(cfg, live_flag: bool):
    if cfg.broker.kind == "paper":
        if live_flag:
            raise SystemExit("--live makes no sense with the paper broker")
        return PaperBroker(cfg.broker.state_dir, cfg.backtest.initial_capital,
                           cfg.execution.commission_per_order, cfg.execution.commission_bps)
    if cfg.broker.kind == "alpaca":
        if live_flag and not cfg.broker.allow_live:
            raise SystemExit("--live refused: set broker.allow_live = true in the config first")
        return AlpacaBroker(live=live_flag)
    raise SystemExit(f"unknown broker: {cfg.broker.kind}")


def cmd_rebalance(args) -> int:
    cfg = _load(args)
    if args.live and not args.execute:
        raise SystemExit("--live only applies together with --execute")
    if args.live:
        print("LIVE TRADING with real money. Ctrl-C within 10 seconds to abort.")
        import time
        time.sleep(10)
    prices = live.completed_bars(data.load(cfg, refresh=True))
    broker = _broker(cfg, args.live)
    record = live.rebalance(cfg, prices, broker, execute=args.execute,
                            require_open=cfg.broker.kind != "paper", force=args.force)
    print(live.summary_text(record))
    for n in record["notes"]:
        print("  note:", n)
    return 1 if record["blocked"] else 0


def cmd_stop(args) -> int:
    cfg = _load(args)
    p = Path(cfg.broker.state_dir) / cfg.risk.kill_switch_file
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("stopped\n")
    print(f"kill switch set at {p}; no orders will be sent until `resume`")
    return 0


def cmd_resume(args) -> int:
    cfg = _load(args)
    p = Path(cfg.broker.state_dir) / cfg.risk.kill_switch_file
    p.unlink(missing_ok=True)
    print("kill switch cleared")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="trendbot")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, with_data=True):
        p.add_argument("--config", default=None, help="TOML config file")
        if with_data:
            p.add_argument("--data", choices=["yfinance", "csv", "synthetic"], help="override data.source")
            p.add_argument("--refresh", action="store_true", help="re-download prices")
        return p

    common(sub.add_parser("backtest", help="run the strategy once and print statistics")).set_defaults(fn=cmd_backtest)
    r = common(sub.add_parser("research", help="full evaluation: benchmarks, costs, walk-forward, overfitting"))
    r.add_argument("--out", default="reports")
    r.set_defaults(fn=cmd_research)
    common(sub.add_parser("signal", help="today's target weights"), with_data=False).set_defaults(fn=cmd_signal)
    rb = common(sub.add_parser("rebalance", help="plan orders, and send them with --execute"), with_data=False)
    rb.add_argument("--execute", action="store_true", help="actually send orders")
    rb.add_argument("--live", action="store_true", help="use a live (real money) account")
    rb.add_argument("--force", action="store_true", help="rebalance even if not scheduled")
    rb.set_defaults(fn=cmd_rebalance)
    common(sub.add_parser("stop", help="set the kill switch"), with_data=False).set_defaults(fn=cmd_stop)
    common(sub.add_parser("resume", help="clear the kill switch"), with_data=False).set_defaults(fn=cmd_resume)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
