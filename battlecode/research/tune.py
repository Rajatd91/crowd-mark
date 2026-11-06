"""Parameter search and ablation, with an in-sample/out-of-sample discipline.

Each variant is the current bot with some PARAMS overridden. It is written to
bots/<name>/ and backtested against a fixed baseline. Selection uses the
training maps only, and the chosen variant is then confirmed on the held-out
test maps, so we do not over-fit to maps the tournament will never use.

    python research/tune.py --baseline baseline --maps train_quick \
        --variant flee_off flee_enabled=False --variant ratio_low engage_ratio=0.6
"""
import argparse
import ast
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import arena  # noqa: E402
import stats  # noqa: E402
from maps import split  # noqa: E402

SOURCE = os.path.join(WS, "bots", "velvet")


def make_variant(name, overrides):
    """Copy the bot and rewrite params.py with the overrides applied."""
    target = os.path.join(WS, "bots", name)
    if os.path.exists(target):
        shutil.rmtree(target)
    shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns(".cambc", "__pycache__"))
    path = os.path.join(target, "src", "params.py")
    text = open(path).read()
    params = ast.literal_eval(text[text.index("{"):text.rindex("}") + 1])
    for key, value in overrides.items():
        if key not in params:
            raise KeyError(f"unknown parameter {key}")
        params[key] = value
    body = "PARAMS = {\n" + "".join(f"    {k!r}: {v!r},\n" for k, v in params.items()) + "}\n"
    open(path, "w").write(f'"""Variant {name}: {overrides}"""\n' + body)
    return target


def parse(pairs):
    out = {}
    for pair in pairs:
        key, raw = pair.split("=", 1)
        out[key] = ast.literal_eval(raw)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--maps", default="train")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--variant", nargs="+", action="append", required=True,
                    help="NAME key=value [key=value ...]")
    args = ap.parse_args()
    maps = split(args.maps)
    for spec in args.variant:
        name, overrides = spec[0], parse(spec[1:])
        make_variant(name, overrides)
        rows = arena.play(name, args.baseline, maps, args.jobs, f"tune_{name}_{args.maps}")
        out = os.path.join(HERE, "results", f"tune_{name}_vs_{args.baseline}_{args.maps}.csv")
        import csv
        with open(out, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=arena.FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"[{name}] {overrides}")
        print(stats.render(stats.summarise(out)), flush=True)


if __name__ == "__main__":
    main()
