import numpy as np
import pandas as pd
import pytest

from trendbot import metrics


def series(values):
    return pd.Series(values, index=pd.bdate_range("2010-01-01", periods=len(values)))


def test_max_drawdown():
    r = series([0.10, -0.50, 0.20])
    assert metrics.max_drawdown(r) == pytest.approx(-0.5)


def test_cagr_of_constant_growth():
    r = series([0.001] * 252)
    assert metrics.cagr(r) == pytest.approx(1.001 ** 252 - 1)


def test_sharpe_sign_and_scale():
    rng = np.random.default_rng(0)
    r = series(rng.normal(0.0005, 0.01, 5000))
    assert metrics.sharpe(r) == pytest.approx(0.0005 / 0.01 * np.sqrt(252), rel=0.25)


def test_psr_rises_with_evidence():
    rng = np.random.default_rng(1)
    short = series(rng.normal(0.0004, 0.01, 250))
    long = series(rng.normal(0.0004, 0.01, 5000))
    assert metrics.probabilistic_sharpe(long) > metrics.probabilistic_sharpe(short) - 0.2
    assert 0 <= metrics.probabilistic_sharpe(long) <= 1


def test_more_trials_raise_the_bar():
    assert metrics.expected_max_sharpe(100, 0.1) > metrics.expected_max_sharpe(10, 0.1) > 0
    rng = np.random.default_rng(2)
    r = series(rng.normal(0.0004, 0.01, 3000))
    assert metrics.deflated_sharpe(r, 100, 0.1) < metrics.deflated_sharpe(r, 2, 0.1)


def test_bootstrap_interval_contains_point_estimate():
    rng = np.random.default_rng(3)
    r = series(rng.normal(0.0004, 0.01, 2000))
    lo, hi = metrics.bootstrap_sharpe_ci(r, n=500)
    assert lo < metrics.sharpe(r) < hi
