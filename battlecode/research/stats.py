"""Statistics for backtests: is version A really better than version B?

- Win rate with a Wilson score interval, which behaves well near 0 and 1.
- Paired bootstrap of the per-map gem margin: both sides of a map form one
  pair, so map difficulty cancels.
- Exact two-sided sign test on per-map results.
- Bradley-Terry / Elo-scale rating difference implied by the win rate.

    python research/stats.py results/velvet_vs_v4.csv
"""
import csv
import math
import random
import sys
from collections import defaultdict


def wilson(wins, n, z=1.96):
    if n == 0:
        return (0.0, 0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def sign_test(plus, minus):
    """Two-sided exact binomial test of plus vs minus (ties dropped)."""
    n = plus + minus
    if n == 0:
        return 1.0
    k = max(plus, minus)
    tail = sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def bootstrap_mean(values, reps=5000, seed=7):
    rng = random.Random(seed)
    n = len(values)
    if n == 0:
        return (0.0, 0.0, 0.0)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(reps))
    return sum(values) / n, means[int(0.025 * reps)], means[int(0.975 * reps)]


def elo_gap(p):
    p = min(max(p, 1e-3), 1 - 1e-3)
    return 400 * math.log10(p / (1 - p))


def summarise(path):
    rows = list(csv.DictReader(open(path)))
    if not rows:
        return None
    a, b = rows[0]["bot_a"], rows[0]["bot_b"]
    wins = sum(r["winner"] == a for r in rows)
    p, lo, hi = wilson(wins, len(rows))
    per_map = defaultdict(list)
    for r in rows:
        per_map[r["map"]].append(int(r["gems_a"]) - int(r["gems_b"]))
    margins = [sum(v) / len(v) for v in per_map.values()]
    mean, mlo, mhi = bootstrap_mean(margins)
    plus = sum(m > 0 for m in margins)
    minus = sum(m < 0 for m in margins)
    return {
        "a": a, "b": b, "games": len(rows), "wins": wins, "win_rate": p, "ci": (lo, hi),
        "margin": mean, "margin_ci": (mlo, mhi), "maps": len(margins),
        "sign_p": sign_test(plus, minus), "elo": elo_gap(p),
        "rounds": sum(int(r["rounds"]) for r in rows) / len(rows),
        "kd_a": sum(int(r["kills_a"]) for r in rows) / max(1, sum(int(r["deaths_a"]) for r in rows)),
    }


def render(s):
    return (f"{s['a']} vs {s['b']}: {s['wins']}/{s['games']} wins = {s['win_rate']:.1%} "
            f"[95% CI {s['ci'][0]:.1%}-{s['ci'][1]:.1%}], Elo gap {s['elo']:+.0f}\n"
            f"  per-map gem margin {s['margin']:+.0f} [95% bootstrap CI {s['margin_ci'][0]:+.0f} "
            f"to {s['margin_ci'][1]:+.0f}] over {s['maps']} maps; sign test p = {s['sign_p']:.2g}; "
            f"K/D {s['kd_a']:.2f}; mean rounds {s['rounds']:.0f}")


if __name__ == "__main__":
    for path in sys.argv[1:]:
        s = summarise(path)
        if s:
            print(render(s))
