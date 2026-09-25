"""Render one holding as the message a holder reads.

The order is deliberate. What you hold, then what the token says the company is
worth, then what the crowd says, then what actually happened the last time one
of these companies listed, then what the issuer can still do to you. A number
without its source is not printed.
"""
import datetime as dt

import model as M


def money(x):
    if x is None:
        return "n/a"
    if abs(x) >= 1e12:
        return f"${x/1e12:,.2f}T"
    if abs(x) >= 1e9:
        return f"${x/1e9:,.0f}B"
    return f"${x:,.2f}"


def pct(x, signed=True):
    if x is None:
        return "n/a"
    return f"{x:+.1%}" if signed else f"{x:.0%}"


def render(card, position=None, powers=None, spacex=None, when=None):
    """Plain text for Telegram. position is the holder's amount, if watched."""
    L = []
    L.append(f"*{card.company}* ({card.symbol})")
    L.append(f"Token {money(card.token_price)} against the issuer's mark "
             f"{money(card.mark_price)} ({pct(card.premium_to_mark)})")

    if position:
        L.append(f"You hold {position['ui_amount']:,.4f} "
                 f"worth about {money(position['ui_amount'] * card.token_price)}")

    L.append("")
    L.append(f"The token price values {card.company} at {money(card.token_implied_value)}")

    if card.kind == "ipo" and card.crowd_per_token:
        gap = card.crowd_per_token / card.token_price - 1
        L.append(f"The crowd expects {money(card.crowd_value)} on listing day, "
                 f"which is {money(card.crowd_per_token)} per token ({pct(gap)})")
        if card.timing:
            near = [t for t in card.timing if t[1] >= 0.2][:2]
            if near:
                L.append("Listing odds: " + ", ".join(f"{p:.0%} by {t}" for t, p in near))
    elif card.ladder:
        if card.crowd_odds_at_token_price is not None:
            L.append(f"The crowd gives {card.crowd_odds_at_token_price:.0%} odds that "
                     f"{card.company} even reaches that valuation by 31 December")
        rungs = ", ".join(f"{money(v)} {p:.0%}" for v, p in card.ladder[-3:])
        L.append(f"Odds of reaching: {rungs}")

    if spacex and card.kind == "ipo":
        L.append("")
        L.append(f"The one that has listed: SpaceX tokens still trade "
                 f"{spacex['discount']:.0%} below the listed stock token, "
                 f"{(dt.date(2026, 9, 21) - dt.date(2026, 6, 12)).days} days after the IPO. "
                 f"At that discount this would be "
                 f"{money((card.crowd_per_token or 0) * (1 - spacex['discount']))} per token.")

    if powers:
        L.append("")
        bits = []
        if powers.get("transfer_fee_bps") is not None:
            bits.append(f"charge {powers['transfer_fee_bps']/100:.2f}% on every transfer")
        if powers.get("next_transfer_fee_bps") is not None:
            bits.append(f"raise it to {powers['next_transfer_fee_bps']/100:.2f}% "
                        f"at epoch {powers['transfer_fee_changes_at_epoch']}")
        if powers.get("paused"):
            bits.append("transfers are PAUSED right now")
        elif powers.get("paused") is False:
            bits.append("pause all transfers")
        if powers.get("permanent_delegate"):
            bits.append("move your balance through a permanent delegate")
        if powers.get("ui_multiplier") and powers["ui_multiplier"] != 1:
            bits.append(f"your balance is displayed at {powers['ui_multiplier']:g}x "
                        f"after a split")
        if bits:
            L.append("The issuer can: " + "; ".join(bits) + ".")

    if card.assumptions:
        L.append("")
        L.append("_" + card.assumptions[0] + "_")

    L.append("")
    L.append(f"Read {when or dt.datetime.now(dt.timezone.utc).strftime('%d %b %H:%M UTC')}. "
             "Prices from Jupiter and PreStocks, odds from Polymarket and Kalshi, "
             "balances and issuer powers from Solana. Information only, not advice.")
    return "\n".join(L)


def render_alert(kind, card, detail):
    """One short message per change worth waking someone for."""
    head = {
        "scheduled": "The issuer has scheduled a change",
        "fee": "The issuer changed the transfer fee",
        "pause": "The issuer paused transfers",
        "multiplier": "Your displayed balance was rescaled",
        "odds": "The listing odds moved",
        "gap": "The gap to the crowd's value moved",
        "delegate": "The issuer changed who can move your balance",
    }[kind]
    return f"*{head}* for {card.company} ({card.symbol})\n{detail}"
