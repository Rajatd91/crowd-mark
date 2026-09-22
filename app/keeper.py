"""Keep the on-chain marks fresh.

Once an hour: read the markets, recompute, and publish. A mark older than six
hours reports itself stale, so a feed nobody refreshes is worse than no feed.

Usage:
    python3 keeper.py --once
    python3 keeper.py            # hourly, until stopped
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEVNET = None


def devnet_rpc():
    """The keyed devnet endpoint, taken from the same file as everything else."""
    global DEVNET
    if DEVNET:
        return DEVNET
    for line in open(os.path.join(HERE, ".env")):
        if line.startswith("SOLANA_RPC="):
            DEVNET = line.strip().split("=", 1)[1].replace("mainnet", "devnet")
            return DEVNET
    return "https://api.devnet.solana.com"


def run(label, args, env=None):
    out = subprocess.run(args, cwd=HERE, capture_output=True, text=True,
                         env={**os.environ, **(env or {})})
    tail = (out.stdout or out.stderr).strip().split("\n")[-1][:160]
    print(f"  {label}: {'ok' if out.returncode == 0 else 'FAILED'}  {tail}", flush=True)
    return out.returncode == 0


def cycle():
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"{stamp} keeper cycle", flush=True)
    if not run("read markets", [sys.executable, "fetch.py"]):
        return False
    if not run("publish", [sys.executable, "publish_onchain.py"],
               env={"PUBLISH_RPC": devnet_rpc()}):
        return False
    if not run("read back", [sys.executable, "read_onchain.py"]):
        return False
    # The page ships the same reading the chain now holds, so a visitor can
    # verify a mark without waiting for the next build.
    if not run("rebuild the desk", [sys.executable, "desk.py"]):
        return False
    return run("stage the site", [sys.executable, "publish_site.py"])


def main():
    once = "--once" in sys.argv
    while True:
        try:
            cycle()
        except Exception as e:  # noqa: BLE001 - a bad hour must not end the feed
            print(f"  cycle failed {e!r}", flush=True)
        if once:
            return 0
        time.sleep(3600 - (time.time() % 3600))


if __name__ == "__main__":
    sys.exit(main())
