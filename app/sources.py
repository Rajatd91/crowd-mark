"""Which public markets price each PreStocks company.

Every entry names a real, open market. Nothing here is inferred: the slugs and
tickers were read from the providers' own APIs on 20 Sep 2026.
"""

# PreStocks tokens this project covers. The rest of the eight have no crowd market.
TOKENS = {
    "ANTHROPIC": {
        "mint": "Pren1FvFX6J3E4kXhJuCiAD5aDmGEb7qJRncwA8Lkhw",
        "company": "Anthropic",
        "kind": "ipo",                       # crowd prices an IPO: timing plus listing-day value
        "polymarket": {
            "timing": "anthropic-ipo-by",
            "month": "in-which-month-will-anthropic-ipo",
            # Several markets price the listing value. The model picks whichever
            # leaves least in its open-ended top bracket, since that bracket is
            # the only part it has to assume a value for.
            "cap_a": "what-will-anthropics-ipo-valuation-be",
            "cap_b": "anthropic-ipo-closing-market-cap-higher-strikes",
            "cap_c": "anthropic-ipo-closing-market-cap-119",
        },
        "kalshi_series": "KXIPOANTHROPIC",   # "When will Anthropic officially announce an IPO?"
    },
    "OPENAI": {
        "mint": "PreweJYECqtQwBtpxHL171nL2K6umo692gTm7Q3rpgF",
        "company": "OpenAI",
        "kind": "ipo",
        "polymarket": {
            "timing": "openai-ipo-by",
            "cap_a": "what-will-openais-ipo-valuation-be",
            "cap_b": "openai-ipo-closing-market-cap-554",
            # Deliberately not the 2026-dated market: it prices a listing that
            # will almost certainly not happen in its window, so its brackets
            # describe a scenario nobody is really betting on.
        },
        "kalshi_series": "KXIPOOPENAI",
    },
    "ANDURIL": {
        "mint": "PresTj4Yc2bAR197Er7wz4UUKSfqt6FryBEdAriBoQB",
        "company": "Anduril",
        "kind": "valuation",                 # crowd prices the private valuation, not an IPO
        "polymarket": {"ladder": "will-andurils-valuation-hit-by-december-31"},
        "kalshi_series": "KXIPOANDURIL",
    },
    "NEURALINK": {
        "mint": "PrekqLJvJ3qVdXmBGDiexvwUTF4rLFDa6HWS4HJbw9S",
        "company": "Neuralink",
        "kind": "valuation",
        "polymarket": {"ladder": "will-neuralinks-valuation-hit-by-december-31"},
        "kalshi_series": None,
    },
}

PRESTOCKS_API = "https://prestocks.com/api/prestocks"
PRESTOCKS_METRICS = "https://prestocks.com/api/metrics"
POLYMARKET_EVENT = "https://gamma-api.polymarket.com/events?slug={slug}"
KALSHI_EVENTS = ("https://api.elections.kalshi.com/trade-api/v2/events"
                 "?series_ticker={series}&with_nested_markets=true")
JUPITER_PRICE = "https://lite-api.jup.ag/price/v3?ids={ids}"
JUPITER_TOKENS = "https://lite-api.jup.ag/tokens/v2/search?query={ids}"

# The SpaceX case: the only PreStocks token whose company has already listed.
# Used to measure what conversion actually paid, rather than assuming it.
SPACEX = {
    "mint": "PreANxuXjsy2pvisWWMNB6YaJNzr7681wJJr2rHsfTh",
    "listed_token": "Xs3oZwbHvqis4NYcf4YKWmEia2eC84wSiVrcYcTqpH8",   # SPCXx, the listed stock token
    "ui_multiplier": 5.0,        # Token-2022 scaled UI amount on the PreStocks mint
    "listed_on": "2026-06-12",
    "swap_deadline": "2027-03-12T23:59:00Z",
}
