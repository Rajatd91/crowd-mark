"""Read a holder's position, and the issuer's power over it, from Solana.

Both halves matter. The balance is what the holder owns. The mint's Token-2022
extensions are what the issuer can still do to it: charge a transfer fee that
changes at an epoch boundary, pause every transfer, reassign a balance through
a permanent delegate, or rescale what every wallet displays through a UI
multiplier. None of that is visible off-chain, which is why this file exists.
"""
import json
import os
import time
import urllib.error
import urllib.request

def _env(name):
    """Read a setting from the environment, falling back to the local .env file.

    The .env file is git-ignored, so keys stay out of the repository and out of
    anything submitted.
    """
    if os.environ.get(name):
        return os.environ[name]
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(path):
        for line in open(path):
            key, _, value = line.strip().partition("=")
            if key == name:
                return value
    return None


# A keyed endpoint is used when one is configured, since the public ones rate
# limit hard and refuse some calls outright. The public endpoints stay as
# fallbacks so nothing breaks without a key.
ENDPOINTS = [u for u in [_env("SOLANA_RPC"),
                         "https://api.mainnet-beta.solana.com",
                         "https://solana-rpc.publicnode.com"] if u]
RPC = ENDPOINTS[0]
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def rpc(method, params, url=None):
    """One RPC call, retried across endpoints. Public nodes answer 429 often."""
    urls = [url] if url else ENDPOINTS
    last = None
    for attempt in range(3):
        for endpoint in urls:
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                               "params": params}).encode()
            req = urllib.request.Request(endpoint, data=body,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    out = json.loads(r.read())
                if "error" in out:
                    raise RuntimeError(f"{method}: {out['error']}")
                return out["result"]
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
                last = e
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{method} failed on every endpoint: {last!r}")


def looks_like_address(text):
    text = (text or "").strip()
    if not 32 <= len(text) <= 44:
        return False
    return all(c in "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz" for c in text)


def holdings(owner, tokens, url=RPC):
    """Every PreStocks token this wallet holds, with the amount actually owed.

    uiAmount already has the mint's scaled multiplier applied by the RPC, so it
    is what the wallet shows. The raw amount is kept because the multiplier can
    change, and a holder who only ever sees the scaled figure cannot tell the
    difference between a price move and a rescale.
    """
    res = rpc("getTokenAccountsByOwner", [owner, {"programId": TOKEN_2022},
                                          {"encoding": "jsonParsed"}], url)
    by_mint = {cfg["mint"]: sym for sym, cfg in tokens.items()}
    out = {}
    for acc in res["value"]:
        info = acc["account"]["data"]["parsed"]["info"]
        sym = by_mint.get(info["mint"])
        if not sym:
            continue
        amt = info["tokenAmount"]
        ui = float(amt.get("uiAmountString") or 0)
        if ui <= 0:
            continue
        prev = out.get(sym, {"ui_amount": 0.0, "raw": 0})
        out[sym] = {"ui_amount": prev["ui_amount"] + ui,
                    "raw": prev["raw"] + int(amt["amount"]),
                    "decimals": amt["decimals"]}
    return out


def issuer_powers(mint, epoch, url=RPC):
    """What the issuer can do to this mint right now, decoded from its extensions."""
    acc = rpc("getAccountInfo", [mint, {"encoding": "jsonParsed"}], url)["value"]
    info = acc["data"]["parsed"]["info"]
    powers = {"mint": mint, "supply_ui": info.get("supply"), "epoch": epoch,
              "transfer_fee_bps": None, "transfer_fee_changes_at_epoch": None,
              "next_transfer_fee_bps": None, "paused": None,
              "permanent_delegate": None, "ui_multiplier": None,
              "freeze_authority": info.get("freezeAuthority")}
    for ext in info.get("extensions", []):
        kind, state = ext.get("extension"), ext.get("state", {})
        if kind == "transferFeeConfig":
            older, newer = state["olderTransferFee"], state["newerTransferFee"]
            in_force = newer if epoch >= newer["epoch"] else older
            powers["transfer_fee_bps"] = in_force["transferFeeBasisPoints"]
            if epoch < newer["epoch"]:
                powers["transfer_fee_changes_at_epoch"] = newer["epoch"]
                powers["next_transfer_fee_bps"] = newer["transferFeeBasisPoints"]
        elif kind == "pausableConfig":
            powers["paused"] = state.get("paused")
        elif kind == "permanentDelegate":
            powers["permanent_delegate"] = state.get("delegate")
        elif kind == "scaledUiAmountConfig":
            # The account keeps the old and the new multiplier side by side, and
            # a timestamp that decides which one is in force. Reading the
            # "multiplier" field alone reports 1x for SpaceX, whose 5x split
            # took effect on 10 June 2026. Anything priced off that is 5x wrong.
            old = float(state.get("multiplier", 1))
            nxt = state.get("newMultiplier")
            effective = state.get("newMultiplierEffectiveTimestamp")
            in_force = old
            if nxt is not None and effective is not None and time.time() >= float(effective):
                in_force = float(nxt)
            powers["ui_multiplier"] = in_force
            if nxt is not None and float(nxt) != in_force:
                powers["next_ui_multiplier"] = float(nxt)
                powers["ui_multiplier_effective"] = effective
    return powers


def current_epoch(url=RPC):
    return rpc("getEpochInfo", [], url)["epoch"]


def cost_to_act(fee_bps):
    """What leaving costs today, as a fraction, before any price impact.

    A sale is one transfer out, so the fee applies once. A holder who converts
    and then sells pays it twice, which is the number that actually bites.
    """
    if fee_bps is None:
        return None
    return {"one_way": fee_bps / 10_000, "round_trip": 2 * fee_bps / 10_000}
