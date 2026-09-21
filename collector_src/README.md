# PreStocks pool collector

Hourly, read-only snapshots of the 35 PreStocks Meteora DLMM pools with at least $1k TVL, started 19 Sep 2026 so the transfer-fee change at Solana epoch 1039 (0.5% to 1.0%, due about Sun 20 Sep 21:13 UTC) can be compared before and after.

Each snapshot in `data/<date>/<HHMM>.json.gz` (UTC) holds raw, undecoded:
- PreStocks API and metrics (mark and token prices, holders)
- each mint's Token-2022 state (transfer fee, UI multiplier, pause flag) and the Solana epoch
- Jupiter prices
- Meteora's API records for every pool holding a PreStocks token
- on-chain LbPair account and bin arrays for each tracked pool

`tracked_pools.json` is the tracked set. Once a pool is tracked it stays tracked.

Check it is running:

    tail collector.log
    ps -p $(cat collector.pid)

Stop it:

    kill $(cat collector.pid)

Keep the laptop plugged in with the lid open. `caffeinate -s` only prevents sleep on mains power.
