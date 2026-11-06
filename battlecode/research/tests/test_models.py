"""Unit tests for the bot's decision models (pure arithmetic, no engine needed).

    python -m pytest research/tests -q
"""
import itertools
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bots", "velvet", "src"))
from models import (GammaRate, Ewma, bank_threshold, banked_rate, duel_win_probability,  # noqa: E402
                    fight_ratio, kill_time, smith_order, soak)


def brute_force_soak(monsters, dps):
    """Minimum damage over every kill order: the ground truth for Smith's rule."""
    best = math.inf
    for order in itertools.permutations(monsters):
        clock = total = 0.0
        for strength, health in order:
            clock += health / dps
            total += strength * clock
        best = min(best, total)
    return best


def test_smith_rule_is_optimal_against_every_permutation():
    groups = [
        [(60, 2400), (20, 1350), (0, 120)],
        [(120, 5000), (60, 2400), (60, 2400), (20, 1350)],
        [(200, 20000), (20, 1350), (0, 120), (0, 120)],
        [(20, 1350), (20, 1350), (60, 2400), (120, 5000), (0, 120)],
    ]
    for monsters in groups:
        assert math.isclose(soak(monsters, 150.0), brute_force_soak(monsters, 150.0), rel_tol=1e-9)


def test_smith_order_puts_harmless_clusters_last():
    order = smith_order([(0, 120), (60, 2400), (20, 1350)])
    assert order[-1] == (0, 120)


def test_bank_threshold_is_the_argmax_of_the_banked_rate():
    for rate, hazard, trip in [(0.35, 0.0012, 30), (0.5, 0.01, 12), (0.2, 0.003, 60), (1.0, 0.02, 8)]:
        g_star = bank_threshold(rate, hazard, trip)
        grid = [g / 10 for g in range(1, 3000)]
        best = max(grid, key=lambda g: banked_rate(g, rate, hazard, trip))
        assert abs(best - g_star) < 0.2, (rate, hazard, trip, best, g_star)


def test_bank_threshold_comparative_statics():
    base = bank_threshold(0.4, 0.002, 30)
    assert bank_threshold(0.4, 0.01, 30) < base          # more danger: bank sooner
    assert bank_threshold(0.4, 0.002, 60) > base         # dearer trips: bank later
    assert math.isinf(bank_threshold(0.4, 0.0, 30))      # no danger: never pay for a trip


def test_gamma_posterior_mean_moves_with_evidence():
    rate = GammaRate(prior_rate=0.002, prior_strength=500)
    assert math.isclose(rate.mean, 0.002)
    rate.observe(events=5, exposure=500)                 # five deaths in 500 rounds
    assert math.isclose(rate.mean, (1 + 5) / 1000)


def test_ewma_converges():
    avg = Ewma(0.0, half_life=10)
    for _ in range(200):
        avg.update(1.0)
    assert abs(avg.value - 1.0) < 1e-6


def test_lanchester_square_law():
    # Two identical units beat one: the power ratio is 2^2 = 4.
    assert math.isclose(fight_ratio([(50, 900), (50, 900)], [(50, 900)]), 4.0)


def test_kill_time_with_and_without_burst():
    assert kill_time(900, 100, 0) == 9
    assert kill_time(900, 100, 300) == 6
    assert kill_time(900, 100, 300, burst_round=8) == 8


def test_duel_probability_bounds_and_monotonicity():
    strong = duel_win_probability(1200, 80, 200, 600, 40, 100)
    weak = duel_win_probability(500, 40, 0, 1200, 80, 200)
    assert 0.0 <= weak <= strong <= 1.0
    assert strong == 1.0 and weak == 0.0
