"""Read the marks back off Solana, and check they match what was computed.

Publishing is only half of it. This reads each account from the chain, decodes
it, and compares it with the model's own output, so a mismatch shows up here
rather than on the page.

It also writes site/onchain.json, which is what the page falls back to if a
visitor's browser cannot reach an RPC endpoint.
"""
import asyncio
import datetime as dt
import json
import os
import struct
import sys

from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

import publish_onchain as P

HERE = os.path.dirname(os.path.abspath(__file__))
STALE_AFTER_HOURS = 6        # the same limit the program states


def decode_mark(data):
    """Unpack one Mark account, in the order the program declares its fields."""
    o = 8                                  # skip Anchor's account discriminator

    def string():
        nonlocal o
        n = struct.unpack_from("<I", data, o)[0]
        o += 4
        value = data[o:o + n].decode()
        o += n
        return value

    symbol, company = string(), string()
    kind, = struct.unpack_from("<B", data, o); o += 1
    token_price, token_implied, crowd, low, high, per_token = struct.unpack_from("<QQQQQQ", data, o); o += 48
    p_event, open_top = struct.unpack_from("<HH", data, o); o += 4
    deadline, = struct.unpack_from("<q", data, o); o += 8
    deadline_bps, = struct.unpack_from("<H", data, o); o += 2
    read_at, published_at, slot = struct.unpack_from("<qqQ", data, o); o += 24
    sources_hash = data[o:o + 32].hex()

    return {
        "symbol": symbol, "company": company, "kind": kind,
        "token_price": token_price / 1e6,
        "token_implied_value": token_implied / 1e2,
        "crowd_value": crowd / 1e2,
        "crowd_low": low / 1e2, "crowd_high": high / 1e2,
        "crowd_per_token": per_token / 1e6,
        "p_event": p_event / 1e4, "open_top_mass": open_top / 1e4,
        "next_deadline": deadline, "next_deadline_p": deadline_bps / 1e4,
        "source_read_at": read_at, "published_at": published_at, "slot": slot,
        "sources_hash": sources_hash,
    }


def devnet_rpc():
    for line in open(os.path.join(HERE, ".env")):
        if line.startswith("SOLANA_RPC="):
            return line.strip().split("=", 1)[1].replace("mainnet", "devnet")
    return "https://api.devnet.solana.com"


async def main():
    client = AsyncClient(devnet_rpc(), commitment=Confirmed)
    computed = json.load(open(os.path.join(HERE, "site", "data.json")))
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    out, problems = {}, []

    for symbol in computed["tokens"]:
        pda, _ = Pubkey.find_program_address([P.MARK_SEED, symbol.encode()], P.PROGRAM_ID)
        account = (await client.get_account_info(pda, commitment=Confirmed)).value
        if account is None:
            problems.append(f"{symbol} has no account on chain yet")
            continue
        mark = decode_mark(bytes(account.data))
        mark["account"] = str(pda)
        mark["age_hours"] = round((now - mark["published_at"]) / 3600, 2)
        mark["stale"] = mark["age_hours"] > STALE_AFTER_HOURS
        out[symbol] = mark

        # The chain is the record. If it disagrees with the model, say so here.
        want = computed["tokens"][symbol]
        if abs(mark["token_price"] - want["token_price"]) > 0.01:
            problems.append(f"{symbol} price on chain {mark['token_price']} "
                            f"vs computed {want['token_price']}")
        if mark["stale"]:
            problems.append(f"{symbol} is {mark['age_hours']}h old, past the "
                            f"{STALE_AFTER_HOURS}h limit the program states")

    out["_meta"] = {"program": str(P.PROGRAM_ID), "cluster": "devnet",
                    "read_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
    with open(os.path.join(HERE, "site", "onchain.json"), "w") as f:
        json.dump(out, f, indent=1)

    for p in problems:
        print(f"  problem {p}")
    fresh = sum(1 for k, v in out.items() if k != "_meta" and not v["stale"])
    print(f"  {fresh} of {len(out) - 1} marks fresh on devnet")
    await client.close()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
