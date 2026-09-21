"""Tests for the maths behind every number on the page.

Fixtures are shortened copies of real responses read on 20 Sep 2026, so a
provider changing its wording breaks a test here rather than the page.
"""
import json
import unittest

import model as M
import sources as S


def mkt(title, yes):
    return {"groupItemTitle": title, "outcomePrices": json.dumps([str(yes), str(round(1 - yes, 4))])}


ANTHROPIC_CAP = {"markets": [
    mkt("<$1.25T", 0.006), mkt("$1.25–$1.5T", 0.039), mkt("$1.5–$1.75T", 0.0615),
    mkt("$1.75–$2.0T", 0.155), mkt("$2.0–$2.25T", 0.241), mkt("$2.25–$2.5T", 0.185),
    mkt("$2.5–$2.75T", 0.1385), mkt("$2.75–$3.0T", 0.0325), mkt("$3.0T+", 0.037),
    mkt("No IPO by December 31, 2027", 0.0445)]}

NEURALINK_LADDER = {"markets": [
    mkt("↑$100B", 0.035), mkt("↑$75B", 0.375), mkt("↑$60B", 0.53),
    mkt("↑$50B", 0.89), mkt("↑$45B", 1.0), mkt("↓$35B", 0.125)]}

ROW = {"symbol": "ANTHROPIC", "tokenPrice": 988.91, "markPrice": 1026.71,
       "markValuation": 1.6818e12, "impliedValuation": 1.62e12}


class TestShares(unittest.TestCase):
    def test_implied_shares_is_the_issuers_own_ratio(self):
        self.assertAlmostEqual(M.implied_shares(ROW), 1.6818e12 / 1026.71, places=0)

    def test_token_implied_value_uses_token_price(self):
        self.assertAlmostEqual(M.token_implied_value(ROW),
                               988.91 * (1.6818e12 / 1026.71), places=0)

    def test_premium_is_signed(self):
        self.assertLess(M.premium_to_mark(ROW), 0)          # token below the mark today


class TestBrackets(unittest.TestCase):
    def setUp(self):
        self.brackets, self.p_no, self.notes = M.cap_brackets(ANTHROPIC_CAP)

    def test_every_bracket_is_read(self):
        self.assertEqual(len(self.brackets), 9)

    def test_no_ipo_leg_is_separated_not_counted(self):
        self.assertAlmostEqual(self.p_no, 0.0445)
        self.assertTrue(all(hi > 0 for _, hi, _ in self.brackets))

    def test_open_ended_bracket_is_reported_as_an_assumption(self):
        self.assertTrue(any("open-ended" in n for n in self.notes))

    def test_lowest_bracket_starts_at_zero(self):
        self.assertEqual(self.brackets[0][0], 0.0)

    def test_expected_cap_sits_inside_the_dense_brackets(self):
        cap, mass = M.expected_cap(self.brackets)
        self.assertTrue(2.0e12 < cap < 2.4e12, cap)          # densest mass is 2.0 to 2.5T
        self.assertAlmostEqual(mass, 0.8955, places=3)

    def test_expected_cap_is_conditional_so_probabilities_renormalise(self):
        half = [(lo, hi, p / 2) for lo, hi, p in self.brackets]
        self.assertAlmostEqual(M.expected_cap(self.brackets)[0], M.expected_cap(half)[0], places=0)

    def test_empty_distribution_returns_none(self):
        self.assertEqual(M.expected_cap([])[0], None)


class TestLadder(unittest.TestCase):
    def setUp(self):
        self.rungs = M.valuation_ladder(NEURALINK_LADDER)

    def test_only_upward_rungs_are_used(self):
        self.assertEqual([v for v, _ in self.rungs],
                         [45e9, 50e9, 60e9, 75e9, 100e9])

    def test_odds_interpolate_between_rungs(self):
        p = M.crowd_odds_at(self.rungs, 67.5e9)              # midway 60 to 75
        self.assertAlmostEqual(p, (0.53 + 0.375) / 2, places=3)

    def test_outside_the_ladder_returns_none_rather_than_a_guess(self):
        self.assertIsNone(M.crowd_odds_at(self.rungs, 10e9))
        self.assertIsNone(M.crowd_odds_at(self.rungs, 500e9))


class TestSpaceX(unittest.TestCase):
    def test_gap_measures_the_listed_token(self):
        snap = {"jupiter_price": {S.SPACEX["mint"]: {"usdPrice": 118.0},
                                  S.SPACEX["listed_token"]: {"usdPrice": 150.0}}}
        gap = M.spacex_conversion_gap(snap, S)
        self.assertAlmostEqual(gap["discount"], 1 - 118.0 / 150.0, places=6)

    def test_missing_price_returns_none_not_zero(self):
        self.assertIsNone(M.spacex_conversion_gap({"jupiter_price": {}}, S))


class TestCard(unittest.TestCase):
    def test_card_carries_its_assumptions(self):
        snap = {"prestocks": [ROW], "polymarket": {"cap": ANTHROPIC_CAP, "timing": {"markets": []}}}
        cfg = {"company": "Anthropic", "kind": "ipo",
               "polymarket": {"cap": "cap", "timing": "timing"}}
        card = M.build_card(snap, "ANTHROPIC", cfg)
        self.assertGreater(card.crowd_per_token, 0)
        self.assertTrue(card.assumptions)
        self.assertAlmostEqual(card.crowd_per_token, card.crowd_value / card.shares, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)


FINE_CAP = {"markets": [
    mkt("<$1.25T", 0.0115), mkt("$1.25–$1.50T", 0.0295), mkt("$1.50–$1.75T", 0.037),
    mkt("$1.75–$2.00T", 0.465), mkt("$2.00–$2.25T", 0.2085), mkt("$2.25–$2.50T", 0.0815),
    mkt("$2.50T+", 0.1445), mkt("No IPO by December 31, 2027", 0.046)]}

COARSE_CAP = {"markets": [
    mkt("<$1.5T", 0.05), mkt("$1.5T+", 0.80), mkt("No IPO by December 31, 2027", 0.15)]}


class TestChoosingTheMarket(unittest.TestCase):
    def test_open_top_mass_is_a_share_of_the_live_brackets(self):
        self.assertAlmostEqual(M.open_top_mass(COARSE_CAP), 0.80 / 0.85, places=3)

    def test_the_market_leaving_least_to_assumption_wins(self):
        cfg = {"polymarket": {"cap_a": "fine", "cap_b": "coarse", "timing": "t"}}
        slug, _, _, _, mass = M.choose_cap_event({"fine": FINE_CAP, "coarse": COARSE_CAP}, cfg)
        self.assertEqual(slug, "fine")
        self.assertLess(mass, 0.2)

    def test_a_missing_market_is_skipped_not_fatal(self):
        cfg = {"polymarket": {"cap_a": "absent", "cap_b": "fine"}}
        slug, *_ = M.choose_cap_event({"fine": FINE_CAP}, cfg)
        self.assertEqual(slug, "fine")

    def test_a_market_too_coarse_to_price_is_refused(self):
        # Two brackets, most of the mass open-ended, means any answer would be
        # mostly our assumption. Saying nothing is the honest outcome.
        cfg = {"polymarket": {"cap_a": "coarse"}}
        self.assertIsNone(M.choose_cap_event({"coarse": COARSE_CAP}, cfg))

    def test_rescaling_the_open_top_moves_the_answer_the_right_way(self):
        brackets, _, _ = M.cap_brackets(FINE_CAP)
        low = M.expected_cap(M.rescale_open_top(brackets, 1.10))[0]
        high = M.expected_cap(M.rescale_open_top(brackets, 1.50))[0]
        self.assertLess(low, high)
        self.assertLess(high - low, 0.4e12)      # the assumption must not dominate
