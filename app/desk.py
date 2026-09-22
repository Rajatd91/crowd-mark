"""Build the desk: everything the terminal shows, for every token.

The page covers all eight PreStocks tokens, not only the four the crowd prices.
For the other four there is no prediction market, so the valuation columns stay
empty rather than being filled with a guess, and the rest of the desk still
applies: what it costs to trade, what the issuer can do, how deep the market is.

Every number here comes from a source that answered in this run, and the file
records when each one was read.
"""
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.request

import model as M
import sources as S
import wallet as W

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
JUP_QUOTE = ("https://lite-api.jup.ag/swap/v1/quote?inputMint={inp}&outputMint={out}"
             "&amount={amt}&slippageBps=300")
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
LADDER = [1_000, 10_000, 50_000]         # dollar sizes a real holder would trade


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.loads(r.read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                return None
            time.sleep(2)


def round_trip_cost(mint, decimals, price):
    """What a holder loses getting in and straight back out, at each size.

    Jupiter is asked for a real quote both ways, so this includes the pool's own
    price impact rather than a modelled spread. The Token-2022 transfer fee is
    charged on top by the mint itself, once in each direction.
    """
    out = []
    for dollars in LADDER:
        buy = get(JUP_QUOTE.format(inp=USDC, out=mint, amt=int(dollars * 1e6)))
        if not buy or "outAmount" not in buy:
            out.append({"size": dollars, "cost": None, "note": "no route"})
            continue
        tokens = int(buy["outAmount"])
        sell = get(JUP_QUOTE.format(inp=mint, out=USDC, amt=tokens))
        if not sell or "outAmount" not in sell:
            out.append({"size": dollars, "cost": None, "note": "no route back"})
            continue
        back = int(sell["outAmount"]) / 1e6
        out.append({
            "size": dollars,
            "cost": 1 - back / dollars,                 # fraction of the stake lost
            "impact_in": float(buy.get("priceImpactPct") or 0),
            "impact_out": float(sell.get("priceImpactPct") or 0),
        })
        time.sleep(0.25)
    return out


def market_depth(mint):
    """Liquidity, holders and traded volume, as Jupiter sees them."""
    d = get(f"https://lite-api.jup.ag/tokens/v2/search?query={mint}")
    if not d:
        return {}
    t = d[0]
    s = t.get("stats24h") or {}
    return {
        "holders": t.get("holderCount"),
        "liquidity": t.get("liquidity"),
        "volume24h": (s.get("buyVolume") or 0) + (s.get("sellVolume") or 0),
        "traders24h": s.get("numTraders"),
        "organic_buyers24h": s.get("numOrganicBuyers"),
        "price": t.get("usdPrice"),
    }


def fee_history():
    """When the issuer changed the transfer fee, from our own hourly snapshots.

    This is the evidence that the powers listed elsewhere are not theoretical.
    """
    import glob
    import gzip
    points, last = [], None
    for path in sorted(glob.glob(os.path.join(HERE, "..", "collector", "data", "*", "*.json.gz"))):
        try:
            with gzip.open(path) as f:
                snap = json.load(f)
        except Exception:
            continue
        epoch = (snap.get("epoch") or {}).get("epoch")
        acc = (snap.get("mint_accounts") or {}).get("ANTHROPIC")
        if not acc or epoch is None:
            continue
        for ext in acc["data"]["parsed"]["info"].get("extensions", []):
            if ext["extension"] != "transferFeeConfig":
                continue
            st = ext["state"]
            in_force = st["newerTransferFee"] if epoch >= st["newerTransferFee"]["epoch"] else st["olderTransferFee"]
            bps = in_force["transferFeeBasisPoints"]
            if bps != last:
                points.append({"at": snap["iso"], "epoch": epoch, "bps": bps})
                last = bps
    return points


def build():
    snap = json.load(open(os.path.join(HERE, "data", "latest.json")))
    epoch = W.current_epoch()
    spacex = M.spacex_conversion_gap(snap, S)
    desk = {
        "read_at": snap["iso"],
        "built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "epoch": epoch,
        "spacex": spacex,
        "fee_history": fee_history(),
        "tokens": {},
    }

    for row in snap["prestocks"]:
        sym = row["symbol"]
        cfg = S.TOKENS.get(sym)
        entry = {
            "symbol": sym,
            "company": row["name"].replace(" PreStocks", ""),
            "mint": row["contract_address"],
            "token_price": row["tokenPrice"],
            "mark_price": row["markPrice"],
            "premium_to_mark": M.premium_to_mark(row),
            "shares": M.implied_shares(row),
            "token_implied_value": M.token_implied_value(row),
            "covered": bool(cfg),                      # does the crowd price this one
            "read_at": snap["iso"],
            # The markets themselves, so the page can re-read them rather than
            # trust the numbers beside them.
            "sources": (cfg or {}).get("polymarket", {}),
        }
        if cfg:
            card = M.build_card(snap, sym, cfg)
            entry.update({
                "kind": card.kind,
                "crowd_value": card.crowd_value,
                "crowd_per_token": card.crowd_per_token,
                "crowd_low": (card.crowd_value_range or [None, None])[0],
                "crowd_high": (card.crowd_value_range or [None, None])[1],
                "gap": (card.crowd_per_token / card.token_price - 1) if card.crowd_per_token else None,
                "p_listing": card.p_listing,
                "open_top_mass": card.open_top_mass,
                "timing": card.timing,
                "ladder": card.ladder,
                "crowd_odds_at_token_price": card.crowd_odds_at_token_price,
                "assumptions": card.assumptions,
                "cap_source": card.cap_source,
                "brackets": [],
            })
            if card.cap_source:
                ev = snap["polymarket"].get(card.cap_source)
                ev = ev[0] if isinstance(ev, list) else ev
                raw, _, _ = M.cap_brackets(ev)
                total = sum(p for _, _, p in raw) or 1
                entry["brackets"] = [{"low": lo, "high": hi, "p": p / total} for lo, hi, p in raw]
            if card.crowd_per_token and spacex:
                entry["spacex_scenario"] = card.crowd_per_token * (1 - spacex["discount"])
        else:
            entry["kind"] = "unpriced"

        entry["powers"] = {k: v for k, v in W.issuer_powers(row["contract_address"], epoch).items()
                           if k in ("transfer_fee_bps", "next_transfer_fee_bps",
                                    "transfer_fee_changes_at_epoch", "paused",
                                    "permanent_delegate", "ui_multiplier", "freeze_authority")}
        entry["depth"] = market_depth(row["contract_address"])
        entry["round_trip"] = round_trip_cost(row["contract_address"], 9, row["tokenPrice"])
        desk["tokens"][sym] = entry
        print(f"  {sym:10} depth {entry['depth'].get('liquidity') or 0:>12,.0f}  "
              f"round trip {(entry['round_trip'][0]['cost'] or 0)*100:5.2f}% at $1k", flush=True)

    with open(os.path.join(HERE, "site", "desk.json"), "w") as f:
        json.dump(desk, f, indent=1)
    print(f"desk built, {len(desk['tokens'])} tokens, {len(desk['fee_history'])} fee changes seen")
    return desk


if __name__ == "__main__":
    build()
