"""Publish the data as an API anyone can read, with no key and no signup.

Everything this terminal knows is already computed each hour. Keeping it locked
inside one web page would waste it, and a number nobody else can fetch is a
number nobody can check.

So the same figures are written as flat JSON at stable paths. No key, no
account, no rate limit worth mentioning, because these are static files served
from the same place as the page. The shapes below are the contract: fields get
added, never renamed or removed, and anything that changes meaning gets a new
version.

Written from the files the keeper already produces, so the API cannot drift
from what the terminal shows. If they disagree, this script is wrong.

Usage:
    python3 api.py
"""
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
OUT = os.path.join(SITE, "api", "v1")
BASE = "https://rajatd91.github.io/crowd-mark/api/v1"


def load(name):
    path = os.path.join(SITE, name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def tokens_doc(desk):
    """Every token, with all three readings of what it is worth."""
    rows = []
    for symbol, t in desk["tokens"].items():
        trip = {str(r["size"]): r.get("cost") for r in (t.get("round_trip") or [])}
        rows.append({
            "symbol": symbol,
            "company": t["company"],
            "mint": t["mint"],
            "token_price_usd": t["token_price"],
            "issuer_mark_usd": t["mark_price"],
            "premium_to_issuer_mark": t.get("premium_to_mark"),
            "shares_per_token": t.get("shares"),
            "company_value_token_implies_usd": t.get("token_implied_value"),
            "crowd_value_usd": t.get("crowd_value"),
            "crowd_per_token_usd": t.get("crowd_per_token"),
            "gap_to_crowd": t.get("gap"),
            "crowd_source_market": t.get("cap_source"),
            "crowd_has_market": bool(t.get("covered")),
            "round_trip_cost_by_size_usd": trip,
            "liquidity_usd": (t.get("depth") or {}).get("liquidity"),
            "volume_24h_usd": (t.get("depth") or {}).get("volume24h"),
            "holders": (t.get("depth") or {}).get("holders"),
            "issuer_powers": t.get("powers") or {},
        })
    rows.sort(key=lambda r: r["symbol"])
    return {
        "generated_at": int(time.time()),
        "sources_read_at": desk["read_at"],
        "count": len(rows),
        "tokens": rows,
        "notes": {
            "gap_to_crowd": "crowd_per_token_usd divided by token_price_usd, minus one. "
                            "Null where no prediction market prices the company.",
            "issuer_mark_usd": "The issuer's own mark. The issuer is the party selling "
                               "the token, so this is not independent.",
            "round_trip_cost_by_size_usd": "Measured from real Jupiter quotes in both "
                                           "directions, including the transfer fee.",
        },
    }


def marks_doc(chain):
    """What is published on Solana, and who last refreshed it."""
    meta = chain.get("_meta") or {}
    rows = []
    for symbol, m in chain.items():
        if symbol == "_meta":
            continue
        rows.append({
            "symbol": symbol,
            "account": m.get("account"),
            "company": m.get("company"),
            "crowd_value_usd": m.get("crowd_value"),
            "crowd_per_token_usd": m.get("crowd_per_token"),
            "token_price_usd": m.get("token_price"),
            "sources_read_at": m.get("source_read_at"),
            "published_at": m.get("published_at"),
            "slot": m.get("slot"),
            "sources_hash": m.get("sources_hash"),
            "last_publisher": m.get("last_publisher"),
            "publish_count": m.get("publish_count"),
            "stale": m.get("stale"),
        })
    rows.sort(key=lambda r: r["symbol"])
    return {
        "generated_at": int(time.time()),
        "program": meta.get("program"),
        "cluster": meta.get("cluster"),
        "count": len(rows),
        "marks": rows,
        "notes": {
            "open": "Anyone may refresh a mark. The program records who did.",
            "sources_hash": "sha256 of the exact inputs the value was computed from. "
                            "The page recomputes it in the browser to check it.",
            "stale": "True once a mark is more than six hours old, which the program "
                     "states about itself.",
        },
    }


def pools_doc(lp):
    """What a liquidity provider earns, and the width at which it stops paying."""
    rows = [{
        "pool": p["pool"],
        "address": p["address"],
        "symbol": p["symbol"],
        "liquidity_usd": p["tvl"],
        "base_fee_pct": p["base_fee_pct"],
        "bin_step": p["bin_step"],
        "fee_income_per_day": p["fee_yield_day"],
        "turnover_per_day": p["turnover_day"],
        "volatility_annual": p["sigma"],
        "arbitrage_loss_per_day_full_range": p["lvr_day_cpmm"],
        "breakeven_half_width": p["breakeven_half_width"],
        "transfer_fee_bps": p["transfer_fee_bps"],
        "entry_and_exit_cost": p["entry_exit_cost"],
        "days_to_recover_entry": p["days_to_recover_entry"],
        "readings": p["snapshots"],
    } for p in lp["pools"] if p.get("corroborated") and not p.get("never_traded")]
    rows.sort(key=lambda r: -(r["liquidity_usd"] or 0))
    return {
        "generated_at": int(time.time()),
        "hourly_readings": lp["window_hours"],
        "count": len(rows),
        "pools": rows,
        "notes": {
            "measured": "Fee income, turnover and volatility come from our own hourly "
                        "readings of each pool.",
            "modelled": "The arbitrage loss is the rate in Milionis, Moallemi, "
                        "Roughgarden and Zhang (2022), arXiv 2208.06046, equation 16, "
                        "raised for a concentrated position by their Example 4.",
            "breakeven_half_width": "Place liquidity wider than this around the price "
                                    "and the fees cover the arbitrage loss. Tighter and "
                                    "they do not.",
            "excluded": "Pools whose reported fee income and volume disagree, and pools "
                        "that have not traded, are left out rather than shown as measured.",
        },
    }


def build():
    desk, chain, lp = load("desk.json"), load("onchain.json"), load("liquidity.json")
    if not desk:
        raise SystemExit("no desk.json to publish, run desk.py first")

    os.makedirs(OUT, exist_ok=True)
    written = {}

    def write(name, doc, what):
        with open(os.path.join(OUT, name), "w") as f:
            json.dump(doc, f, indent=1)
        written[name] = what

    write("tokens.json", tokens_doc(desk),
          "Every token, what it costs, what the crowd says it is worth, what a round "
          "trip costs and what the issuer can do to a holder.")
    if chain:
        write("marks.json", marks_doc(chain),
              "What is published on Solana for each company, with the hash of its "
              "inputs and who last refreshed it.")
    if lp:
        write("pools.json", pools_doc(lp),
              "Every liquidity pool holding one of these tokens, what it pays and the "
              "range width at which it stops paying.")

    index = {
        "name": "Crowd Mark",
        "version": 1,
        "generated_at": int(time.time()),
        "base": BASE,
        "auth": "None. No key, no signup, no account.",
        "format": "Static JSON, regenerated every hour beside the page that uses it.",
        "stability": "Fields are added, never renamed or removed. A change of meaning "
                     "gets a new version path.",
        "endpoints": [{"path": f"{BASE}/{name}", "what": what}
                      for name, what in written.items()],
        "source": "https://github.com/Rajatd91/crowd-mark",
        "terms": "Use it for anything. It is public data, computed from public markets, "
                 "and it comes with no warranty of any kind.",
    }
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump(index, f, indent=1)

    total = sum(os.path.getsize(os.path.join(OUT, n)) for n in os.listdir(OUT))
    print(f"api written, {len(written) + 1} files, {total/1024:.0f} kB")
    return index


if __name__ == "__main__":
    build()
