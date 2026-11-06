"""Backtest engine: play bot A against bot B across a map set, both sides, and record every game.

Each map is played twice with sides swapped. That cancels the first-mover
and spawn asymmetries the same way a paired experiment cancels block effects.
Results go to a CSV, one row per game, for research/stats.py.

    python research/arena.py velvet v4 --maps test --jobs 3 --out results/velvet_vs_v4.csv
"""
import argparse
import csv
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from maps import split  # noqa: E402

RUNS = os.path.join(WS, "replays", "arena")
FIELDS = ["map", "side", "bot_a", "bot_b", "gems_a", "gems_b", "winner", "rounds",
          "kills_a", "kills_b", "deaths_a", "deaths_b", "gold_a", "gold_b"]


def team_metrics(stats, team):
    kills = deaths = gold = 0
    ids = {c["id"] for c in stats["roster"]["champions"] if c["team"] == team}
    for champion in stats["champions"]:
        if champion["id"] in ids:
            m = champion["metrics"]
            kills += int(m["kills"])
            deaths += int(m["deaths"])
            gold += int(m["earnedGold"])
    return kills, deaths, gold


def play(bot_a, bot_b, maps, jobs, tag):
    run = os.path.join(RUNS, tag)
    os.makedirs(run, exist_ok=True)
    rows, manifest = [], os.path.join(run, "manifest.txt")
    with open(manifest, "w") as fh:
        for i, name in enumerate(maps):
            for side, (x, y) in enumerate(((bot_a, bot_b), (bot_b, bot_a))):
                key = f"{i:03d}_{side}"
                for ext in (".repl26a", ".json"):
                    path = os.path.join(run, key + ext)
                    if os.path.exists(path):
                        os.remove(path)
                fh.write(f"{WS}/bots/{x} {WS}/bots/{y} {WS}/maps/{name} {run}/{key}.repl26a "
                         f"--statistics {run}/{key}.json\n")
                rows.append((key, name, side, x, y))
    subprocess.run(["cambc", "run-batch", manifest, "--jobs", str(jobs), "--json", "--timeout", "900",
                    "--release", "--log-limit", "0"], cwd=WS, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = []
    for key, name, side, x, y in rows:
        path = os.path.join(run, key + ".json")
        if not os.path.exists(path):
            continue
        stats = json.load(open(path))
        gems = {t["team"]: int(t["submittedGems"]) for t in stats["teams"]}
        ka, da, ga = team_metrics(stats, "teamA")
        kb, db, gb = team_metrics(stats, "teamB")
        winner = x if stats["match"]["outcome"] == "teamA" else y
        # Store from bot_a's point of view regardless of side.
        flip = side == 1
        out.append({
            "map": name.replace(".map26a", ""), "side": "B" if flip else "A",
            "bot_a": bot_a, "bot_b": bot_b,
            "gems_a": gems.get("teamB" if flip else "teamA", 0), "gems_b": gems.get("teamA" if flip else "teamB", 0),
            "winner": winner, "rounds": stats["match"]["roundsCompleted"],
            "kills_a": kb if flip else ka, "kills_b": ka if flip else kb,
            "deaths_a": db if flip else da, "deaths_b": da if flip else db,
            "gold_a": gb if flip else ga, "gold_b": ga if flip else gb,
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bot_a")
    ap.add_argument("bot_b")
    ap.add_argument("--maps", default="test", help="train | test | all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    maps = split(args.maps)
    if args.limit:
        maps = maps[:args.limit]
    rows = play(args.bot_a, args.bot_b, maps, args.jobs, f"{args.bot_a}_vs_{args.bot_b}_{args.maps}")
    out = os.path.join(HERE, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    wins = sum(r["winner"] == args.bot_a for r in rows)
    print(f"{args.bot_a} vs {args.bot_b}: {wins}/{len(rows)} wins -> {out}")


if __name__ == "__main__":
    main()
