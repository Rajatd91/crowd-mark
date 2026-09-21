"""The Telegram side: watch a wallet, get told when the picture changes.

One process does two things. It answers messages, and every few minutes it
re-reads the markets and the mints and sends an alert when something a holder
would want woken for has actually changed. Usage is logged so the project can
say honestly how many real people used it, rather than claiming an audience.
"""
import json
import os
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

import card as C
import fetch as F
import model as M
import sources as S
import wallet as W

HERE = os.path.dirname(os.path.abspath(__file__))
SUBS = os.path.join(HERE, "subs.json")
STATE = os.path.join(HERE, "state.json")
USAGE = os.path.join(HERE, "usage.jsonl")
CHECK_EVERY = 600          # seconds between market and mint checks

ODDS_MOVE = 0.05           # 5 points of listing probability
GAP_MOVE = 0.05            # 5 points on the gap between token and crowd value


def token():
    for line in open(os.path.join(HERE, ".env")):
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.strip().split("=", 1)[1]
    raise SystemExit("no TELEGRAM_BOT_TOKEN in .env")


API = f"https://api.telegram.org/bot{token()}"


def tg(method, **params):
    url = f"{API}/{method}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": e.read().decode()[:200]}
    except (urllib.error.URLError, TimeoutError) as e:
        return {"ok": False, "error": repr(e)}


def send(chat_id, text):
    return tg("sendMessage", chat_id=chat_id, text=text,
              parse_mode="Markdown", disable_web_page_preview="true")


def load(path, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1)


def log_usage(event, chat_id, extra=None):
    with open(USAGE, "a") as f:
        f.write(json.dumps({"ts": int(time.time()), "event": event,
                            "chat": chat_id, **(extra or {})}) + "\n")


HELP = ("*Crowd Mark* shows what a pre-IPO token is worth against what the crowd "
        "betting on the company thinks, and tells you when the issuer changes the "
        "terms underneath you.\n\n"
        "/card `ANTHROPIC` for any of ANTHROPIC, OPENAI, ANDURIL, NEURALINK\n"
        "/follow `ANTHROPIC` to be told when that token's terms or odds change\n"
        "/watch `<your wallet address>` to follow your own position\n"
        "/status what I am watching for you\n"
        "/stop to stop\n\n"
        "Read only. No wallet connection, nothing to sign, no advice.")


def cards_now(snapshot, epoch):
    out = {}
    for sym, cfg in S.TOKENS.items():
        try:
            c = M.build_card(snapshot, sym, cfg)
            powers = W.issuer_powers(cfg["mint"], epoch)
            out[sym] = (c, powers)
        except Exception:
            traceback.print_exc()
    return out


def handle(update, subs):
    msg = update.get("message") or update.get("edited_message")
    if not msg or "text" not in msg:
        return
    chat = str(msg["chat"]["id"])
    text = msg["text"].strip()
    cmd, _, arg = text.partition(" ")
    cmd, arg = cmd.lower().lstrip("/").split("@")[0], arg.strip()

    if cmd in ("start", "help"):
        log_usage("start", chat)
        send(chat, HELP)
    elif cmd == "watch":
        if not W.looks_like_address(arg):
            send(chat, "Send it as `/watch <address>` with a Solana address, "
                       "for example /watch 7xKX...9yTp")
            return
        snapshot = load(os.path.join(HERE, "data", "latest.json"), None)
        try:
            held = W.holdings(arg, S.TOKENS)
        except Exception:
            send(chat, "Solana did not answer just then. Try again in a moment.")
            return
        sub = subs.get(chat, {})
        sub.update({"wallet": arg, "since": sub.get("since", int(time.time()))})
        subs[chat] = sub
        save(SUBS, subs)
        log_usage("watch", chat, {"wallet": arg, "tokens": list(held)})
        if not held:
            send(chat, "Watching that wallet. It holds none of the four tokens I cover "
                       "right now, so I will stay quiet about it until it does.\n\n"
                       "Meanwhile `/follow ANTHROPIC` and I will tell you when the issuer "
                       "changes that token's terms or the listing odds move. "
                       "`/card ANTHROPIC` shows where it stands today.")
            return
        epoch = W.current_epoch()
        sx = M.spacex_conversion_gap(snapshot, S)
        for sym, pos in held.items():
            c = M.build_card(snapshot, sym, S.TOKENS[sym])
            send(chat, C.render(c, position=pos,
                                powers=W.issuer_powers(S.TOKENS[sym]["mint"], epoch), spacex=sx))
    elif cmd == "card":
        sym = arg.upper()
        if sym not in S.TOKENS:
            send(chat, "I cover ANTHROPIC, OPENAI, ANDURIL and NEURALINK.")
            return
        log_usage("card", chat, {"symbol": sym})
        snapshot = load(os.path.join(HERE, "data", "latest.json"), None)
        c = M.build_card(snapshot, sym, S.TOKENS[sym])
        send(chat, C.render(c, powers=W.issuer_powers(S.TOKENS[sym]["mint"], W.current_epoch()),
                            spacex=M.spacex_conversion_gap(snapshot, S)))
    elif cmd == "follow":
        sym = arg.upper()
        if sym not in S.TOKENS:
            send(chat, "I cover ANTHROPIC, OPENAI, ANDURIL and NEURALINK. "
                       "Send `/follow ANTHROPIC`.")
            return
        sub = subs.get(chat, {"since": int(time.time())})
        following = set(sub.get("follow", []))
        following.add(sym)
        sub["follow"] = sorted(following)
        subs[chat] = sub
        save(SUBS, subs)
        log_usage("follow", chat, {"symbol": sym})
        send(chat, f"Following {sym}. I will message you when the issuer changes its "
                   f"terms, or when the listing odds or the gap to the crowd's value "
                   f"move by five points. Nothing otherwise.")
    elif cmd == "status":
        sub = subs.get(chat)
        if not sub:
            send(chat, "Not watching anything yet. Try `/card ANTHROPIC`.")
        else:
            lines = []
            if sub.get("wallet"):
                lines.append(f"Wallet `{sub['wallet']}`")
            if sub.get("follow"):
                lines.append("Following " + ", ".join(sub["follow"]))
            send(chat, "\n".join(lines) or "Nothing set yet.")
    elif cmd == "stop":
        if subs.pop(chat, None):
            save(SUBS, subs)
            log_usage("stop", chat)
        send(chat, "Stopped. /watch again whenever you like.")


def changes(prev, cards):
    """What changed since the last check, as (symbol, kind, message) tuples."""
    out = []
    for sym, (c, powers) in cards.items():
        old = prev.get(sym, {})
        if old.get("fee_bps") is not None and powers.get("transfer_fee_bps") != old["fee_bps"]:
            out.append((sym, "fee",
                        f"It was {old['fee_bps']/100:.2f}% per transfer, it is now "
                        f"{powers['transfer_fee_bps']/100:.2f}%. On a $1,000 position that is "
                        f"${10*powers['transfer_fee_bps']/100:.2f} to move it."))
        if old.get("paused") is False and powers.get("paused"):
            out.append((sym, "pause", "Transfers are paused. Nobody can move this token until "
                                      "the issuer unpauses it."))
        if old.get("multiplier") and powers.get("ui_multiplier") != old["multiplier"]:
            out.append((sym, "multiplier",
                        f"Your wallet now shows {powers['ui_multiplier']:g} units for every "
                        f"{old['multiplier']:g} before. The position did not change size."))
        if old.get("delegate") != powers.get("permanent_delegate"):
            if old.get("delegate") is not None:
                out.append((sym, "delegate", "The permanent delegate on this mint changed."))
        if c.kind == "ipo" and c.timing and old.get("timing"):
            # Only live markets say anything. One that has settled at 0 or 1, or a
            # date that has passed, moves for reasons a holder does not care about.
            was_by = dict(old["timing"])
            moves = [(abs(p - was_by[label]), label, was_by[label], p)
                     for label, p in c.timing
                     if label in was_by and 0.02 < p < 0.98 and 0.02 < was_by[label] < 0.98]
            if moves:
                size, label, was, now = max(moves)
                if size >= ODDS_MOVE:
                    out.append((sym, "odds",
                                f"Odds of listing by {label} moved from {was:.0%} to {now:.0%}."))
        if c.kind == "ipo" and c.crowd_per_token and old.get("gap") is not None:
            gap = c.crowd_per_token / c.token_price - 1
            if abs(gap - old["gap"]) >= GAP_MOVE:
                out.append((sym, "gap",
                            f"The token was {old['gap']:+.0%} from the crowd's value, "
                            f"it is now {gap:+.0%}."))
    return out


def snapshot_state(cards):
    st = {}
    for sym, (c, powers) in cards.items():
        st[sym] = {"fee_bps": powers.get("transfer_fee_bps"), "paused": powers.get("paused"),
                   "multiplier": powers.get("ui_multiplier"),
                   "delegate": powers.get("permanent_delegate"),
                   "timing": c.timing,
                   "gap": (c.crowd_per_token / c.token_price - 1) if c.crowd_per_token else None}
    return st


def check_and_alert(subs):
    snap = F.snapshot()
    epoch = W.current_epoch()
    cards = cards_now(snap, epoch)
    prev = load(STATE, {})
    fired = changes(prev, cards)
    save(STATE, snapshot_state(cards))
    if not fired or not subs:
        return fired
    for chat, sub in list(subs.items()):
        held = {}
        if sub.get("wallet"):
            try:
                held = W.holdings(sub["wallet"], S.TOKENS)
            except Exception:
                pass
        wanted = set(held) | set(sub.get("follow", []))
        for sym, kind, detail in fired:
            if sym not in wanted:
                continue
            c, _ = cards[sym]
            send(chat, C.render_alert(kind, c, detail))
            log_usage("alert", chat, {"symbol": sym, "kind": kind})
    return fired


def main():
    subs = load(SUBS, {})
    offset, last_check = None, 0
    print(f"crowdmark bot up, {len(subs)} watching", flush=True)
    while True:
        try:
            if time.time() - last_check > CHECK_EVERY:
                last_check = time.time()
                fired = check_and_alert(subs)
                print(f"check done, {len(fired)} change(s)", flush=True)
            r = tg("getUpdates", offset=offset or "", timeout=20)
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                try:
                    handle(u, subs)
                except Exception:
                    traceback.print_exc()
        except Exception:
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()
