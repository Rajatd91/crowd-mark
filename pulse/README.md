# Crowd Mark

**What is a private company really worth? Ask the people betting real money on it.**

Crowd Mark turns live prediction-market odds into a valuation range and an IPO
timeline for the biggest private companies, then shows what that means for a
person's own shares or options.

Live: https://rajatd91.github.io/crowd-mark/pulse/

## What it does that others don't

Prediction markets already publish odds like "OpenAI's listing value will be
$1.75T to $2T: 18%". On their own those are a list of bets. Crowd Mark:

1. **Turns brackets into a valuation.** The bracket prices become a full
   distribution, so you get an expected value, a median and an 80% range, and
   every assumption (open-ended top and bottom brackets, the chance of no
   listing) is stated on the page with its effect on the answer.
2. **Turns dated markets into a timeline.** "IPO by June?", "IPO by December?"
   become one curve of the chance of listing by each date, cleaned so it never
   falls over time, with the month it becomes more likely than not.
3. **Keeps different questions apart.** Markets on whether a valuation
   *reaches* a level are touch odds, not a forecast of one number. They are
   shown as a ladder and never averaged into a fake point estimate.
4. **Applies it to you.** Enter an ownership percentage, or shares or options
   with a strike, plus expected dilution. Your stake runs through the whole
   distribution: likely value at listing, the 80% range, the chance it clears a
   figure you have in mind, and the chance options end up under water.
   Nothing typed leaves the page.

Search finds markets for any other company and analyses whatever they price.

## How it is built

No server and no build step. The visitor's browser reads Polymarket directly,
so numbers are never older than the page. If Polymarket cannot be reached the
page shows a stored snapshot and says how old it is.

| File | What it is |
|---|---|
| `js/crowd.js` | The valuation engine: distributions, quantiles, timelines, ladders, your stake. Pure functions. |
| `js/markets.js` | Live reads from Polymarket, with the snapshot fallback |
| `js/companies.js` | Which markets price which company |
| `js/charts.js` | Hand-drawn SVG charts |
| `js/app.js` | Pages: board, company, equity, search, method |
| `js/config.js` | The alerts sign-up endpoint and links |
| `build.py` | Publishes to `docs/pulse` with a fresh snapshot |
| `test/crowd.test.mjs` | Tests for every calculation |

```bash
node --test pulse/test/crowd.test.mjs   # the maths
python3 pulse/build.py                  # publish to docs/pulse
cd docs && python3 -m http.server       # then open http://localhost:8000/pulse/
```

The hourly keeper (`app/publish_site.py`) rebuilds it, so the fallback snapshot
stays as fresh as the latest fetch.

## Adding a company

Find its Polymarket event slugs (the part after `polymarket.com/event/`) and add
an entry to `js/companies.js`: `timing` for an "IPO by ...?" event, `caps` for
listing-value brackets, or `ladder` for "valuation reaches ... by ..." events.
Then add the same slugs to `EXTRA_POLYMARKET` in `app/sources.py`, so the
hourly keeper fetches them and the fallback snapshot covers them too. The live
page works without that step; only the fallback needs it.

## Turning on alerts

Create a free form endpoint (Formspree, Buttondown, Tally or similar) that
accepts a POST with an `email` field, and paste its URL into `SIGNUP_ENDPOINT`
in `js/config.js`. Until then the page says alerts are coming soon rather than
collecting addresses it has nowhere to send.

## Limits, stated plainly

- Coverage is only as wide as the markets: a company appears once someone bets
  on what it is worth.
- Thin markets can be wrong or moved by a few large bets. Every page shows how
  much money is behind the numbers.
- A listing value is not today's private-sale price, and a stake's value at
  listing is before tax, liquidation preferences, lockups and vesting.
- Not investment advice.
