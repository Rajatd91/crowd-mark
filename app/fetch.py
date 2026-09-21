"""Take one snapshot of every source Crowd Mark reads.

PreStocks keeps no price history and prediction-market odds move daily, so each
run is stored whole. The page is built from these files, which means every
number on it can be traced back to a timestamped response.

Usage:
    python3 fetch.py          # one snapshot into data/
    python3 fetch.py --loop   # one now, then every 15 minutes
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

import sources as S

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def attempt(into, key, fn):
    try:
        into[key] = fn()
    except Exception as e:  # noqa: BLE001 - a dead source must not lose the rest
        into.setdefault("errors", []).append({"what": key, "error": repr(e)})
    return into.get(key)


def snapshot():
    now = dt.datetime.now(dt.timezone.utc)
    snap = {"ts": int(now.timestamp()), "iso": now.isoformat(timespec="seconds")}

    attempt(snap, "prestocks", lambda: get(S.PRESTOCKS_API))
    attempt(snap, "prestocks_metrics", lambda: get(S.PRESTOCKS_METRICS))

    # Prediction markets, one call per event, keyed by the slug so nothing is guessed later.
    snap["polymarket"] = {}
    for sym, cfg in S.TOKENS.items():
        for role, slug in cfg["polymarket"].items():
            if slug in snap["polymarket"]:
                continue
            attempt(snap["polymarket"], slug, lambda s=slug: get(S.POLYMARKET_EVENT.format(slug=s)))
            time.sleep(0.4)

    snap["kalshi"] = {}
    for sym, cfg in S.TOKENS.items():
        series = cfg.get("kalshi_series")
        if series and series not in snap["kalshi"]:
            attempt(snap["kalshi"], series, lambda s=series: get(S.KALSHI_EVENTS.format(series=s)))
            time.sleep(0.4)

    mints = [c["mint"] for c in S.TOKENS.values()] + [S.SPACEX["mint"], S.SPACEX["listed_token"]]
    attempt(snap, "jupiter_price", lambda: get(S.JUPITER_PRICE.format(ids=",".join(mints))))
    attempt(snap, "jupiter_tokens", lambda: get(S.JUPITER_TOKENS.format(ids=",".join(mints))))

    os.makedirs(os.path.join(DATA, "history"), exist_ok=True)
    with open(os.path.join(DATA, "history", now.strftime("%Y%m%dT%H%M") + ".json"), "w") as f:
        json.dump(snap, f)
    with open(os.path.join(DATA, "latest.json"), "w") as f:
        json.dump(snap, f, indent=1)

    errs = len(snap.get("errors", [])) + len(snap["polymarket"].get("errors", [])) + len(snap["kalshi"].get("errors", []))
    print(f"{snap['iso']} prestocks={len(snap.get('prestocks') or [])} "
          f"polymarket={len([k for k in snap['polymarket'] if k != 'errors'])} "
          f"kalshi={len([k for k in snap['kalshi'] if k != 'errors'])} errors={errs}", flush=True)
    return snap


def main():
    loop = "--loop" in sys.argv
    with open(os.path.join(HERE, "fetch.pid"), "w") as f:
        f.write(str(os.getpid()))
    while True:
        try:
            snapshot()
        except Exception as e:  # noqa: BLE001
            print(f"FAILED {e!r}", flush=True)
        if not loop:
            break
        time.sleep(900 - (time.time() % 900))


if __name__ == "__main__":
    main()
