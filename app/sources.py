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


# What the companies and the issuer have themselves said about these tokens.
#
# This is the part that decides whether any valuation on this desk means
# anything. A crowd valuation compares a token against what a company might be
# worth, and that comparison only holds if the token is a claim on the company.
# For these tokens that is contested by the companies themselves.
#
# Every entry is a dated, published statement with its source, not an inference
# drawn here. Nothing in this block is computed.
DISCLOSURES = [
    {
        "at": "2026-05-13",
        "severity": "critical",
        "applies_to": ["ANTHROPIC", "OPENAI"],
        "headline": "Both companies say the share transfers behind these tokens are void",
        "detail": ("Anthropic stated that it does not permit special purpose vehicles to "
                   "acquire its stock and that any transfer of shares to an SPV is void "
                   "under its transfer restrictions. Both companies warned that third "
                   "parties selling such exposure are likely either engaged in fraud or "
                   "offering an investment that may have no value. The Anthropic token "
                   "fell 34% and the OpenAI token 39% over the following week."),
        "source": "CoinDesk, 13 May 2026",
        "url": ("https://www.coindesk.com/markets/2026/05/13/"
                "anthropic-openai-tokens-plunge-nearly-40-as-ai-firms-warn-spv-transfers-are-invalid"),
    },
    {
        "at": "2026-05-13",
        "severity": "critical",
        "applies_to": ["ANTHROPIC", "OPENAI"],
        "headline": "The implied value of the tokens vastly exceeds the assets behind them",
        "detail": ("The platform showed an implied Anthropic valuation above $1.3 trillion "
                   "while holding roughly $23 million in total assets, and about $333,000 "
                   "of stablecoins available for Anthropic redemptions. The attestation "
                   "reports that had been promised were never published."),
        "source": "CoinDesk, 13 May 2026",
        "url": ("https://www.coindesk.com/markets/2026/05/13/"
                "anthropic-openai-tokens-plunge-nearly-40-as-ai-firms-warn-spv-transfers-are-invalid"),
    },
    {
        "at": "2027-03-12",
        "severity": "critical",
        "applies_to": ["SPACEX"],
        "headline": "This token expires worthless if it is not swapped in time",
        "detail": ("Conversion is not automatic. PreStocks states that holders must swap "
                   "into the listed stock token before 23:59 UTC on 12 March 2027, and "
                   "that tokens not swapped by then will expire worthless."),
        "source": "PreStocks",
        "url": "https://prestocks.com/spacex",
    },
    {
        "at": "2026-06-12",
        "severity": "context",
        "applies_to": ["SPACEX"],
        "headline": "Its discount to the listed stock is a lockup effect, and it decays",
        "detail": ("SpaceX listed on 12 June 2026 and the token has traded below the "
                   "listed stock since. The issuer attributes this to the underlying "
                   "shares being inside a 180 day staged lockup, which limits liquidity "
                   "and is expected to narrow as shares unlock. The main lockup expires "
                   "on 8 December 2026. So this discount is a temporary illiquidity "
                   "discount on a claim that is not yet deliverable, not evidence about "
                   "what conversion finally pays."),
        "source": "Bitget News, 19 June 2026",
        "url": "https://www.bitget.com/news/detail/12560605468288",
    },
]
