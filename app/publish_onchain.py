"""Publish each company's mark to the Solana feed.

The model computes the numbers off-chain from public markets. This puts them
where nobody can quietly edit them afterwards: an account per company, stamped
with the reading time, the slot, and a hash of the inputs.

Money is converted to fixed units here, once, so rounding happens in one place:
company values in whole cents, per-token prices in millionths of a dollar.

Usage:
    python3 publish_onchain.py --dry-run      # show what would be sent
    python3 publish_onchain.py                # sign and send
"""
import argparse
import asyncio
import calendar
import hashlib
import math
import json
import os
import struct
import sys
import time

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.transaction import Transaction
from solana.rpc.async_api import AsyncClient

import build_site
import sources as S

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM_ID = Pubkey.from_string("6jsqLJjNynJWc2g1kRNi65wiTCkoUkQ8V3p7MUiBgGgU")
CONFIG_SEED = b"config"
MARK_SEED = b"mark.v2"


def discriminator(name):
    """Anchor's instruction tag: the first eight bytes of sha256("global:name")."""
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


def borsh_string(text):
    raw = text.encode()
    return struct.pack("<I", len(raw)) + raw


def to_cents(dollars):
    """Whole cents, rounded half up. Values above u64 are refused, not wrapped."""
    if dollars is None:
        return 0
    cents = int(round(dollars * 100))
    if not 0 <= cents < 2**64:
        raise ValueError(f"{dollars} does not fit in u64 cents")
    return cents


def to_micro(dollars):
    """Millionths of a dollar, for per-token prices."""
    if dollars is None:
        return 0
    micro = int(round(dollars * 1_000_000))
    if not 0 <= micro < 2**64:
        raise ValueError(f"{dollars} does not fit in u64 micro-dollars")
    return micro


def to_bps(fraction):
    """Basis points, clamped to the scale the program accepts."""
    if fraction is None:
        return 0
    return max(0, min(10_000, int(round(fraction * 10_000))))


def hash_material(symbol, token, read_at, snapshot_at):
    """The exact bytes the published hash commits to.

    Written as integers joined by separators rather than as JSON, because two
    languages must produce this identically: the keeper in Python and the page
    in JavaScript, which disagree about how to print floats and how to order
    nested keys. Money becomes millionths or cents, probabilities become basis
    points, and nothing here is a float.

    Two times appear. `read_at` is when the publisher read the crowd. The
    `snapshot_at` is when the issuer's own figures were read, which a browser
    cannot fetch for itself, so a mark says plainly how old that part is
    instead of letting a fresh timestamp cover a stale price.
    """
    def half_up(x, scale):
        """Round half away from zero, as JavaScript's Math.round does.

        Python rounds halves to even, so 2.5 becomes 2 here and 3 in the
        browser. Every value below is non-negative, so adding a half and
        taking the floor reproduces the browser exactly. One disagreement in
        the last cent would change the hash and make an honest mark look
        forged.
        """
        return str(math.floor((x or 0) * scale + 0.5))

    def micro(x):
        return half_up(x, 1_000_000)

    def cents(x):
        return half_up(x, 100)

    def bps(x):
        return half_up(x, 10_000)

    brackets = ",".join(f"{cents(b['low'])}:{cents(b['high'])}:{bps(b['p'])}"
                        for b in (token.get("brackets") or []))
    timing = ",".join(f"{label}={bps(p)}" for label, p in (token.get("timing") or []))
    ladder = ",".join(f"{cents(v)}={bps(p)}" for v, p in (token.get("ladder") or []))
    return "|".join([
        "crowdmark.v3",
        symbol,
        str(read_at),
        str(snapshot_at),
        token.get("cap_source") or "",
        micro(token["token_price"]),
        micro(token["mark_price"]),
        cents(token.get("crowd_value")),
        brackets,
        timing,
        ladder,
    ])


def sources_hash(symbol, token, read_at, snapshot_at):
    """The 32 bytes the account stores, over exactly the material above.

    A visitor recomputes this in the browser from the same public sources. If
    it matches what is on chain, the mark was made from those numbers and
    nothing else, whoever pressed publish.
    """
    return hashlib.sha256(hash_material(symbol, token, read_at, snapshot_at).encode()).digest()


def next_deadline(token, read_at):
    """The nearest deadline the crowd still prices, with its probability.

    Settled markets say nothing, so anything at the extremes is skipped.
    """
    live = [(label, p) for label, p in (token.get("timing") or []) if 0.02 < p < 0.98]
    if not live:
        return 0, 0
    label, p = max(live, key=lambda x: x[1])
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            # UTC, not local time. The browser can publish the same mark from
            # any timezone, and both must write the same number.
            return calendar.timegm(time.strptime(label, fmt)), to_bps(p)
        except ValueError:
            continue
    return 0, to_bps(p)


def publish_args(symbol, token, read_at, snapshot_at):
    """Borsh-encoded arguments, in the order the program declares them."""
    deadline, deadline_bps = next_deadline(token, read_at)
    low, high = token.get("crowd_value_range") or (token["crowd_value"], token["crowd_value"])
    body = (
        borsh_string(token["company"])
        + struct.pack("<B", 0 if token["kind"] == "ipo" else 1)
        + struct.pack("<Q", to_micro(token["token_price"]))
        + struct.pack("<Q", to_cents(token["token_implied_value"]))
        + struct.pack("<Q", to_cents(token["crowd_value"]))
        + struct.pack("<Q", to_cents(low))
        + struct.pack("<Q", to_cents(high))
        + struct.pack("<Q", to_micro(token["crowd_per_token"]))
        + struct.pack("<H", to_bps(token.get("p_listing")))
        + struct.pack("<H", to_bps(token.get("open_top_mass")))
        + struct.pack("<q", deadline)
        + struct.pack("<H", deadline_bps)
        + struct.pack("<q", read_at)
        + sources_hash(symbol, token, read_at, snapshot_at)
    )
    return discriminator("publish") + borsh_string(symbol) + body


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=os.environ.get("PUBLISH_RPC", "http://127.0.0.1:8899"))
    ap.add_argument("--keypair", default=os.path.expanduser("~/.config/solana/id.json"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    data = build_site.build()                      # recompute from the latest snapshot
    read_at = int(time.mktime(time.strptime(data["read_at"][:19], "%Y-%m-%dT%H:%M:%S")))
    read_at -= time.timezone if not time.daylight else time.altzone

    proofs = {}
    keypair = Keypair.from_bytes(bytes(json.load(open(args.keypair))))
    client = AsyncClient(args.rpc)
    config, _ = Pubkey.find_program_address([CONFIG_SEED], PROGRAM_ID)

    for symbol, token in data["tokens"].items():
        if token["kind"] == "ipo" and not token.get("crowd_per_token"):
            print(f"{symbol}: no crowd value to publish, skipped")
            continue
        mark, _ = Pubkey.find_program_address([MARK_SEED, symbol.encode()], PROGRAM_ID)
        ix = Instruction(
            program_id=PROGRAM_ID,
            data=publish_args(symbol, token, read_at, read_at),
            accounts=[
                AccountMeta(keypair.pubkey(), is_signer=True, is_writable=True),
                AccountMeta(config, is_signer=False, is_writable=True),
                AccountMeta(mark, is_signer=False, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            ],
        )
        # The keeper reads both halves in the same run, so the two times agree.
        proofs[symbol] = {"material": hash_material(symbol, token, read_at, read_at),
                          "sha256": sources_hash(symbol, token, read_at, read_at).hex(),
                          "account": str(mark)}
        if args.dry_run:
            print(f"{symbol:10} -> {mark}  "
                  f"crowd {to_cents(token['crowd_value'])/1e14:.2f}T  "
                  f"{len(ix.data)} bytes")
            continue
        blockhash = (await client.get_latest_blockhash()).value.blockhash
        tx = Transaction([keypair], Message.new_with_blockhash(
            [ix], keypair.pubkey(), blockhash), blockhash)
        sig = (await client.send_transaction(tx)).value
        print(f"{symbol:10} published in {sig}")
    with open(os.path.join(HERE, "site", "proofs.json"), "w") as f:
        json.dump({"read_at": read_at, "proofs": proofs}, f, indent=1)
    await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
