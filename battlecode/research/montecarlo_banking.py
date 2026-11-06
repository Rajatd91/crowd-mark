"""Monte Carlo check of the banking model.

The bot banks when its bag reaches G* = bank_threshold(rate, hazard, trip), a
closed form derived under first-order assumptions: smooth income and at most
one death per cycle. Real income is lumpy (captures land in chunks of 4-36
gems) and deaths are Poisson events. This script simulates the actual
process across bag thresholds and checks that the closed form lands near
the simulated optimum.

    python research/montecarlo_banking.py   # writes results/banking_mc.csv and charts/banking_mc.png
"""
import csv
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bots", "velvet", "src"))
from models import bank_threshold  # noqa: E402

# Capture sizes seen on the map pool (gem clusters 7, wolves 4, elk groups 15+).
CAPTURES = [7, 7, 7, 14, 4, 11, 15, 21, 28, 36]
RESPAWN = 60


def simulate(threshold, rate, hazard, trip, rounds=400_000, seed=1):
    """Banked gems per round for a champion that banks whenever its bag reaches `threshold`."""
    rng = random.Random(seed)
    mean_capture = sum(CAPTURES) / len(CAPTURES)
    p_capture = rate / mean_capture          # captures per round giving the target income rate
    bag = banked = 0
    t = 0
    while t < rounds:
        if rng.random() < hazard:           # death: lose the bag, sit out the respawn
            bag = 0
            t += RESPAWN
            continue
        if rng.random() < p_capture:
            bag += rng.choice(CAPTURES)
        t += 1
        if bag >= threshold:
            t += trip                       # the bank trip; risk during the trip is folded into hazard
            banked += bag
            bag = 0
    return banked / rounds


def main():
    cases = [(0.35, 0.0012, 30, "calm, altar 15 tiles away"), (0.35, 0.012, 30, "enemies around"),
             (0.6, 0.003, 12, "rich map, altar close")]
    rows = []
    for rate, hazard, trip, label in cases:
        g_star = bank_threshold(rate, hazard, trip)
        grid = list(range(4, 121, 4))
        sims = [(g, simulate(g, rate, hazard, trip)) for g in grid]
        g_best, v_best = max(sims, key=lambda x: x[1])
        v_star = simulate(round(g_star), rate, hazard, trip)
        print(f"{label:28s} closed-form G*={g_star:5.1f} (sim {v_star:.4f}/round)   "
              f"simulated best G={g_best} ({v_best:.4f}/round)   loss {(1 - v_star / v_best):.1%}")
        for g, v in sims:
            rows.append({"case": label, "rate": rate, "hazard": hazard, "trip": trip, "threshold": g,
                         "banked_per_round": round(v, 5), "closed_form": round(g_star, 2)})
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "banking_mc.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 4.5))
        for label in dict.fromkeys(r["case"] for r in rows):
            pts = [r for r in rows if r["case"] == label]
            line, = ax.plot([r["threshold"] for r in pts], [r["banked_per_round"] for r in pts], label=label)
            ax.axvline(pts[0]["closed_form"], color=line.get_color(), linestyle="--", linewidth=1)
        ax.set_xlabel("bag size at which the champion banks (gems)")
        ax.set_ylabel("banked gems per round (simulated)")
        ax.set_title("Monte Carlo banking curves; dashed = closed-form threshold G*")
        ax.legend()
        os.makedirs(os.path.join(HERE, "charts"), exist_ok=True)
        fig.tight_layout()
        fig.savefig(os.path.join(HERE, "charts", "banking_mc.png"), dpi=130)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
