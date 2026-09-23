"""Headlines for each company, fetched on a schedule and shipped with the page.

The terminal reads the news service directly from the visitor's browser, which
is the honest way round: they see what it says, not what we say it said. But
that service limits how often one address may ask, and a visitor who opens
several companies quickly gets turned away.

So the keeper fetches the same headlines once an hour, slowly enough never to
be refused, and the page ships the result. A visitor sees headlines at once and
the browser refreshes them live on top. If the live call is refused, the shipped
ones stay, with their age shown.

Usage:
    python3 news.py
"""
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
GAP = 8            # seconds between calls, comfortably inside their limit
TRIES = 4
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# The same queries the browser uses, so both sides ask the same question.
QUERY = {
    "ANTHROPIC": '"Anthropic" (IPO OR valuation OR funding OR "public offering")',
    "OPENAI": '"OpenAI" (IPO OR valuation OR funding OR "public offering")',
    "ANDURIL": '"Anduril" (valuation OR funding OR contract OR IPO)',
    "NEURALINK": '"Neuralink" (valuation OR funding OR trial OR IPO)',
    "SPACEX": '"SpaceX" (valuation OR funding OR IPO OR Starlink)',
    "POLYMARKET": '"Polymarket" (valuation OR funding OR regulation)',
    "FIGUREAI": '"Figure AI" (valuation OR funding OR robot)',
    "XAI": '"xAI" (valuation OR funding OR Grok)',
}
NAME = {"ANTHROPIC": "Anthropic", "OPENAI": "OpenAI", "ANDURIL": "Anduril",
        "NEURALINK": "Neuralink", "SPACEX": "SpaceX", "POLYMARKET": "Polymarket",
        "FIGUREAI": "Figure", "XAI": "xAI"}


def fetch(query):
    """One query, retried while the service says it is busy.

    It answers a refusal as plain text rather than as an error status, so the
    body decides whether this worked, not the status code.
    """
    url = (f"{GDELT}?query={urllib.parse.quote(query)}&mode=artlist"
           f"&maxrecords=60&format=json&sort=datedesc&timespan=7d")
    for attempt in range(TRIES):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45) as r:
                body = r.read().decode("utf-8", "replace")
            if body.lstrip().startswith("{"):
                return json.loads(body).get("articles") or []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(GAP * (attempt + 1))
    return None


def parse_stamp(s):
    """Their stamps look like 20260922T233000Z."""
    try:
        return int(time.mktime(time.strptime(s, "%Y%m%dT%H%M%SZ")) - time.timezone)
    except (ValueError, TypeError):
        return None


def tidy(articles, name):
    """One article per headline, and only where the headline names the company.

    A piece that mentions the company in passing is not news about it, and a
    rail full of general artificial intelligence stories would be noise beside
    a price.
    """
    named = re.compile(re.escape(name), re.I)
    seen, out = set(), []
    for a in articles or []:
        title = (a.get("title") or "").strip()
        key = title[:60].lower()
        if not title or not a.get("url") or key in seen or not named.search(title):
            continue
        seen.add(key)
        out.append({
            "title": re.sub(r"\s+", " ", title),
            "url": a["url"],
            "domain": a.get("domain"),
            "image": a.get("socialimage") or None,
            "at": parse_stamp(a.get("seendate")),
        })
    out.sort(key=lambda x: x["at"] or 0, reverse=True)
    return out


def build():
    out, refused = {}, []
    for i, (symbol, query) in enumerate(QUERY.items()):
        if i:
            time.sleep(GAP)
        articles = fetch(query)
        if articles is None:
            refused.append(symbol)
            continue
        out[symbol] = tidy(articles, NAME[symbol])[:12]
        print(f"  {symbol:10} {len(out[symbol]):>2} headlines", flush=True)

    # Anything refused is asked again, once, after a longer wait. Being turned
    # away is not the same as there being no news, and the page would otherwise
    # say so for a whole hour.
    if refused:
        print(f"  waiting, then asking again for {', '.join(refused)}", flush=True)
        time.sleep(GAP * 4)
        still = []
        for symbol in refused:
            articles = fetch(QUERY[symbol])
            if articles is None:
                still.append(symbol)
                continue
            out[symbol] = tidy(articles, NAME[symbol])[:12]
            print(f"  {symbol:10} {len(out[symbol]):>2} headlines on the second ask", flush=True)
            time.sleep(GAP)
        refused = still

    # A run that got nothing must not replace a good file with an empty one.
    path = os.path.join(HERE, "site", "news.json")
    if not out:
        print("  the news service refused every query, keeping what is there")
        return None
    if refused and os.path.exists(path):
        old = json.load(open(path)).get("by_symbol", {})
        for symbol in refused:
            if old.get(symbol):
                out[symbol] = old[symbol]
                print(f"  {symbol:10} kept {len(out[symbol])} from the last run")

    data = {"read_at": int(time.time()), "by_symbol": out,
            "source": "GDELT Project, the global news index",
            "refused": refused}
    with open(path, "w") as f:
        json.dump(data, f, indent=1)
    print(f"news written, {sum(len(v) for v in out.values())} headlines across "
          f"{len(out)} companies")
    return data


if __name__ == "__main__":
    build()
