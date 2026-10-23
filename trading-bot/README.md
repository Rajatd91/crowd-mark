# trendbot

A trading bot for a personal portfolio: diversified trend following across ETFs,
sized by volatility. It comes with a backtest that tries hard not to flatter it,
and a live runner that refuses to trade when something looks wrong.

It is not a money machine. Nothing here has been shown to make money on real
data yet: it was built and tested on simulated prices, because the build machine
had no market data access. **Run the research on real data yourself before
deciding anything**, and read the report as evidence, not as a promise.

## What the strategy does

Once a week, after Friday's close:

1. For each ETF, measure its trend over about 1, 3, 6 and 12 months, each
   scaled by how volatile it is, and average them into a score from -1 to 1.
2. Hold the ones trending up, each sized inversely to its volatility, so a
   bond fund and an equity fund carry similar risk.
3. Scale the whole portfolio so its expected volatility is 10% a year, using
   the assets' correlations, with no more than 25% in one fund and no leverage.
   Whatever is not invested stays in cash.
4. On Monday, trade only the funds whose weight changed by more than 5 points.

Why this strategy: trend following on diversified futures and ETFs is one of
the best-documented effects in finance, over more than a century of data
(Moskowitz, Ooi & Pedersen 2012; Hurst, Ooi & Pedersen 2017). It is also widely
known, so the edge is modest, and it has long flat or losing stretches,
for example in choppy years like 2011–2012 and 2016. Its main appeal for a
personal account is that it tends to step aside during long sell-offs such as
2008, which buy-and-hold does not.

## How the backtest avoids fooling you

| Trap | What the code does |
|---|---|
| Look-ahead bias | Decisions use data up to day t's close; trades fill at day t+1's open. Tests change future prices and check that no earlier decision moves, and were confirmed to fail when a look-ahead bug was planted. |
| Ignoring costs | Commission per order, slippage on every fill, whole shares, cash never below zero. The report repeats everything at 2x and 3x costs. |
| Dividends and splits | Prices are adjusted, including the open, so neither looks like a gain or loss. |
| Overfitting | 17 variants are run and all of them are counted. The Deflated Sharpe Ratio says how likely the edge is real after allowing for that many tries. |
| In-sample optimism | Walk-forward: each year, the variant that did best over the previous five years is chosen and only its result in the following, unseen year is kept. |
| Luck | Block-bootstrap 95% interval for the Sharpe ratio, plus the probability the true Sharpe is above zero. |
| No baseline | Buy-and-hold and an equal-weight portfolio run through the same engine and costs. |

## Live safety

The runner computes target weights from the last *completed* daily bar, compares
them with what the account holds, and plans orders. Before sending anything it
refuses if:

- the kill switch is set (`python -m trendbot stop`),
- prices are more than 4 business days old,
- any price moved more than 25% in a day (likely a data error),
- equity fell more than 3% since the last close,
- any single order is above 30% of equity, or there are too many orders,
- a target weight breaks the caps,
- the market is closed (for a real broker),
- it already rebalanced this week.

It sends marketable limit orders (0.5% through the last price), sells before
buys, and logs every run to `state/journal.jsonl`. Running it twice does not
double the trades. Optional Telegram messages if `TELEGRAM_BOT_TOKEN` and
`TELEGRAM_CHAT_ID` are set.

Real money needs all three of: `broker.allow_live = true` in the config,
`--execute` and `--live` on the command line. It then waits 10 seconds before
sending anything.

## Using it

```bash
cd trading-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.toml config.toml

python -m pytest -q                                  # 30+ tests, all on simulated data
python -m trendbot backtest --config config.toml     # one run, real data from Yahoo
python -m trendbot research --config config.toml     # the full report, saved in reports/
python -m trendbot signal   --config config.toml     # what it would hold today
python -m trendbot rebalance --config config.toml             # dry run: shows orders
python -m trendbot rebalance --config config.toml --execute   # paper account in state/
```

`--data synthetic` runs anything without internet.

## Suggested path to real money

1. **Research.** Run `research` on real data. Read `reports/report.md`. Go no
   further if, after costs, it does not beat buy-and-hold on risk-adjusted terms
   (Sharpe, maximum drawdown), the walk-forward result is much worse than the
   full-sample one, or the deflated Sharpe is well below 90%.
2. **Paper trade for at least 3 months.** Run `rebalance --execute` each Monday
   with the local paper broker, or an Alpaca paper account. Compare what it did
   with what the backtest says it should have done over the same weeks.
3. **Small and real.** Only then, with money you can afford to lose entirely,
   and with your broker's real fees in the config. Keep `max_daily_loss` and the
   kill switch on.

## Things to know before trading it in the UK

- **US ETFs:** UK retail accounts usually cannot buy US-listed ETFs such as SPY.
  `config.example.toml` lists London-listed UCITS equivalents. Check each one,
  and its currency, with your broker.
- **Broker:** the code talks to Alpaca, which mainly serves US accounts; check
  whether it accepts yours. Interactive Brokers is the usual UK choice for API
  trading; an adapter for it is not included yet, and `broker.py` shows the four
  methods one needs.
- **Fees on a small account:** at £1–3 per order, weekly trading in ten funds
  costs a noticeable share of a £10,000 account. The report shows this as
  `cost_drag_per_year`. Monthly rebalancing or a wider band reduces it.
- **Tax:** the backtest ignores tax. An ISA avoids capital gains tax on gains;
  outside one, frequent rebalancing creates taxable disposals.
- **Not advice.** This is a research and learning tool. Past performance,
  simulated or real, does not predict future returns.

## Layout

| File | What it is |
|---|---|
| `trendbot/config.py` | Every setting, with defaults and validation |
| `trendbot/data.py` | Yahoo, CSV and synthetic prices; cleaning and alignment |
| `trendbot/strategy.py` | Trend scores, volatility, covariance, target weights |
| `trendbot/backtest.py` | Share-level accounting engine with costs |
| `trendbot/metrics.py` | Performance, bootstrap, probabilistic and deflated Sharpe |
| `trendbot/research.py` | Benchmarks, cost stress, grid, walk-forward, report |
| `trendbot/risk.py` | Pre-trade checks |
| `trendbot/broker.py` | Paper broker and Alpaca |
| `trendbot/live.py` | Scheduling, order planning, the guarded rebalance |
| `tests/` | Look-ahead, accounting, costs, caps, metrics and live-safety tests |

## Known limitations

- Walk-forward switches variants without charging the cost of moving from one
  variant's portfolio to the next, so it is slightly optimistic.
- A position in a fund with no price that day cannot be exited until it trades.
- Cash earns nothing in the backtest, which understates returns when rates are high.
- Yahoo data is free and usually good, but not guaranteed: the price checks exist
  for that reason.
