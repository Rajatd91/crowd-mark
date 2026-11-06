"""Chart every backtest result: win rate with Wilson 95% intervals.

    python research/report.py results/*.csv     # writes charts/backtests.png and prints a table
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stats  # noqa: E402


def main(paths):
    rows = [s for s in (stats.summarise(p) for p in paths) if s]
    for s in rows:
        print(stats.render(s))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    labels = [f"{s['a']} vs {s['b']}" for s in rows]
    rates = [s["win_rate"] for s in rows]
    lo = [s["win_rate"] - s["ci"][0] for s in rows]
    hi = [s["ci"][1] - s["win_rate"] for s in rows]
    fig, ax = plt.subplots(figsize=(8, 0.6 * len(rows) + 1.5))
    ax.barh(labels, rates, xerr=[lo, hi], color="#3b6ea5", capsize=4)
    ax.axvline(0.5, color="grey", linestyle="--", linewidth=1)
    ax.set_xlim(0, 1)
    ax.set_xlabel("win rate (both sides of every map), 95% Wilson interval")
    ax.invert_yaxis()
    fig.tight_layout()
    os.makedirs(os.path.join(HERE, "charts"), exist_ok=True)
    fig.savefig(os.path.join(HERE, "charts", "backtests.png"), dpi=130)


if __name__ == "__main__":
    main(sys.argv[1:])
