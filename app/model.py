"""Turn a snapshot into the numbers the page shows.

Two rules hold everywhere in this file.

1. Nothing is called fair value. The crowd prices the COMPANY. A PreStocks
   token is exposure to that company through an issuer's holding entity, and
   what it pays on a listing depends on conversion mechanics that no market
   prices. The gap between the two is the thing worth showing, not a verdict.
2. Every assumption that is not read from a market is returned beside the
   number it affects, so the page can print it.
"""
from dataclasses import dataclass, field
import re

TRILLION = 1e12
BILLION = 1e9


# ---------------------------------------------------------------- PreStocks

def token_row(snapshot, symbol):
    for t in snapshot["prestocks"]:
        if t["symbol"] == symbol:
            return t
    raise KeyError(symbol)


def implied_shares(row):
    """Share count PreStocks' own API implies: its valuation divided by its price.

    markValuation / markPrice and impliedValuation / tokenPrice give the same
    count, which is why this is the issuer's number rather than an estimate.
    """
    return row["markValuation"] / row["markPrice"]


def token_implied_value(row):
    """What the token's own price says the whole company is worth."""
    return row["tokenPrice"] * implied_shares(row)


def premium_to_mark(row):
    """Token price against the issuer's mark, as a fraction."""
    return row["tokenPrice"] / row["markPrice"] - 1.0


# ------------------------------------------------------- prediction markets

def _prices(market):
    """Yes price of a Polymarket market. outcomePrices is a JSON string pair."""
    raw = market.get("outcomePrices")
    if isinstance(raw, str):
        import json
        raw = json.loads(raw)
    return float(raw[0])


_RANGE = re.compile(
    r"^\s*(?:(?P<lt><)\s*\$?(?P<upper>[\d.]+)(?P<upper_unit>[TB])"
    r"|\$?(?P<lo>[\d.]+)(?P<lo_unit>[TB])?\s*[–-]\s*\$?(?P<hi>[\d.]+)(?P<hi_unit>[TB])"
    r"|\$?(?P<plus>[\d.]+)(?P<plus_unit>[TB])\s*\+)\s*$", re.I)


def _scale(unit):
    return TRILLION if (unit or "T").upper() == "T" else BILLION


def cap_brackets(event, top_open_end_multiple=1.25):
    """Read an IPO closing market cap event into a distribution.

    Returns (brackets, p_no_ipo, assumptions). Each bracket is
    (low, high, probability) in dollars. The open-ended top bracket has no
    upper bound in the market, so one is assumed and reported.
    """
    brackets, p_no_ipo, assumptions = [], 0.0, []
    for m in event["markets"]:
        title = (m.get("groupItemTitle") or "").strip()
        p = _prices(m)
        if title.lower().startswith("no ipo"):
            p_no_ipo = p
            continue
        g = _RANGE.match(title)
        if not g:
            assumptions.append(f"skipped an unreadable bracket: {title!r}")
            continue
        if g.group("lt"):
            hi = float(g.group("upper")) * _scale(g.group("upper_unit"))
            brackets.append((0.0, hi, p))
        elif g.group("hi"):
            hi_unit = g.group("hi_unit")
            hi = float(g.group("hi")) * _scale(hi_unit)
            lo = float(g.group("lo")) * _scale(g.group("lo_unit") or hi_unit)
            brackets.append((lo, hi, p))
        else:
            lo = float(g.group("plus")) * _scale(g.group("plus_unit"))
            hi = lo * top_open_end_multiple
            brackets.append((lo, hi, p))
            assumptions.append(
                f"the open-ended top bracket ({title}) is valued at "
                f"${hi/TRILLION:.2f}T, that is {top_open_end_multiple:.2f} times its floor")
    brackets.sort()
    return brackets, p_no_ipo, assumptions


def expected_cap(brackets):
    """Crowd expected listing-day market cap, conditional on the listing happening.

    Each bracket contributes its midpoint. Probabilities are renormalised over
    the brackets alone, so the no-listing leg is excluded rather than valued.
    """
    total = sum(p for _, _, p in brackets)
    if total <= 0:
        return None, 0.0
    ev = sum((lo + hi) / 2 * p for lo, hi, p in brackets) / total
    return ev, total


def open_top_mass(event):
    """Probability sitting in the open-ended top bracket of a cap event.

    That bracket is the only one whose value has to be assumed, so the smaller
    this is, the less of the answer is guesswork.
    """
    brackets, _, _ = cap_brackets(event)
    _, total = expected_cap(brackets)
    if not brackets or not total:
        return 1.0
    return brackets[-1][2] / total


def rescale_open_top(brackets, multiple):
    """Same distribution with the open-ended top bracket valued differently."""
    if not brackets:
        return brackets
    *rest, (lo, _hi, p) = brackets
    return rest + [(lo, lo * multiple, p)]


def choose_cap_event(polymarket, cfg):
    """Pick the listing-value market that leaves least to assumption.

    Markets on the same question differ in how finely they cut the top end. The
    one with the least probability in its open-ended bracket is the one whose
    answer is mostly the crowd's rather than ours.
    """
    best = None
    for role, slug in cfg["polymarket"].items():
        if not role.startswith("cap"):
            continue
        ev = polymarket.get(slug)
        if not ev:
            continue
        ev = ev[0] if isinstance(ev, list) else ev
        brackets, p_no, notes = cap_brackets(ev)
        if len(brackets) < 3:
            continue
        mass = open_top_mass(ev)
        if best is None or mass < best[4]:
            best = (slug, brackets, p_no, notes, mass)
    return best


def timing_ladder(event):
    """[(deadline text, probability)] for 'IPO by __' style events, soonest first."""
    out = []
    for m in event["markets"]:
        title = (m.get("groupItemTitle") or "").strip()
        p = _prices(m)
        if p <= 0:
            continue                     # a date already passed without the event
        out.append((title, p))
    return sorted(out, key=lambda x: x[1])


def valuation_ladder(event):
    """[(threshold dollars, probability)] for 'will X's valuation hit __' events.

    These price whether a private valuation REACHES a level by a date, so they
    are a ladder of touch probabilities, not a distribution over an end value.
    Only the upward rungs are returned; downward rungs ask a different question.
    """
    rungs = []
    for m in event["markets"]:
        title = (m.get("groupItemTitle") or "").strip()
        if not title.startswith("↑"):
            continue
        g = re.match(r"^↑\$?([\d.]+)([TB])", title)
        if not g:
            continue
        rungs.append((float(g.group(1)) * _scale(g.group(2)), _prices(m)))
    return sorted(rungs)


def crowd_odds_at(rungs, value):
    """Crowd probability that the valuation reaches the level the token implies.

    Interpolates between the two rungs either side of `value`. Returns None if
    the value sits outside the ladder, since guessing beyond it would invent a
    number the market never made.
    """
    if not rungs or value < rungs[0][0] or value > rungs[-1][0]:
        return None
    for (x0, p0), (x1, p1) in zip(rungs, rungs[1:]):
        if x0 <= value <= x1:
            if x1 == x0:
                return p0
            w = (value - x0) / (x1 - x0)
            return p0 + w * (p1 - p0)
    return None


# ------------------------------------------------------- the SpaceX evidence

def spacex_conversion_gap(snapshot, sources):
    """What conversion is actually paying on the one company that has listed.

    The PreStocks token carries a scaled UI multiplier, so its raw quote must be
    divided by that multiplier before it can be set beside the listed stock token.
    """
    px = snapshot.get("jupiter_price") or {}
    pre = px.get(sources.SPACEX["mint"], {}).get("usdPrice")
    listed = px.get(sources.SPACEX["listed_token"], {}).get("usdPrice")
    if not pre or not listed:
        return None
    return {"prestocks_token_usd": pre, "listed_token_usd": listed,
            "discount": 1.0 - pre / listed}


# ------------------------------------------------------------------ the card

@dataclass
class Card:
    symbol: str
    company: str
    kind: str
    token_price: float
    mark_price: float
    premium_to_mark: float
    shares: float
    token_implied_value: float
    crowd_value: float = None          # expected listing-day cap, IPO tokens only
    crowd_per_token: float = None
    p_listing: float = None            # crowd probability the listing happens at all
    cap_source: str = None
    open_top_mass: float = None
    crowd_value_range: tuple = None
    timing: list = field(default_factory=list)
    ladder: list = field(default_factory=list)   # valuation tokens only
    crowd_odds_at_token_price: float = None
    assumptions: list = field(default_factory=list)


def build_card(snapshot, symbol, cfg):
    row = token_row(snapshot, symbol)
    shares = implied_shares(row)
    card = Card(symbol=symbol, company=cfg["company"], kind=cfg["kind"],
                token_price=row["tokenPrice"], mark_price=row["markPrice"],
                premium_to_mark=premium_to_mark(row), shares=shares,
                token_implied_value=token_implied_value(row))

    pm = snapshot["polymarket"]
    if cfg["kind"] == "ipo":
        chosen = choose_cap_event(pm, cfg)
        if chosen:
            slug, brackets, p_no, notes, open_mass = chosen
            cap, mass = expected_cap(brackets)
            card.crowd_value = cap
            card.crowd_per_token = cap / shares if cap else None
            card.p_listing = mass
            card.cap_source = slug
            card.open_top_mass = open_mass
            # How much the one assumed number moves the answer, so a reader can
            # judge it rather than take it on trust.
            lo = expected_cap(rescale_open_top(brackets, 1.10))[0]
            hi = expected_cap(rescale_open_top(brackets, 1.50))[0]
            card.crowd_value_range = (lo, hi)
            card.assumptions += notes
            if open_mass and open_mass >= 0.10:
                card.assumptions.append(
                    f"{open_mass:.0%} of the crowd's probability sits in that open-ended top "
                    f"bracket, so the value would be {lo/1e12:,.2f}T to {hi/1e12:,.2f}T if it "
                    "were worth 1.1 to 1.5 times its floor instead")
            if p_no:
                card.assumptions.append(
                    f"the crowd puts {p_no:.1%} on no listing in the market's window, "
                    "which is excluded from the value above rather than priced")
        tv = pm.get(cfg["polymarket"].get("timing"))
        if tv:
            card.timing = timing_ladder(tv[0] if isinstance(tv, list) else tv)
    else:
        lv = pm.get(cfg["polymarket"]["ladder"])
        if lv:
            card.ladder = valuation_ladder(lv[0] if isinstance(lv, list) else lv)
            card.crowd_odds_at_token_price = crowd_odds_at(card.ladder, card.token_implied_value)
            card.assumptions.append(
                "these markets price whether the valuation REACHES a level by 31 December, "
                "so they are touch odds, not a distribution over a final value")
    return card
