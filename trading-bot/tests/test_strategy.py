import numpy as np
import pandas as pd
import pytest

from trendbot import strategy
from trendbot.config import StrategyConfig
from trendbot.data import Prices, synthetic

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]


@pytest.fixture(scope="module")
def prices():
    return synthetic(TICKERS, days=1200, seed=11)


def test_caps_hold_every_day(prices):
    cfg = StrategyConfig(max_weight=0.2, max_gross=0.9, target_vol=0.5)
    w = strategy.target_weights(prices, cfg)
    assert (w.abs() <= 0.2 + 1e-12).all().all()
    assert (w.abs().sum(axis=1) <= 0.9 + 1e-12).all()
    assert (w >= 0).all().all()


def test_short_allowed_only_when_configured(prices):
    w = strategy.target_weights(prices, StrategyConfig(long_only=False))
    assert (w < 0).any().any()


def test_no_position_before_a_year_of_history(prices):
    w = strategy.target_weights(prices, StrategyConfig())
    assert (w.iloc[:252] == 0).all().all()


def test_uptrend_is_held_and_downtrend_is_not():
    idx = pd.bdate_range("2015-01-01", periods=600)
    rng = np.random.default_rng(0)
    up = 100 * np.exp(np.cumsum(0.001 + 0.01 * rng.standard_normal(600)))
    down = 100 * np.exp(np.cumsum(-0.001 + 0.01 * rng.standard_normal(600)))
    close = pd.DataFrame({"UP": up, "DOWN": down}, idx)
    w = strategy.target_weights(Prices(close.copy(), close), StrategyConfig()).iloc[-1]
    assert w["UP"] > 0
    assert w["DOWN"] == 0


def test_volatility_targeting_scales_down_risk():
    """Doubling an asset's volatility should roughly halve its weight."""
    idx = pd.bdate_range("2015-01-01", periods=600)
    rng = np.random.default_rng(1)
    shocks = rng.standard_normal(600)
    calm = 100 * np.exp(np.cumsum(0.0008 + 0.005 * shocks))
    wild = 100 * np.exp(np.cumsum(0.0016 + 0.010 * shocks))   # same t-stats, twice the vol
    cfg = StrategyConfig(max_weight=1.0, target_vol=0.02)
    w_calm = strategy.target_weights(Prices(*(pd.DataFrame({"X": calm}, idx),) * 2), cfg).iloc[-1, 0]
    w_wild = strategy.target_weights(Prices(*(pd.DataFrame({"X": wild}, idx),) * 2), cfg).iloc[-1, 0]
    assert w_wild == pytest.approx(w_calm / 2, rel=0.05)


def test_weekly_rebalance_dates_are_last_day_of_week():
    idx = pd.bdate_range("2024-01-01", "2024-01-31")
    d = strategy.rebalance_dates(idx, "weekly")
    assert all(x.dayofweek == 4 or x == idx[-1] for x in d)
    assert len(strategy.rebalance_dates(idx, "monthly")) == 1
