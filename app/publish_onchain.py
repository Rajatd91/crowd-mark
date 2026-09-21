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
import hashlib
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
MARK_SEED = b"mark"


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


def sources_hash(token, read_at):
    """A hash of the inputs behind a mark, so a reader can check it later."""
    material = json.dumps({
        "read_at": read_at,
        "cap_source": token.get("cap_source"),
        "token_price": token["token_price"],
        "mark_price": token["mark_price"],
        "crowd_value": token["crowd_value"],
        "brackets": token.get("brackets"),
        "timing": token.get("timing"),
        "ladder": token.get("ladder"),
    }, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(material).digest()


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
            return int(time.mktime(time.strptime(label, fmt))), to_bps(p)
        except ValueError:
            continue
    return 0, to_bps(p)


def publish_args(symbol, token, read_at):
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
        + sources_hash(token, read_at)
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
            data=publish_args(symbol, token, read_at),
            accounts=[
                AccountMeta(keypair.pubkey(), is_signer=True, is_writable=True),
                AccountMeta(config, is_signer=False, is_writable=True),
                AccountMeta(mark, is_signer=False, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            ],
        )
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
    await client.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
