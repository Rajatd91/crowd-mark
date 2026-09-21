"""Hourly snapshot collector for PreStocks liquidity on Meteora DLMM.

Records the state that cannot be rebuilt later: pool depth (raw bin arrays),
pool config and TVL, PreStocks mark prices, and each mint's Token-2022 fee
settings, so the transfer-fee change at epoch 1039 (0.5% -> 1.0%) can be
compared before and after. Everything is read-only public data.

Raw responses are stored as-is (gzip JSON) and decoded later, so nothing is
lost to a decoding assumption made today.

Usage:
    python3 collector.py          # one snapshot
    python3 collector.py --loop   # one snapshot now, then every hour
"""
import base64
import datetime as dt
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
STATE = os.path.join(HERE, "tracked_pools.json")

RPC = "https://api.mainnet-beta.solana.com"
METEORA = "https://dlmm.datapi.meteora.ag"
PRESTOCKS = "https://prestocks.com/api"
JUP_PRICE = "https://lite-api.jup.ag/price/v3?ids="
DLMM_PROGRAM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo"
BIN_ARRAY_SIZE = 10136      # DLMM BinArray account size, lb_pair pubkey at offset 24
SOL = "So11111111111111111111111111111111111111112"
MIN_TVL = 1000.0            # start tracking a pool once its TVL reaches $1k
UA = {"User-Agent": "Mozilla/5.0"}   # Meteora's API rejects the default urllib agent


def _open(req, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(3 * (i + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if i < tries - 1:
                time.sleep(3 * (i + 1))
                continue
            raise


def get(url):
    return _open(urllib.request.Request(url, headers=UA))


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    r = _open(urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json"}))
    if "error" in r:
        raise RuntimeError(f"{method}: {r['error']}")
    return r["result"]


def attempt(snap, key, fn):
    """Run one fetch; record the result or the error, never abort the snapshot."""
    try:
        snap[key] = fn()
    except Exception as e:  # noqa: BLE001 - every failure is logged in the snapshot
        snap.setdefault("errors", []).append({"what": key, "error": repr(e)})
    return snap.get(key)


def load_tracked():
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return {}


def snapshot():
    t0 = time.time()
    now = dt.datetime.now(dt.timezone.utc)
    snap = {"ts": int(t0), "iso": now.isoformat(timespec="seconds")}

    attempt(snap, "epoch", lambda: rpc("getEpochInfo", []))
    tokens = attempt(snap, "prestocks", lambda: get(f"{PRESTOCKS}/prestocks")) or []
    attempt(snap, "prestocks_metrics", lambda: get(f"{PRESTOCKS}/metrics"))  # undocumented endpoint

    mints = {t["symbol"]: t["contract_address"] for t in tokens}
    if not mints:  # fall back to the last known mint list so pool tracking continues
        mints = load_tracked().get("_mints", {})
    snap["mints"] = mints

    # Token-2022 mint state: transfer fee (older/newer + epoch), UI multiplier, pause flag
    snap["mint_accounts"] = {}
    for sym, mint in mints.items():
        attempt(snap["mint_accounts"], sym,
                lambda m=mint: rpc("getAccountInfo", [m, {"encoding": "jsonParsed"}])["value"])
        time.sleep(0.3)

    attempt(snap, "jup_prices", lambda: get(JUP_PRICE + ",".join(list(mints.values()) + [SOL])))

    # Every Meteora DLMM pool holding each PreStocks token (full API records)
    snap["meteora_pools"] = {}
    for sym, mint in mints.items():
        attempt(snap["meteora_pools"], sym,
                lambda m=mint: get(f"{METEORA}/pools?query={m}&page_size=100"))
        time.sleep(0.3)

    # Sticky tracked set: once a pool reaches MIN_TVL it stays tracked,
    # so a before/after comparison is never broken by a pool dropping out.
    tracked = load_tracked()
    for sym, resp in snap["meteora_pools"].items():
        for p in (resp or {}).get("data", []):
            if (p.get("tvl") or 0) >= MIN_TVL and p["address"] not in tracked:
                tracked[p["address"]] = {"symbol": sym, "name": p.get("name"),
                                         "first_tracked": snap["iso"]}
    tracked["_mints"] = mints
    with open(STATE, "w") as f:
        json.dump(tracked, f, indent=1)

    # Raw on-chain pool state and liquidity bins for every tracked pool
    snap["pools_onchain"] = {}
    for addr in [a for a in tracked if not a.startswith("_")]:
        rec = {}
        attempt(rec, "lb_pair", lambda a=addr: rpc("getAccountInfo", [a, {"encoding": "base64"}])["value"])
        attempt(rec, "bin_arrays", lambda a=addr: rpc("getProgramAccounts", [DLMM_PROGRAM, {
            "encoding": "base64",
            "filters": [{"dataSize": BIN_ARRAY_SIZE}, {"memcmp": {"offset": 24, "bytes": a}}],
            "withContext": True,
        }]))
        snap["pools_onchain"][addr] = rec
        time.sleep(0.5)

    snap["secs"] = round(time.time() - t0, 1)
    day = os.path.join(DATA, now.strftime("%Y-%m-%d"))
    os.makedirs(day, exist_ok=True)
    path = os.path.join(day, now.strftime("%H%M") + ".json.gz")
    with gzip.open(path, "wt") as f:
        json.dump(snap, f)

    n_pools = len(snap["pools_onchain"])
    n_bins = sum(len(((r.get("bin_arrays") or {}).get("value")) or [])
                 for r in snap["pools_onchain"].values())
    epoch = (snap.get("epoch") or {}).get("epoch")
    errs = len(snap.get("errors", [])) + sum(len(r.get("errors", [])) for r in snap["pools_onchain"].values())
    size_kb = os.path.getsize(path) // 1024
    print(f"{snap['iso']} epoch={epoch} tokens={len(mints)} pools={n_pools} "
          f"bin_arrays={n_bins} errors={errs} secs={snap['secs']} file={size_kb}KB", flush=True)


def main():
    with open(os.path.join(HERE, "collector.pid"), "w") as f:
        f.write(str(os.getpid()))
    loop = "--loop" in sys.argv
    while True:
        try:
            snapshot()
        except Exception as e:  # noqa: BLE001 - keep the hourly loop alive
            print(f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} FAILED {e!r}", flush=True)
        if not loop:
            break
        # sleep to two minutes past the next hour
        now = time.time()
        time.sleep(3600 - (now % 3600) + 120)


if __name__ == "__main__":
    main()
