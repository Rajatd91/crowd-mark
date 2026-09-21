"""Turn the latest snapshot into the one file the web page reads.

The page is static. Everything it shows is computed here, from a stored
snapshot, so the browser never needs a key and every number on screen has a
timestamp behind it.
"""
import datetime as dt
import json
import os

import model as M
import sources as S
import wallet as W

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")


def build():
    snap = json.load(open(os.path.join(HERE, "data", "latest.json")))
    epoch = W.current_epoch()
    spacex = M.spacex_conversion_gap(snap, S)
    out = {"read_at": snap["iso"], "epoch": epoch, "spacex": spacex, "tokens": {}}

    for sym, cfg in S.TOKENS.items():
        c = M.build_card(snap, sym, cfg)
        powers = W.issuer_powers(cfg["mint"], epoch)
        gap = (c.crowd_per_token / c.token_price - 1) if c.crowd_per_token else None

        # The distribution itself, so the page can draw what the crowd believes
        # rather than only its average.
        brackets = []
        if c.cap_source:
            ev = snap["polymarket"].get(c.cap_source)
            ev = ev[0] if isinstance(ev, list) else ev
            raw, _p_no, _notes = M.cap_brackets(ev)
            total = sum(p for _, _, p in raw) or 1
            brackets = [{"low": lo, "high": hi, "p": p / total} for lo, hi, p in raw]
        out["tokens"][sym] = {
            "company": c.company, "kind": c.kind, "mint": cfg["mint"],
            "token_price": c.token_price, "mark_price": c.mark_price,
            "premium_to_mark": c.premium_to_mark, "shares": c.shares,
            "token_implied_value": c.token_implied_value,
            "crowd_value": c.crowd_value, "crowd_per_token": c.crowd_per_token,
            "crowd_value_range": c.crowd_value_range, "cap_source": c.cap_source,
            "p_listing": c.p_listing,
            "open_top_mass": c.open_top_mass, "brackets": brackets,
            "gap": gap, "timing": c.timing, "ladder": c.ladder,
            "crowd_odds_at_token_price": c.crowd_odds_at_token_price,
            "assumptions": c.assumptions,
            "powers": {k: powers.get(k) for k in
                       ("transfer_fee_bps", "next_transfer_fee_bps",
                        "transfer_fee_changes_at_epoch", "paused",
                        "permanent_delegate", "ui_multiplier")},
            "spacex_scenario": (c.crowd_per_token * (1 - spacex["discount"])
                                if (c.crowd_per_token and spacex) else None),
        }

    # The history behind the one issuer change we watched happen, so the page can
    # show that these powers are used, not theoretical.
    out["fee_change"] = {
        "token": "every PreStocks token",
        "from_bps": 50, "to_bps": 100,
        "observed_between": ["2026-09-20T21:02Z", "2026-09-20T22:02Z"],
        "note": "caught by this project's own hourly snapshots, at the epoch 1039 boundary",
    }

    os.makedirs(SITE, exist_ok=True)
    with open(os.path.join(SITE, "data.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"site data written, {len(out['tokens'])} tokens, read at {out['read_at']}")
    return out


if __name__ == "__main__":
    build()
