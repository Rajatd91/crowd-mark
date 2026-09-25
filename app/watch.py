"""What can be done to a holder's balance, what has been done, and what is next.

A Token-2022 mint is not a fixed thing. It is a contract the issuer can amend,
and these eight have amendment powers switched on: a transfer fee it can raise,
a multiplier that rescales every balance, a pause switch, a freeze authority and
a delegate that can move tokens out of any wallet.

Every tool that looks at these mints reports a snapshot. This reports three
things none of them do.

**What is actually in force.** The mint stores the current setting and the next
one side by side, and which applies depends on the epoch or the clock. Reading
the obvious field gives the wrong answer: the multiplier field on the SpaceX
mint says 1 while 5 has been in force since 10 June, and RugCheck's own API
returns both raw values and resolves neither. Anything reading the obvious
field is five times wrong on SpaceX and about one and a half times wrong on
OpenAI.

**What the powers are actually worth.** "Fee config enabled" is not a risk
statement. The maximum fee on these mints is 2^64-1, which is to say uncapped,
so the issuer may set the fee to one hundred percent and take a holder's entire
balance on their next transfer. That is the exposure, and it is expressible in
dollars.

**What is coming.** A fee change takes effect two epochs after it is set, and a
multiplier change carries its own effective timestamp. The chain therefore
announces these changes days before they bite. Nobody reads the announcement.

Usage:
    python3 watch.py
"""
import json
import os
import time

import sources as S
import wallet as W

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOTS = os.path.join(HERE, "..", "collector", "data", "*", "*.json.gz")

# A u64 maximum fee means the issuer set no ceiling at all.
UNCAPPED = 2 ** 64 - 1
SLOT_SECONDS = 0.4          # Solana's target, used only to say roughly when


def in_force(extensions, epoch, now, base=None):
    """Resolve every amendable power to the value that actually applies.

    This is the part other readers get wrong. Both the current and the pending
    value are stored together, and the deciding field is an epoch for the fee
    and a wall clock timestamp for the multiplier. Taking the obvious field
    without checking either is how a five times error gets published.
    """
    out = {
        "transfer_fee_bps": 0, "fee_uncapped": False, "max_fee": None,
        "multiplier": 1.0, "paused": False,
        "freeze_authority": None, "permanent_delegate": None,
        "pending": [],
    }
    # Two of the strongest powers are not extensions at all. They sit on the
    # base mint, which is why a reader that only walks the extension list
    # reports a token as safer than it is.
    if base:
        out["freeze_authority"] = base.get("freezeAuthority")
        out["mint_authority"] = base.get("mintAuthority")

    for ext in extensions or []:
        kind, state = ext.get("extension"), ext.get("state") or {}

        if kind == "transferFeeConfig":
            older, newer = state["olderTransferFee"], state["newerTransferFee"]
            live = newer if epoch >= newer["epoch"] else older
            out["transfer_fee_bps"] = live["transferFeeBasisPoints"]
            cap = int(live["maximumFee"])
            out["max_fee"] = cap
            out["fee_uncapped"] = cap >= UNCAPPED
            out["fee_authority"] = state.get("transferFeeConfigAuthority")
            if epoch < newer["epoch"]:
                out["pending"].append({
                    "what": "transfer fee",
                    "from": f"{older['transferFeeBasisPoints'] / 100:.2f}%",
                    "to": f"{newer['transferFeeBasisPoints'] / 100:.2f}%",
                    "when": f"epoch {newer['epoch']}",
                    "epochs_away": newer["epoch"] - epoch,
                })

        elif kind == "scaledUiAmountConfig":
            nxt = state.get("newMultiplier")
            at = state.get("newMultiplierEffectiveTimestamp") or 0
            current = state.get("multiplier")
            # The effective timestamp decides. If it has passed, the new value
            # is the one in force, whatever the plain field still says.
            out["multiplier"] = float(nxt if at and now >= at else current)
            out["multiplier_naive"] = float(current)
            out["multiplier_authority"] = state.get("authority")
            if at and now < at and str(nxt) != str(current):
                out["pending"].append({
                    "what": "balance multiplier",
                    "from": str(current), "to": str(nxt),
                    "when": time.strftime("%d %b %Y %H:%M", time.gmtime(at)) + " UTC",
                    "seconds_away": at - now,
                })

        elif kind == "pausableConfig":
            out["paused"] = bool(state.get("paused"))
            out["pause_authority"] = state.get("authority")

        elif kind == "permanentDelegate":
            out["permanent_delegate"] = state.get("delegate")

    return out


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
SQUADS_V4 = "SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf"
SQUADS_V3 = "SMPLecH534NA9acpos4G6x7uf3LWbCAwZQE9e8ZekMu"


def on_curve(address):
    """Is this an ordinary wallet, or a program derived address?

    An ordinary address is a point on the ed25519 curve, because it is the
    public half of somebody's key. A program derived address is chosen to be
    off the curve precisely so no key can sign for it, which is what a multisig
    vault is. The difference decides whether one person holds these powers or a
    quorum does, so it is worth checking rather than assuming.
    """
    n = 0
    for c in address:
        n = n * 58 + B58.index(c)
    b = n.to_bytes(32, "big")
    p = (1 << 255) - 19
    d = (-121665 * pow(121666, p - 2, p)) % p
    y = int.from_bytes(b, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= p:
        return False
    y2 = y * y % p
    u, v = (y2 - 1) % p, (d * y2 + 1) % p
    x2 = u * pow(v, p - 2, p) % p
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = x * pow(2, (p - 1) // 4, p) % p
        if (x * x - x2) % p != 0:
            return False
    return not (x == 0 and sign)


def governance(authorities, reads=12):
    """Who holds these powers, and whether holding them is separated at all.

    The test is not how many tokens exist. It is whether the money, the assets
    and the records are controlled separately, because an attestation of
    reserves means nothing if the same approval that proves them can also mint,
    freeze, seize or rescale them afterwards.

    So this counts the distinct holders across every power on every mint, says
    whether that holder is a wallet or a vault, and looks at who has actually
    been signing for it.
    """
    holders, slots = {}, 0
    for mint_powers in authorities:
        for power, who in mint_powers.items():
            if who:
                # One slot per power per mint. The same address holding the
                # same power on eight mints is eight slots, not one, because
                # that is eight tokens it can act on.
                slots += 1
                holders.setdefault(who, set()).add(power)
    if not holders:
        return None

    main = max(holders, key=lambda k: len(holders[k]))
    out = {
        "distinct_holders": len(holders),
        "authority": main,
        "powers_held": sorted(holders[main]),
        "power_slots": slots,
        "mints": len(authorities),
        "is_wallet": on_curve(main),
        "kind": "an ordinary wallet" if on_curve(main) else "a program derived address",
        "program": None, "signers": [], "reads": 0,
    }
    # Who signs for it, which a program derived address cannot do by itself.
    try:
        sigs = W.rpc("getSignaturesForAddress", [main, {"limit": reads}])
        seen = {}
        for sig in sigs:
            tx = W.rpc("getTransaction", [sig["signature"],
                       {"maxSupportedTransactionVersion": 0, "encoding": "jsonParsed"}])
            if not tx:
                continue
            out["reads"] += 1
            msg = tx["transaction"]["message"]
            for key in msg.get("accountKeys", []):
                if key.get("signer"):
                    seen[key["pubkey"]] = seen.get(key["pubkey"], 0) + 1
            for ix in msg.get("instructions", []):
                pid = ix.get("programId")
                if pid == SQUADS_V4:
                    out["program"] = "Squads multisig v4"
                elif pid == SQUADS_V3:
                    out["program"] = "Squads multisig v3"
        out["signers"] = [{"key": k, "signed": n}
                          for k, n in sorted(seen.items(), key=lambda x: -x[1])]
    except Exception:
        pass
    return out


def exposure(powers, value_usd):
    """What each power is worth, in dollars, on a holding of this size.

    A list of capabilities tells a holder nothing. What they can act on is the
    amount at stake, so every power is priced against the position rather than
    named.
    """
    fee = powers["transfer_fee_bps"] / 1e4
    rows = [{
        "power": "The transfer fee it charges today",
        "costs": value_usd * fee,
        "detail": f"{powers['transfer_fee_bps'] / 100:.2f}% of every transfer, "
                  f"charged again when you sell",
        "severity": "now",
    }]
    if powers["fee_uncapped"]:
        rows.append({
            "power": "The fee has no ceiling",
            "costs": value_usd,
            "detail": "The maximum fee on this mint is set to the largest number it can "
                      "hold, so the issuer may raise the fee to 100% and take the whole "
                      "balance on your next transfer",
            "severity": "worst",
        })
    if powers["permanent_delegate"]:
        rows.append({
            "power": "A permanent delegate can move your tokens",
            "costs": value_usd,
            "detail": "This authority can transfer your balance out of your wallet "
                      "without your signature",
            "severity": "worst",
        })
    if powers["freeze_authority"]:
        rows.append({
            "power": "A freeze authority can stop you selling",
            "costs": value_usd,
            "detail": "Your account can be frozen, which does not take the balance but "
                      "does end your ability to act on it",
            "severity": "worst",
        })
    if powers.get("mint_authority"):
        rows.append({
            "power": "More tokens can be minted at any time",
            "costs": None,
            "detail": "The mint authority is still live, so the supply behind each claim "
                      "can be increased without notice",
            "severity": "worst",
        })
    if not powers["paused"]:
        rows.append({
            "power": "Transfers can be paused for everyone",
            "costs": value_usd,
            "detail": "The mint carries a pause switch that is currently off",
            "severity": "worst",
        })
    return rows


def amendments():
    """Every change to these powers that our own snapshots have witnessed.

    Not because the chain forgets. The mint keeps one step of its past in
    olderTransferFee, and every change is a transaction, so the record can be
    rebuilt from the log wherever the endpoint still serves it. What an hourly
    archive adds is narrower and worth stating honestly: the wall clock moment,
    since the mint records only an epoch, and durability, since replaying
    transactions fails once an endpoint stops retaining them.
    """
    import glob
    import gzip

    seen, log = {}, []
    for path in sorted(glob.glob(SNAPSHOTS)):
        try:
            with gzip.open(path) as f:
                snap = json.load(f)
        except Exception:
            continue
        epoch = (snap.get("epoch") or {}).get("epoch")
        when = snap.get("iso")
        if epoch is None:
            continue
        now = snap.get("ts") or 0
        for symbol, account in (snap.get("mint_accounts") or {}).items():
            if not isinstance(account, dict):
                continue
            info = (account.get("data") or {})
            info = info.get("parsed") if isinstance(info, dict) else None
            exts = ((info or {}).get("info") or {}).get("extensions")
            if not exts:
                continue
            state = in_force(exts, epoch, now, base=(info or {}).get("info") or {})
            key = (state["transfer_fee_bps"], state["multiplier"], state["paused"])
            was = seen.get(symbol)
            if was is not None and was != key:
                log.append({
                    "at": when, "epoch": epoch, "symbol": symbol,
                    "fee_from": was[0], "fee_to": key[0],
                    "multiplier_from": was[1], "multiplier_to": key[1],
                    "paused_from": was[2], "paused_to": key[2],
                })
            seen[symbol] = key
    return log


def build():
    desk_path = os.path.join(HERE, "site", "desk.json")
    desk = json.load(open(desk_path)) if os.path.exists(desk_path) else {"tokens": {}}
    epoch_info = W.rpc("getEpochInfo", [])
    epoch = epoch_info["epoch"]
    left = (epoch_info["slotsInEpoch"] - epoch_info["slotIndex"]) * SLOT_SECONDS
    now = int(time.time())

    tokens, wrong = {}, []
    for symbol, t in desk["tokens"].items():
        acc = W.rpc("getAccountInfo", [t["mint"], {"encoding": "jsonParsed"}])
        info = (((acc or {}).get("value") or {}).get("data") or {}) \
            .get("parsed", {}).get("info", {})
        powers = in_force(info.get("extensions", []), epoch, now, base=info)
        powers["authorities"] = {
            "mint": info.get("mintAuthority"),
            "freeze": info.get("freezeAuthority"),
            "fee": powers.get("fee_authority"),
            "pause": powers.get("pause_authority"),
            "multiplier": powers.get("multiplier_authority"),
            "delegate": powers.get("permanent_delegate"),
        }
        value = (t.get("depth") or {}).get("liquidity") or 0
        powers["exposure"] = exposure(powers, value)
        powers["mint"] = t["mint"]
        powers["company"] = t["company"]
        powers["token_price"] = t["token_price"]
        powers["holders"] = (t.get("depth") or {}).get("holders")
        powers["liquidity"] = value
        tokens[symbol] = powers
        # Where the obvious field disagrees with what is actually in force,
        # every reader that does not resolve it is wrong by this factor.
        naive = powers.get("multiplier_naive")
        if naive is not None and naive != powers["multiplier"]:
            wrong.append({"symbol": symbol, "naive": naive,
                          "in_force": powers["multiplier"],
                          "factor": powers["multiplier"] / naive if naive else None})

    log = amendments()
    gov = governance([t["authorities"] for t in tokens.values()])
    out = {
        "governance": gov,
        "read_at": now,
        "epoch": epoch,
        "hours_to_next_epoch": round(left / 3600, 1),
        "tokens": tokens,
        "amendments": log,
        "misread": wrong,
        "watching_since": "2026-09-19",
        "note": ("The current and pending settings are stored together on the mint and "
                 "which one applies depends on the epoch or the clock. Everything here "
                 "is resolved to what is actually in force."),
    }
    with open(os.path.join(HERE, "site", "watch.json"), "w") as f:
        json.dump(out, f, indent=1)

    total = sum(t["liquidity"] for t in tokens.values())
    holders = sum(t["holders"] or 0 for t in tokens.values())
    print(f"  epoch {epoch}, {left/3600:.1f} h to the next")
    print(f"  {len(tokens)} mints, {holders:,} wallets, ${total:,.0f} exposed")
    print(f"  {len(log)} amendments witnessed since 19 Sep")
    if gov:
        print(f"  {gov['power_slots']} power slots across {len(tokens)} mints held by "
              f"{gov['distinct_holders']} address(es)")
        print(f"  authority is {gov['kind']}"
              + (f", {gov['program']}" if gov["program"] else "")
              + f", {len(gov['signers'])} signers seen in {gov['reads']} transactions")
    for w in wrong:
        print(f"  MISREAD {w['symbol']}: obvious field says {w['naive']}, "
              f"in force is {w['in_force']} ({w['factor']:.4g}x)")
    for p in [p for t in tokens.values() for p in t["pending"]]:
        print(f"  PENDING {p['what']} {p['from']} -> {p['to']} at {p['when']}")
    return out


if __name__ == "__main__":
    build()
