"""Publish the Crowd Mark site to docs/pulse, with a fresh fallback snapshot.

The site reads Polymarket live from the visitor's browser. The snapshot is
only what it shows when that fails, and the page states its age. It is built
from the keeper's latest fetch, so it is as fresh as the last hourly run.

Usage:
    python3 pulse/build.py
"""
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LATEST = os.path.join(ROOT, "app", "data", "latest.json")
OUT = os.path.join(ROOT, "docs", "pulse")

PUBLISH = ["index.html", "css", "js", "favicon.svg"]


def slugs():
    """Every slug the company list names, read from companies.js itself."""
    src = open(os.path.join(HERE, "js", "companies.js")).read()
    return sorted(set(re.findall(r'"([a-z0-9-]+-[a-z0-9-]+)"', src)) - {"anthropic", "openai"})


def num(v):
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def normalize(raw):
    """The same shape markets.js produces, so the page reads both the same way."""
    markets = []
    for m in raw.get("markets", []):
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except ValueError:
                prices = None
        markets.append({
            "title": (m.get("groupItemTitle") or m.get("question") or "").strip(),
            "question": m.get("question") or "",
            "slug": m.get("slug") or "",
            "yes": num(prices[0]) if prices else None,
            "closed": bool(m.get("closed")),
            "dayChange": num(m.get("oneDayPriceChange")),
            "weekChange": num(m.get("oneWeekPriceChange")),
            "volume": num(m.get("volumeNum", m.get("volume"))),
            "liquidity": num(m.get("liquidityNum", m.get("liquidity"))),
        })
    return {
        "slug": raw.get("slug"), "title": raw.get("title") or raw.get("slug"),
        "volume": num(raw.get("volume")), "liquidity": num(raw.get("liquidity")),
        "endDate": raw.get("endDate"), "closed": bool(raw.get("closed")),
        "image": raw.get("image") or raw.get("icon"),
        "markets": markets,
    }


def snapshot():
    if not os.path.exists(LATEST):
        print("  no app/data/latest.json yet; publishing without a fallback snapshot")
        return {"as_of": None, "events": {}}
    data = json.load(open(LATEST))
    events = {}
    for slug in slugs():
        raw = data.get("polymarket", {}).get(slug)
        if raw is None:
            continue
        events[slug] = normalize(raw[0] if isinstance(raw, list) else raw)
    missing = set(slugs()) - set(events)
    if missing:
        print(f"  not in the latest fetch: {', '.join(sorted(missing))}")
    return {"as_of": data.get("iso"), "events": events}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name in PUBLISH:
        src, dst = os.path.join(HERE, name), os.path.join(OUT, name)
        if not os.path.exists(src):
            sys.exit(f"missing {name}")
        if os.path.isdir(src):
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
    snap = snapshot()
    with open(os.path.join(OUT, "snapshot.json"), "w") as f:
        json.dump(snap, f, separators=(",", ":"))
    print(f"  published to docs/pulse with {len(snap['events'])} events "
          f"in the fallback snapshot (as of {snap['as_of']})")


if __name__ == "__main__":
    main()
