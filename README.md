# Crowd Mark

**An on-chain reference price for companies that have not listed.**

Pyth and Chainlink price public stocks. Nothing on Solana prices a private
company, so tokenised claims on Anthropic, OpenAI, Anduril and Neuralink trade
against a mark their own issuer publishes off-chain, or against nothing at all.

Crowd Mark publishes a value derived from markets anyone can check: the
prediction markets where people bet real money on whether, when and at what
value these companies list. Each mark is written to Solana with the time its
sources were read, the slot it landed in, the probability behind it, how much of
it rests on an assumption, and a hash of its inputs.

## What it says today

The token that claims Anthropic exposure prices the company at about **$1.71T**.
The crowd betting on the IPO prices it at about **$2.23T**, with a 54% chance of
listing by 30 November.

The gap looks like free money until you look at the one of these companies that
has already listed. **SpaceX listed on 12 June. Its PreStocks token still trades
about 24% below the listed stock token**, and on-chain it has 10,104 holders, 26
traders in 24 hours and zero organic buyers. Apply that same haircut to Anthropic
and the crowd's $1,358 a token becomes about $1,030, which is roughly where it
trades. That is the honest answer to a question holders keep asking in public.

## Why it belongs on Solana

The tokens are Token-2022 mints whose issuer keeps real power over your balance,
and all of it is readable on-chain:

- a transfer fee it can change at an epoch boundary,
- a pause switch on every transfer,
- a permanent delegate that can move a balance,
- a multiplier that silently rescales what every wallet displays.

These powers get used. **On 20 September the fee on every PreStocks token doubled
from 0.50% to 1.00%** at the epoch 1039 boundary, with no announcement. This
project's own hourly snapshots caught it between 21:02 and 22:02 UTC.

The SpaceX mint reports `multiplier: 1` in the obvious field while its 5x split
has been in force since 10 June. Anything reading that field naively is five
times wrong, which is the sort of thing only on-chain reading catches.

## Layout

| Path | What it is |
|---|---|
| `program/` | The Anchor program: one account per company, an authorised publisher, and the rules it enforces |
| `app/` | The model, the snapshot fetcher, the publisher, the Telegram bot and the web page |
| `collector/` | Hourly snapshots of every PreStocks pool on Meteora, including the fee change |

## Deployed

- Program: `6jsqLJjNynJWc2g1kRNi65wiTCkoUkQ8V3p7MUiBgGgU` (devnet)
- Anthropic mark: `8Trw6Muh5nHYYjKwHcrPP2JuiZjKxvs4nAtbVq1ubxux`
- OpenAI mark: `2DGCpz82X3hbdgLZv5KNMykvGrjJHTubYhRUqcNAwjDw`
- Telegram: [@crowdmark_bot](https://t.me/crowdmark_bot)

## What the program refuses

A feed is only as good as the readings it will not accept:

- anyone other than the configured publisher,
- a probability above one,
- a reading from the future, or older than an hour,
- a value outside the range it states for itself,
- any attempt to replace a mark with an older reading.

Five tests cover these. One of them earned its place: it caught a defect where
using a timestamp as the "first publication" sentinel silently disabled the
anti-rewind rule on a chain whose clock reads zero.

## Honest limits

- **The crowd prices the company, not the token.** What a token pays on a
  listing depends on conversion terms no market prices. The gap between the two
  is the point, and nothing here is called fair value.
- **One number is assumed, and it is shown.** Prediction markets have an
  open-ended top bracket. The model picks whichever market leaves least in it,
  then prints what the answer would be if that bracket were valued differently.
  For Anthropic that assumption moves the answer by under 2%.
- **Anthropic states that transfers of its stock it has not approved are void**,
  and that tokenised exposure may have no value. That appears on the page beside
  the numbers, not buried.
- The feed is on devnet. Marks are published by a keeper, not by a decentralised
  set of publishers.

## Running it

```bash
cd app
python3 fetch.py                 # one snapshot of every source
python3 -m unittest test_model   # the maths, 21 tests
python3 build_site.py            # compute the cards
python3 publish_onchain.py --dry-run
```

```bash
cd program
cargo build-sbf --tools-version v1.56 --arch v3
cargo test                       # the program, 5 tests
```

Built for the Stocklana hackathon, September 2026.
