"""Decision models used by the bot. Pure arithmetic: no engine calls, so every
function here is unit-tested offline (research/tests/test_models.py).

Contents
--------
- Camp table and Smith's-rule damage model (scheduling).
- Banking threshold: an inventory-under-risk (EOQ-style) closed form.
- Bayesian death-hazard estimate (Gamma-Poisson conjugate update).
- Lanchester square-law team-fight strength.
- Exact duel win probability with an unknown enemy cooldown.

Python bots run on a fuel budget, so everything here is closed form or a
small exact enumeration. The Monte Carlo work that justifies these formulas
lives in research/ and runs offline.
"""
import math

# Handbook camp table (finals patch): health, strength, attack range.
CAMP_STATS = {
    "wolf": (1350, 20, 3), "elk": (2400, 60, 4), "golem": (5000, 120, 4),
    "monolith": (20000, 200, 5), "gem_cluster": (120, 0, 0), "gold_cluster": (120, 0, 0),
}
ABILITY_COOLDOWN = 8


# --------------------------------------------------------------------------
# Scheduling: which monster first, and how much damage the group deals.
# --------------------------------------------------------------------------
def smith_order(monsters):
    """Order (strength, health) monsters by Smith's rule: strength/health, descending.

    Each monster hits every round until it dies, so the damage taken is
    sum(strength_i * finish_time_i). An adjacent-swap argument shows this
    weighted completion time is minimised by descending strength/health.
    """
    return sorted(monsters, key=lambda m: -m[0] / max(m[1], 1e-9))


def soak(monsters, team_dps, health_scale=1.0):
    """Total damage a group deals while a team with `team_dps` kills it in Smith order."""
    if team_dps <= 0:
        return math.inf
    clock = total = 0.0
    for strength, health in smith_order(monsters):
        clock += health * health_scale / team_dps
        total += strength * clock
    return total


# --------------------------------------------------------------------------
# Banking: carry gems until the threshold, then tribute.
# --------------------------------------------------------------------------
def bank_threshold(rate, hazard, trip):
    """Gems to carry before banking, maximising banked gems per round.

    Model: gems arrive at `rate` per round while farming. While carrying,
    death (hazard per round) loses the bag. A bank trip costs `trip` rounds.
    Banking every G gems gives a cycle of G/rate + trip rounds and an
    expected loss of hazard * G^2 / (2 rate), to first order. The banked rate
    f(G) = (G - aG^2) / (G/rate + trip), with a = hazard / (2 rate). Setting
    f'(G) = 0 gives a quadratic with positive root

        G* = rate * (sqrt(a^2 T^2 + a T / rate) - a T) / a.

    As hazard -> 0 the optimum grows without bound (never pay for a trip). As
    the trip gets cheaper, banking becomes frequent.
    """
    rate = max(rate, 1e-6)
    trip = max(trip, 0.0)
    if hazard <= 1e-9:
        return math.inf
    a = hazard / (2.0 * rate)
    root = math.sqrt(a * a * trip * trip + a * trip / rate)
    return rate * (root - a * trip) / a


def banked_rate(gems, rate, hazard, trip):
    """Objective that bank_threshold maximises; used in tests and research."""
    a = hazard / (2.0 * max(rate, 1e-6))
    return (gems - a * gems * gems) / (gems / max(rate, 1e-6) + trip)


class GammaRate:
    """Poisson event rate with a conjugate Gamma(alpha, beta) prior.

    Posterior mean = (alpha + events) / (beta + exposure). Used for this
    champion's death hazard, split by whether enemies are around.
    """

    def __init__(self, prior_rate, prior_strength):
        self.alpha = prior_rate * prior_strength
        self.beta = prior_strength

    def observe(self, events, exposure):
        self.alpha += events
        self.beta += exposure

    @property
    def mean(self):
        return self.alpha / self.beta


class Ewma:
    """Exponentially weighted moving average with a warm start."""

    def __init__(self, value, half_life):
        self.value = value
        self.weight = 1.0 - 0.5 ** (1.0 / max(half_life, 1e-6))

    def update(self, sample):
        self.value += self.weight * (sample - self.value)
        return self.value


# --------------------------------------------------------------------------
# Champion combat.
# --------------------------------------------------------------------------
def lanchester_power(units):
    """Square-law fighting strength of a side: (total damage rate) x (total health).

    Under Lanchester's square law with aimed fire, a side's strength is
    proportional to its firepower times its staying power. The ratio of the
    two sides' powers is the win condition.
    """
    return sum(u[0] for u in units) * sum(u[1] for u in units)


def fight_ratio(ours, theirs):
    """Our Lanchester power over theirs; > 1 means we are expected to win."""
    p_them = lanchester_power(theirs)
    if p_them <= 0:
        return math.inf
    return lanchester_power(ours) / p_them


def duel_win_probability(my_hp, my_dps, my_burst, en_hp, en_dps, en_burst, we_act_first=True):
    """P(we kill the enemy first), averaging over the enemy's unknown cooldown.

    Our ability state is known. The enemy's burst comes back after an unknown
    0..7 rounds, taken as uniform. For each case both kill times are exact,
    and ties go to whoever acts first. A 1v1 heuristic for when the
    Lanchester ratio is close.
    """
    my_dps = max(my_dps, 1e-6)
    en_dps = max(en_dps, 1e-6)
    our_time = kill_time(en_hp, my_dps, my_burst, burst_round=1)
    wins = 0
    for ready_in in range(ABILITY_COOLDOWN):
        their_time = kill_time(my_hp, en_dps, en_burst, burst_round=max(ready_in, 1))
        if our_time < their_time or (our_time == their_time and we_act_first):
            wins += 1
    return wins / ABILITY_COOLDOWN


def kill_time(health, dps, burst, burst_round=1):
    """Rounds to deal `health` damage at `dps` per round plus one `burst` landing at `burst_round`."""
    without = max(1, math.ceil(health / dps))
    if burst <= 0:
        return without
    with_burst = max(burst_round, math.ceil(max(0.0, health - burst) / dps), 1)
    return min(without, with_burst)


def target_value(gems_carried, health, my_dps, kill_gold=100, gem_weight=1.0, gold_weight=0.12):
    """Reward per round of focusing an enemy: what the kill pays, over time to kill."""
    reward = gem_weight * gems_carried + gold_weight * kill_gold
    return reward / max(health / max(my_dps, 1e-6), 1.0)
