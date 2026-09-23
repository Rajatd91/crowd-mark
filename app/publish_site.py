"""Copy the terminal into docs, which is what GitHub Pages serves.

Only the files the page actually loads are copied, and each one has to exist,
so a renamed module cannot reach the site as a missing script. The conformance
tests run first: if the two copies of the model disagree, or a view throws, or
a mark on chain no longer verifies from the page, nothing is copied.

Usage:
    python3 publish_site.py            # test, then copy
    python3 publish_site.py --no-test  # copy only
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
DOCS = os.path.join(HERE, "..", "docs")

# Everything index.html loads, directly or through an import.
FILES = [
    "index.html", "terminal.css",
    # The terminal and the modules it loads, some of them only on demand.
    "terminal.js", "poly.js", "news.js", "chain.js",
    "commit.js", "model.js", "live.js", "publish.js",
    # What it ships with, so the first screen is never empty.
    "desk.json", "onchain.json", "liquidity.json", "news.json",
]

TESTS = [
    ("the two models agree", ["node", "conformance_model.mjs"]),
    ("every screen renders", ["node", "conformance_terminal.mjs"]),
    ("the chain verifies from the page", ["node", "conformance_chain.mjs"]),
]


def expected_json():
    """The Python model's own output, for the cross-language comparison."""
    out = subprocess.run([sys.executable, "-c", EXPECT], cwd=HERE,
                         capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(f"could not run the Python model\n{out.stderr}")
    path = os.path.join(HERE, "site", ".expected.json")
    with open(path, "w") as f:
        f.write(out.stdout)
    return path


EXPECT = """
import json
import model as M, sources as S
snap = json.load(open('data/latest.json'))
out = {"tokens": {}, "config": {}}
for sym, cfg in S.TOKENS.items():
    c = M.build_card(snap, sym, cfg)
    e = {k: getattr(c, k) for k in
         ("token_price","mark_price","premium_to_mark","shares","token_implied_value",
          "crowd_value","crowd_per_token","p_listing","open_top_mass","cap_source",
          "crowd_odds_at_token_price","timing","ladder")}
    e["crowd_low"], e["crowd_high"] = (c.crowd_value_range or (None, None))
    e["brackets"] = []
    if c.cap_source:
        ev = snap["polymarket"][c.cap_source]
        ev = ev[0] if isinstance(ev, list) else ev
        raw, _, _ = M.cap_brackets(ev)
        total = sum(p for _, _, p in raw) or 1
        e["brackets"] = [{"low": lo, "high": hi, "p": p/total} for lo, hi, p in raw]
    out["tokens"][sym] = e
    out["config"][sym] = {"company": cfg["company"], "kind": cfg["kind"],
                          "polymarket": cfg["polymarket"]}
print(json.dumps(out))
"""


def main():
    if "--no-test" not in sys.argv:
        expected = expected_json()
        for label, cmd in TESTS:
            args = cmd + (["data/latest.json", expected] if "model" in cmd[1] else [])
            out = subprocess.run(args, cwd=HERE, capture_output=True, text=True)
            print(f"  {label}: {'ok' if out.returncode == 0 else 'FAILED'}")
            if out.returncode:
                print(out.stdout or out.stderr)
                raise SystemExit("nothing copied")
        os.remove(expected)

    missing = [f for f in FILES if not os.path.exists(os.path.join(SITE, f))]
    if missing:
        raise SystemExit(f"these are referenced but not there: {', '.join(missing)}")

    os.makedirs(DOCS, exist_ok=True)
    for f in FILES:
        shutil.copy2(os.path.join(SITE, f), os.path.join(DOCS, f))
    stale = [f for f in os.listdir(DOCS) if f not in FILES]
    for f in stale:
        os.remove(os.path.join(DOCS, f))
    print(f"copied {len(FILES)} files to docs"
          + (f", removed {len(stale)} no longer used" if stale else ""))


if __name__ == "__main__":
    main()
