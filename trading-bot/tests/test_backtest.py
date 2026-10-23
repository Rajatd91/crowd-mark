import numpy as np
import pandas as pd
import pytest

from trendbot import backtest, research, strategy
from trendbot.config import Config, ExecutionConfig
from trendbot.data import Prices, clean, synthetic

TICKERS = ["AAA", "BBB", "CCC", "DDD"]


@pytest.fixture(scope="module")
def prices():
    return synthetic(TICKERS, days=900, seed=3)


def free() -> ExecutionConfig:
    return ExecutionConfig(rebalance="daily", band=0.0, commission_per_order=0.0,
                           commission_bps=0.0, slippage_bps=0.0, fractional=True,
                           min_trade_value=0.0)


@pytest.mark.parametrize("factor", [3.0, 0.3])
def test_targets_do_not_look_ahead(prices, factor):
    """Changing the future must not change any decision made before it. Several
    cut dates and both directions, because a single cut where the book happens
    to be flat, or a shock in the direction it cannot act on, proves nothing."""
    cfg = Config(universe=TICKERS, benchmark="AAA")
    base = strategy.target_weights(prices, cfg.strategy)
    for i in range(300, 850, 50):
        cut = prices.close.index[i]
        future = prices.close.index > cut
        shocked = Prices(prices.open.copy(), prices.close.copy())
        shocked.close.loc[future] *= factor
        shocked.open.loc[future] *= factor
        b = strategy.target_weights(shocked, cfg.strategy).loc[:cut]
        pd.testing.assert_frame_equal(base.loc[:cut], b)


@pytest.mark.parametrize("factor", [3.0, 0.3])
def test_equity_before_shock_is_unchanged(prices, factor):
    cfg = Config(universe=TICKERS, benchmark="AAA")
    cfg.execution.rebalance = "daily"
    base = research.run_strategy(prices, cfg).equity
    for i in (400, 550, 700, 850):
        cut = prices.close.index[i]
        shocked = Prices(prices.open.copy(), prices.close.copy())
        later = prices.close.index > cut
        shocked.close.loc[later] *= factor
        shocked.open.loc[later] *= factor
        b = research.run_strategy(shocked, cfg).equity.loc[:cut]
        pd.testing.assert_series_equal(base.loc[:cut], b)


def test_trades_fill_at_next_open(prices):
    d0 = prices.close.index[10]
    targets = pd.DataFrame({"AAA": [1.0]}, index=[d0]).reindex(columns=TICKERS).fillna(0.0)
    res = backtest.run(prices, targets, free(), 1000.0)
    t = res.trades.iloc[0]
    assert t["date"] == prices.close.index[11]
    assert t["price"] == pytest.approx(prices.open.loc[prices.close.index[11], "AAA"])


def test_buy_and_hold_tracks_price(prices):
    d0 = prices.close.index[10]
    targets = pd.DataFrame({"AAA": [1.0]}, index=[d0]).reindex(columns=TICKERS).fillna(0.0)
    res = backtest.run(prices, targets, free(), 1000.0)
    entry = prices.open["AAA"].iloc[11]
    expected = 1000.0 * prices.close["AAA"].iloc[11:] / entry
    np.testing.assert_allclose(res.equity.iloc[11:], expected, rtol=1e-12)


def test_books_balance_and_cash_never_negative(prices):
    cfg = Config(universe=TICKERS, benchmark="AAA")
    res = research.run_strategy(prices, cfg)
    marks = prices.close.ffill().fillna(0.0)
    value = res.cash + (res.holdings * marks).sum(axis=1)
    np.testing.assert_allclose(res.equity, value, rtol=1e-10)
    assert (res.cash >= -1e-9).all()
    assert (res.holdings.to_numpy() >= 0).all(), "long-only book went short"
    assert np.allclose(res.holdings.to_numpy(), np.round(res.holdings.to_numpy())), "fractional shares"


def test_costs_are_charged_and_accounted(prices):
    cfg = Config(universe=TICKERS, benchmark="AAA")
    cheap = research.run_strategy(prices, cfg)
    cfg.execution.slippage_bps = 50
    cfg.execution.commission_per_order = 5
    dear = research.run_strategy(prices, cfg)
    assert dear.equity.iloc[-1] < cheap.equity.iloc[-1]
    assert dear.trades["fee"].sum() == pytest.approx(5 * len(dear.trades))


def test_band_reduces_trading(prices):
    cfg = Config(universe=TICKERS, benchmark="AAA")
    cfg.execution.band = 0.0
    busy = research.run_strategy(prices, cfg)
    cfg.execution.band = 0.10
    calm = research.run_strategy(prices, cfg)
    assert len(calm.trades) < len(busy.trades)


def test_buys_are_scaled_when_cash_is_short():
    idx = pd.bdate_range("2020-01-01", periods=4)
    close = pd.DataFrame({"A": [10.0, 10, 10, 10]}, idx)
    open_ = pd.DataFrame({"A": [10.0, 20, 20, 20]}, idx)     # gap up overnight
    targets = pd.DataFrame({"A": [1.0]}, index=[idx[0]])
    exe = free()
    res = backtest.run(Prices(open_, close), targets, exe, 1000.0)
    assert res.cash.min() >= -1e-9
    assert res.holdings["A"].iloc[1] == pytest.approx(50.0)  # 1000 / 20, not 1000 / 10


def test_clean_does_not_invent_tradable_opens():
    idx = pd.bdate_range("2020-01-01", periods=3)
    close = pd.DataFrame({"A": [10.0, np.nan, 11.0], "B": [5.0, 5.1, 5.2]}, idx)
    open_ = pd.DataFrame({"A": [10.0, np.nan, 11.0], "B": [5.0, 5.1, 5.2]}, idx)
    p = clean(open_, close)
    assert np.isnan(p.open.loc[idx[1], "A"])        # no bar: cannot trade
    assert p.close.loc[idx[1], "A"] == 10.0         # but can be valued
