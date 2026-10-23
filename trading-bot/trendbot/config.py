"""Every number the strategy, the backtest and the live runner use, in one place.

Defaults are deliberately conservative: no leverage, long only, a 10% volatility
target, whole shares, and costs that are pessimistic for a liquid ETF. Load a
TOML file to change them; anything the file leaves out keeps its default.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path


@dataclass
class StrategyConfig:
    # Trend horizons in trading days (about 1, 3, 6 and 12 months). Several
    # horizons are averaged so no single lookback has to be right.
    lookbacks: tuple[int, ...] = (21, 63, 126, 252)
    vol_span: int = 60           # EWMA span for each asset's volatility
    cov_span: int = 120          # EWMA span for the covariance matrix
    signal_cap: float = 2.0      # trend t-stat at which conviction is full
    target_vol: float = 0.10     # annualised portfolio volatility aimed for
    max_weight: float = 0.25     # largest share of equity in one asset
    max_gross: float = 1.0       # 1.0 means no leverage
    long_only: bool = True


@dataclass
class ExecutionConfig:
    rebalance: str = "weekly"    # daily, weekly or monthly
    band: float = 0.05           # ignore weight changes smaller than this; per-order
                                 # fees make small trades expensive on a small account
    commission_per_order: float = 1.0
    commission_bps: float = 0.0
    slippage_bps: float = 5.0    # paid on every fill, both directions
    fractional: bool = False
    min_trade_value: float = 50.0


@dataclass
class RiskConfig:
    max_order_fraction: float = 0.30   # no single order above this share of equity
    max_daily_loss: float = 0.03       # halt if equity fell this much since yesterday
    max_staleness_days: int = 4        # refuse to trade on data older than this
    max_price_jump: float = 0.25       # refuse if a price moved this much in a day
    max_orders: int = 20
    limit_buffer_bps: float = 50.0     # marketable limit, this far through the last price
    kill_switch_file: str = "KILL"


@dataclass
class BacktestConfig:
    initial_capital: float = 10_000.0
    start: str | None = "2005-01-01"
    end: str | None = None


@dataclass
class DataConfig:
    source: str = "yfinance"           # yfinance, csv or synthetic
    csv_dir: str = "data"
    cache_dir: str = "data_cache"


@dataclass
class BrokerConfig:
    kind: str = "paper"                # paper or alpaca
    state_dir: str = "state"
    allow_live: bool = False           # live trading also needs --live on the command line


@dataclass
class Config:
    # A diversified ETF set: US, international and emerging equity, Treasuries,
    # gold, commodities and real estate. Long history, deep liquidity.
    universe: list[str] = field(default_factory=lambda: [
        "SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ",
    ])
    benchmark: str = "SPY"
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    data: DataConfig = field(default_factory=DataConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)


def _apply(obj, values: dict, path: str = "") -> None:
    known = {f.name: f for f in fields(obj)}
    for key, value in values.items():
        if key not in known:
            raise ValueError(f"unknown config key: {path}{key}")
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"{path}{key} must be a table")
            _apply(current, value, f"{path}{key}.")
        else:
            if isinstance(current, tuple):
                value = tuple(value)
            setattr(obj, key, value)


def load_config(path: str | Path | None = None) -> Config:
    cfg = Config()
    if path:
        with open(path, "rb") as fh:
            _apply(cfg, tomllib.load(fh))
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    s, e, r = cfg.strategy, cfg.execution, cfg.risk
    if not cfg.universe:
        raise ValueError("universe is empty")
    if not s.lookbacks or min(s.lookbacks) < 2:
        raise ValueError("lookbacks must be positive and at least 2 days")
    if not 0 < s.target_vol <= 1:
        raise ValueError("target_vol must be in (0, 1]")
    if not 0 < s.max_weight <= s.max_gross:
        raise ValueError("max_weight must be in (0, max_gross]")
    if s.max_gross > 1.0 and s.long_only:
        raise ValueError("max_gross above 1 means borrowing; this runner does not support leverage")
    if e.rebalance not in ("daily", "weekly", "monthly"):
        raise ValueError("rebalance must be daily, weekly or monthly")
    if e.slippage_bps < 0 or e.commission_bps < 0 or e.commission_per_order < 0:
        raise ValueError("costs cannot be negative")
    if not 0 < r.max_order_fraction <= 1:
        raise ValueError("max_order_fraction must be in (0, 1]")
