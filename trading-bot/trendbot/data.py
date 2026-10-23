"""Prices in, clean aligned panels out.

Everything downstream works on two DataFrames, `open` and `close`, indexed by
trading day with one column per ticker, both adjusted for splits and dividends.
Signals are computed from closes; trades fill at the next day's open.

Three sources: Yahoo via yfinance (cached to CSV), a folder of CSV files, or a
seeded synthetic market used by the tests and for dry runs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class Prices:
    open: pd.DataFrame
    close: pd.DataFrame

    @property
    def tickers(self) -> list[str]:
        return list(self.close.columns)

    def returns(self) -> pd.DataFrame:
        return self.close.pct_change(fill_method=None)

    def slice(self, start=None, end=None) -> "Prices":
        return Prices(self.open.loc[start:end], self.close.loc[start:end])


def clean(open_: pd.DataFrame, close: pd.DataFrame, max_gap: int = 3) -> Prices:
    """Align, sort, and patch short gaps. Long gaps stay missing, which keeps
    an asset out of the portfolio until it has real data again."""
    idx = open_.index.union(close.index).sort_values()
    cols = sorted(set(open_.columns) | set(close.columns))
    open_ = open_.reindex(index=idx, columns=cols).astype(float)
    close = close.reindex(index=idx, columns=cols).astype(float)

    bad = (close <= 0) | (open_ <= 0)
    if bad.any().any():
        log.warning("dropping %d non-positive prices", int(bad.sum().sum()))
        close = close.mask(close <= 0)
        open_ = open_.mask(open_ <= 0)

    # A missing open with a real close that day is filled from the close. A day
    # with no bar at all keeps a missing open, so nothing can trade on it; the
    # close is carried forward only so the position can still be valued.
    open_ = open_.fillna(close)
    close = close.ffill(limit=max_gap)
    close = close.dropna(how="all")
    open_ = open_.reindex(close.index)

    jumps = close.pct_change(fill_method=None).abs() > 0.5
    for day, ticker in zip(*np.nonzero(jumps.to_numpy())):
        log.warning("%s moved more than 50%% on %s; check the data",
                    close.columns[ticker], close.index[day].date())
    return Prices(open_, close)


# --- sources ---------------------------------------------------------------

def load_yfinance(tickers: list[str], start: str | None, end: str | None,
                  cache_dir: str | Path, refresh: bool = False) -> Prices:
    """Adjusted daily bars from Yahoo, cached per ticker as CSV."""
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    opens, closes = {}, {}
    for t in tickers:
        path = cache / f"{t}.csv"
        if refresh or not path.exists() or _stale(path):
            frame = _download(t)
            frame.to_csv(path)
        frame = pd.read_csv(path, index_col=0, parse_dates=True)
        opens[t], closes[t] = frame["Open"], frame["Close"]
    prices = clean(pd.DataFrame(opens), pd.DataFrame(closes))
    return prices.slice(start, end)


def _stale(path: Path) -> bool:
    age = pd.Timestamp.now() - pd.Timestamp(path.stat().st_mtime, unit="s")
    return age > pd.Timedelta(hours=12)


def _download(ticker: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise SystemExit("yfinance is not installed: pip install yfinance") from exc
    frame = yf.download(ticker, period="max", auto_adjust=True, progress=False,
                        multi_level_index=False)
    if frame is None or frame.empty:
        raise RuntimeError(f"no data returned for {ticker}")
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    return frame[["Open", "High", "Low", "Close", "Volume"]]


def load_csv_dir(tickers: list[str], directory: str | Path,
                 start: str | None = None, end: str | None = None) -> Prices:
    """One file per ticker, TICKER.csv, with Date, Open, Close and optionally
    Adj Close. When Adj Close is present the open is adjusted by the same
    factor, so a dividend or split does not look like a price move."""
    opens, closes = {}, {}
    for t in tickers:
        frame = pd.read_csv(Path(directory) / f"{t}.csv", parse_dates=["Date"],
                            index_col="Date").sort_index()
        if "Adj Close" in frame:
            factor = frame["Adj Close"] / frame["Close"]
            opens[t], closes[t] = frame["Open"] * factor, frame["Adj Close"]
        else:
            opens[t], closes[t] = frame["Open"], frame["Close"]
    return clean(pd.DataFrame(opens), pd.DataFrame(closes)).slice(start, end)


def synthetic(tickers: list[str], days: int = 3000, seed: int = 7,
              start: str = "2010-01-04") -> Prices:
    """A correlated market with slowly changing drifts, so trends exist but are
    noisy. For tests and dry runs only: it says nothing about real markets."""
    rng = np.random.default_rng(seed)
    n = len(tickers)
    idx = pd.bdate_range(start, periods=days)
    vols = rng.uniform(0.10, 0.30, n) / np.sqrt(252)
    corr = 0.3 + 0.7 * np.eye(n)
    chol = np.linalg.cholesky(corr)
    drift = np.zeros(n)
    rets = np.empty((days, n))
    for d in range(days):
        if d % 120 == 0:
            drift = rng.normal(0, 0.15, n) / 252
        rets[d] = drift + vols * (chol @ rng.standard_normal(n))
    close = 100 * np.exp(np.cumsum(rets, axis=0))
    gap = rng.normal(0, 0.3, (days, n)) * vols
    open_ = np.vstack([close[:1], close[:-1]]) * np.exp(gap)
    return clean(pd.DataFrame(open_, idx, tickers), pd.DataFrame(close, idx, tickers))


def load(cfg, refresh: bool = False) -> Prices:
    tickers = list(dict.fromkeys(cfg.universe + [cfg.benchmark]))
    src = cfg.data.source
    if src == "yfinance":
        return load_yfinance(tickers, cfg.backtest.start, cfg.backtest.end,
                             cfg.data.cache_dir, refresh)
    if src == "csv":
        return load_csv_dir(tickers, cfg.data.csv_dir, cfg.backtest.start, cfg.backtest.end)
    if src == "synthetic":
        return synthetic(tickers)
    raise ValueError(f"unknown data source: {src}")
