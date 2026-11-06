"""Calibrate the banking model's priors from backtest data.

For every champion-game in the backtests, exposure is the rounds spent alive
(rounds played minus 60 per death) and events are its deaths. The pooled
Poisson rate is deaths / exposure, with an exact-ish 95% interval from the
Gamma posterior (normal approximation on the log rate). Gem income per
champion-round calibrates the income prior the same way.

    python research/calibrate.py velvet      # pools every game velvet played in replays/arena
"""
import glob
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
RESPAWN = 60


def games_for(bot):
    """(stats json, our team) for each finished game this bot played."""
    out = []
    for manifest in glob.glob(os.path.join(WS, "replays", "arena", "*", "manifest.txt")):
        for line in open(manifest):
            parts = line.split()
            a, b, stats_path = os.path.basename(parts[0]), os.path.basename(parts[1]), parts[5]
            if os.path.exists(stats_path) and bot in (a, b):
                out.append((stats_path, "teamA" if a == bot else "teamB"))
    return out


def main():
    bot = sys.argv[1] if len(sys.argv) > 1 else "velvet"
    deaths = exposure = gems = 0.0
    champion_games = 0
    for path, team in games_for(bot):
        stats = json.load(open(path))
        rounds = stats["match"]["roundsCompleted"]
        ids = {c["id"] for c in stats["roster"]["champions"] if c["team"] == team}
        for champion in stats["champions"]:
            if champion["id"] not in ids:
                continue
            d = int(champion["metrics"]["deaths"])
            deaths += d
            exposure += max(1, rounds - RESPAWN * d)
            gems += int(champion["metrics"]["collectedGems"])
            champion_games += 1
    if exposure == 0:
        print("no games found")
        return
    rate = deaths / exposure
    se = 1 / math.sqrt(max(deaths, 1))
    lo, hi = rate * math.exp(-1.96 * se), rate * math.exp(1.96 * se)
    print(f"{bot}: {champion_games} champion-games, {deaths:.0f} deaths over {exposure:.0f} alive rounds")
    print(f"  death hazard {rate:.5f}/round  [95% CI {lo:.5f}-{hi:.5f}]  -> mean life {1 / max(rate, 1e-9):.0f} rounds")
    print(f"  gem income   {gems / exposure:.3f} gems per alive champion-round")


if __name__ == "__main__":
    main()
