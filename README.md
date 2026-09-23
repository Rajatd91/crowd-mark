# Crowd Mark

**Before you buy a tokenised share in a company that has not listed, find out
what it is actually worth and what it will really cost you.**

Live: **https://rajatd91.github.io/crowd-mark/**

## The problem, and who has it

Eight tokens on Solana claim to represent private companies: Anthropic, OpenAI,
SpaceX, Anduril, Neuralink and others. Tens of thousands of wallets hold them.
Anyone can buy one in about fifteen seconds.

Nobody can tell you whether the price is right.

These companies are private. There is no share price, no exchange, no audited
number. The only figure a buyer gets is the one the issuer publishes, and the
issuer is the party selling the token. A brokerage app would at least show you a
market price. Here there is nothing to compare against.

So people buy blind, and they do not find out until later that a round trip
costs several percent, that the issuer can charge a fee on every transfer and
change it without notice, that it holds a delegate able to move their balance,
and that the one company in this set that has already listed still trades far
below its listed stock.

## What this does about it

One screen, one question, one action.

1. **A verdict.** The token costs one thing. People betting real money on the
   company's listing value price it at another. The difference is stated in
   plain words, with the reasons it might be wrong in the same box rather than
   in a footnote: what a round trip costs, how often the crowd's own odds land
   below today's price, and what the issuer can do to a holder.
2. **A purchase.** Jupiter is asked for a route, your wallet signs and
   broadcasts it. Nothing here touches a key or a balance, and nobody takes a
   fee.
3. **The working, one tab across.** The order books the verdict is built from,
   the fills as they happen, the arithmetic, and a chart of what the crowd has
   said each hour this past week.
4. **A mark on chain.** The same number, published to a Solana program that
   anyone can refresh and anyone can verify.

## Where the second opinion comes from

Prediction markets. On Polymarket, people stake money on what a company's market
cap will be on listing day. That produces a probability distribution made by
people with money at risk and no relationship to the token's issuer.

The model reads that distribution, takes each bracket's midpoint weighted by its
own odds, renormalises over the brackets alone so the chance of no listing is
excluded rather than valued at zero, and divides by the shares the token
implies.

None of this happens on a server. Your browser fetches the markets, runs the
model, and rebuilds the number every time a bet moves it. The websocket pushes
the book as it changes, so the figure at the top of the screen is arithmetic
happening in front of you rather than a value someone stored.

## Measured, modelled, and assumed

Kept apart on purpose, because they are known to different standards.

**Measured.** Every price, order book, fill, round trip cost, transfer fee,
freeze authority, delegate, pool fee income and realised volatility. All read
from Polymarket, Jupiter, PreStocks or Solana itself.

**Modelled, and cited.** The loss a liquidity provider takes to arbitrage, at
the rate Milionis, Moallemi, Roughgarden and Zhang (2022) give for a constant
product pool, raised for a concentrated position by the closed form in their
Example 4. Checked numerically against pool value before use.

**Assumed, and shown.** Exactly one number. Prediction markets leave the top
bracket open ended, so a value has to be put on it. The model picks whichever
market leaves least probability in that bracket, then prints what the answer
would be at 1.1 and 1.5 times its floor so a reader can judge the assumption
instead of trusting it.

## Why it belongs on Solana

These are Token-2022 mints, and the issuer keeps real power over your balance in
the mint itself:

- a transfer fee it can change at an epoch boundary,
- a pause switch on every transfer,
- a permanent delegate that can move a balance,
- a multiplier that silently rescales what every wallet displays.

These powers get used. **On 20 September 2026 the fee on every PreStocks token
doubled from 0.50% to 1.00%**, with no announcement. This project's own hourly
snapshots caught it between 21:02 and 22:02 UTC, which is why the page can show
it as history rather than as a warning.

The SpaceX mint also reports `multiplier: 1` in the obvious field while its 5x
split has been in force since 10 June. Anything reading that field naively is
five times wrong. Only reading the chain catches that.

## The feed is open

Anyone may refresh a mark. The program records who did and how many times it has
been refreshed. A visitor presses a button, their browser reads the markets,
computes the value locally, and their own key signs the transaction.

The rules therefore live in the program rather than in whoever runs it, and they
apply to the keeper exactly as they apply to a stranger. It refuses:

- a symbol that is not plain capitals, or longer than twelve characters,
- a probability above one, or a price of zero,
- a listing value outside the range published with it,
- a reading stamped more than two minutes in the future,
- a reading older than an hour,
- a reading older than the one already stored,

and a mark nobody refreshes reports itself stale after six hours.

Fourteen tests cover the program. One earned its place: it caught a defect where
using a timestamp as the "first publication" sentinel silently disabled the
anti-rewind rule on a chain whose clock reads zero.

## Two copies of the model, held together by a test

The keeper computes in Python, the browser computes in JavaScript, and a mark
published by either must verify against the other. `conformance_model.mjs` runs
both over the same snapshot and compares every field.

That test has already earned its keep. Python rounds halves to even and
JavaScript rounds them away from zero, so a single cent could differ and make an
honest mark look forged. Dates were also being parsed in local time, so the same
mark published from Mumbai and from London would write different numbers.

## Honest limits

- **The crowd prices the company, not the token.** What a token pays on a
  listing depends on conversion terms no market prices. Nothing here is called
  fair value.
- **Four of the eight tokens have no market.** Figure AI and Kalshi have no open
  Polymarket market at all; SpaceX has several, but they ask about launches and
  a merger, not about its valuation. Those screens say so and list what does
  exist rather than leaving a blank.
- **Anthropic states that any transfer of its stock it has not approved is
  void**, and that tokenised exposure may have no value. That sits beside the
  numbers, not buried.
- **The marks are on devnet.** The tokens, the pools and the trading are
  mainnet. Deploying the feed to mainnet is a funding decision, not a technical
  one.
- **The issuer's own mark price cannot be refreshed in the browser**, because
  prestocks.com does not allow browser requests. It comes from the shipped
  snapshot and the page states its age rather than passing it off as current.

## Layout

| Path | What it is |
|---|---|
| `app/site/` | The terminal. `terminal.js` is the shell and screens, `model.js` the valuation, `poly.js` the live wire to Polymarket, `swap.js` the purchase, `commit.js` what a published mark commits to, `chain.js` reading Solana without a library |
| `app/` | The keeper: fetch the sources, compute, publish on chain, rebuild the site, push it |
| `program/` | The Anchor program: one account per company, open to any publisher, and the rules it enforces |
| `collector/` | Hourly snapshots of every PreStocks pool on Meteora, including the fee change |

## Deployed

- Program: `6jsqLJjNynJWc2g1kRNi65wiTCkoUkQ8V3p7MUiBgGgU` on devnet
- Each company's account is derived from its symbol, so there is no registry to
  trust. The Verify screen derives it in your browser and shows the working.

## Running it

```bash
cd app
python3 fetch.py                    # one snapshot of every source
python3 -m unittest test_model      # the maths
node conformance_model.mjs data/latest.json expected.json   # both models agree
node conformance_poly.mjs           # every live endpoint answers a browser
node conformance_terminal.mjs       # every screen renders, in every state
node conformance_chain.mjs          # the chain verifies from the page
python3 publish_site.py             # runs the tests, then stages the site
python3 keeper.py --once            # one full cycle
```

```bash
cd program
cargo build-sbf --tools-version v1.56 --arch v3
cargo test
```

Built for the Stocklana hackathon, September 2026.
