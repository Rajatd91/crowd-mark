from datetime import datetime, timezone

import pandas as pd
import pytest

from trendbot import live
from trendbot.broker import PaperBroker
from trendbot.config import Config
from trendbot.data import synthetic

TICKERS = ["AAA", "BBB", "CCC", "DDD"]


@pytest.fixture
def setup(tmp_path):
    cfg = Config(universe=TICKERS, benchmark="AAA")
    cfg.broker.state_dir = str(tmp_path)
    cfg.execution.rebalance = "daily"
    prices = synthetic(TICKERS, days=700, seed=5)
    today = prices.close.index[-1] + pd.offsets.BDay(1)
    broker = PaperBroker(tmp_path, 10_000.0, cfg.execution.commission_per_order)
    return cfg, prices, today, broker


def test_dry_run_sends_nothing(setup):
    cfg, prices, today, broker = setup
    rec = live.rebalance(cfg, prices, broker, execute=False, today=today, require_open=False)
    assert not rec["executed"]
    assert broker.positions() == {}


def test_execute_reaches_target_and_is_idempotent(setup):
    cfg, prices, today, broker = setup
    rec = live.rebalance(cfg, prices, broker, execute=True, today=today, require_open=False)
    assert rec["executed"] and not rec["blocked"]
    held = broker.positions()
    assert held == {o["symbol"]: o["qty"] for o in rec["orders"] if o["qty"] > 0}
    again = live.rebalance(cfg, prices, broker, execute=True, today=today,
                           require_open=False, force=True)
    assert again["orders"] == []


def test_kill_switch_blocks(setup, tmp_path):
    cfg, prices, today, broker = setup
    (tmp_path / cfg.risk.kill_switch_file).write_text("x")
    rec = live.rebalance(cfg, prices, broker, execute=True, today=today, require_open=False)
    assert rec["blocked"] and not rec["executed"]
    assert broker.positions() == {}


def test_stale_data_blocks(setup):
    cfg, prices, today, broker = setup
    rec = live.rebalance(cfg, prices, broker, execute=True,
                         today=today + pd.Timedelta(days=30), require_open=False)
    assert any("old" in b for b in rec["blocked"])


def test_oversized_order_blocks(setup):
    cfg, prices, today, broker = setup
    cfg.risk.max_order_fraction = 0.01
    rec = live.rebalance(cfg, prices, broker, execute=True, today=today, require_open=False)
    assert any("more than" in b for b in rec["blocked"])


def test_daily_loss_blocks(setup):
    cfg, prices, today, broker = setup
    broker.state["last_equity"] = 20_000.0          # pretend yesterday was much better
    rec = live.rebalance(cfg, prices, broker, execute=True, today=today, require_open=False)
    assert any("equity down" in b for b in rec["blocked"])


def test_weekly_schedule(tmp_path):
    friday = pd.Timestamp("2024-03-08")
    due, _ = live.schedule_due(friday, pd.Timestamp("2024-03-11"), "weekly", tmp_path)
    assert due
    not_yet, _ = live.schedule_due(pd.Timestamp("2024-03-06"), pd.Timestamp("2024-03-07"), "weekly", tmp_path)
    assert not not_yet


def test_unfinished_bar_is_dropped():
    prices = synthetic(TICKERS, days=50, seed=1, start="2024-01-01")
    last = prices.close.index[-1]
    during = datetime(last.year, last.month, last.day, 15, 0, tzinfo=timezone.utc)   # 10-11am New York
    after = datetime(last.year, last.month, last.day, 23, 0, tzinfo=timezone.utc)
    assert live.completed_bars(prices, during).close.index[-1] < last
    assert live.completed_bars(prices, after).close.index[-1] == last


def test_plan_sells_before_buys(setup):
    cfg, prices, today, broker = setup
    target = pd.Series({"AAA": 0.0, "BBB": 0.25})
    plan, _ = live.plan_orders(target, {"AAA": 10}, 10_000.0, prices.close.iloc[-1], cfg)
    assert plan[0].qty < 0 and plan[-1].qty > 0
