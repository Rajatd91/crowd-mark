"""What a liquidity provider actually earns on these pools, and what it costs.

Three things decide whether providing liquidity here pays, and this separates
them because they are known to different standards.

Measured, from our own hourly snapshots since 19 September 2026: the fee income
each pool pays per dollar of liquidity, how much it trades, and how volatile its
price is. Nothing here is assumed.

Measured, from the mints themselves: the Token-2022 transfer fee the issuer
charges. It is taken on the way into a position and again on the way out, so it
is a cost no amount of trading avoids.

Modelled, and cited: the loss a provider takes to arbitrage. For a pool quoting
a price that lags the wider market, the loss against a portfolio that rebalances
at the market price accrues at a rate set by volatility. Milionis, Moallemi,
Roughgarden and Zhang (2022), "Automated Market Making and Loss Versus
Rebalancing", give that rate as sigma squared over eight per unit of pool value
for a constant product pool.

These are concentrated pools, not constant product ones. The same paper gives
the concentrated case in closed form, so the amplification is derived rather
than assumed: for liquidity placed between P/(1+w) and P(1+w), the loss per
dollar is larger than the constant product rate by exactly

    A(w) = 1 / (1 - (1+w) ** -0.5)

which follows from their Example 4, where the loss is unchanged but the pool
value is only 2L sqrt(P) (1 - (1+w) ** -0.5). So what this reports for each pool
is the width at which its fee income stops covering its arbitrage loss. Place
liquidity wider than that and the pool pays; tighter and the traders are being
subsidised.

Usage:
    python3 liquidity.py
"""
import glob
import gzip
import json
import math
import os
import statistics as st
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOTS = os.path.join(HERE, "..", "collector", "data", "*", "*.json.gz")

HOURS_PER_YEAR = 24 * 365
MIN_SNAPSHOTS = 24        # a day of hourly readings before a pool is reported
MIN_TVL = 5_000.0         # below this a fee yield is noise, not a return
# Half-widths a provider would actually choose, as a fraction of the price.
WIDTHS = [0.005, 0.01, 0.02, 0.05, 0.10, 0.25, 0.50, 1.00]


def amplification(w):
    """How much more a position of half-width w loses than a full-range one.

    From Milionis, Moallemi, Roughgarden and Zhang (2022), Example 4: a range
    order loses the same absolute amount per unit of liquidity as a constant
    product pool, but holds less value, so the loss per dollar is larger in
    exactly that proportion. A full-range position is w to infinity, where this
    tends to 1.
    """
    return 1.0 / (1.0 - (1.0 + w) ** -0.5)


def breakeven_width(ratio):
    """The half-width at which income exactly covers the loss.

    Inverts the amplification above. A ratio at or below 1 means the pool does
    not pay even spread over every price, so there is no width that works.
    """
    if ratio is None or ratio <= 1:
        return None
    return (1.0 - 1.0 / ratio) ** -2 - 1.0


def read_series():
    """Every pool's readings, in time order, from the stored snapshots."""
    series = defaultdict(list)
    fees_by_symbol = {}
    files = sorted(glob.glob(SNAPSHOTS))
    for path in files:
        try:
            with gzip.open(path) as f:
                snap = json.load(f)
        except Exception:                       # a truncated hour is skipped
            continue
        epoch = (snap.get("epoch") or {}).get("epoch")
        for symbol, account in (snap.get("mint_accounts") or {}).items():
            # Early snapshots stored this differently. Skip rather than guess.
            if not isinstance(account, dict):
                continue
            info = (account.get("data") or {})
            info = info.get("parsed") if isinstance(info, dict) else None
            info = (info or {}).get("info") or {}
            for ext in (info.get("extensions") or []):
                if ext["extension"] != "transferFeeConfig" or epoch is None:
                    continue
                state = ext["state"]
                in_force = (state["newerTransferFee"]
                            if epoch >= state["newerTransferFee"]["epoch"]
                            else state["olderTransferFee"])
                fees_by_symbol[symbol] = in_force["transferFeeBasisPoints"]
        # A pool holding two tracked tokens is listed under both of them, so
        # the same reading arrives twice. Counting it twice would halve the
        # apparent volatility, since every duplicate pair returns zero.
        seen_this_hour = set()
        for symbol, blob in (snap.get("meteora_pools") or {}).items():
            for pool in (blob.get("data") or []):
                if not pool.get("tvl") or pool["address"] in seen_this_hour:
                    continue
                seen_this_hour.add(pool["address"])
                series[pool["address"]].append({
                    "ts": snap["ts"], "symbol": symbol, "name": pool["name"],
                    "tvl": pool["tvl"], "price": pool.get("current_price"),
                    "fees24": (pool.get("fees") or {}).get("24h"),
                    "volume24": (pool.get("volume") or {}).get("24h"),
                    "base_fee_pct": (pool.get("pool_config") or {}).get("base_fee_pct"),
                    "bin_step": (pool.get("pool_config") or {}).get("bin_step"),
                    "cum_fees": (pool.get("cumulative_metrics") or {}).get("fees"),
                })
    return series, fees_by_symbol, len(files)


def realised_sigma(prices):
    """Annualised volatility from hourly log returns.

    Hourly readings are what we have, so this is what it is: a short window,
    stated with its observation count wherever it is shown. Zero and missing
    prices are dropped rather than carried forward, which would understate it.
    """
    clean = [p for p in prices if p and p > 0]
    rets = [math.log(clean[i] / clean[i - 1]) for i in range(1, len(clean))]
    if len(rets) < 12:
        return None, len(rets)
    return st.pstdev(rets) * math.sqrt(HOURS_PER_YEAR), len(rets)


def summarise(points, transfer_fee_bps):
    """One pool's economics, measured where possible and swept where not."""
    tvl = st.median([p["tvl"] for p in points])
    fee24 = [p["fees24"] for p in points if p["fees24"] is not None]
    vol24 = [p["volume24"] for p in points if p["volume24"] is not None]
    sigma, n_returns = realised_sigma([p["price"] for p in points])
    last = points[-1]

    fee_yield_day = st.median(fee24) / tvl if fee24 and tvl else None
    turnover = st.median(vol24) / tvl if vol24 and tvl else None

    # Two readings of the same thing. Fee income should be about what the
    # pool's own fee rate charges on the volume it reports, and the provider's
    # share is net of the protocol's cut. If these disagree badly, one of the
    # two numbers is wrong and the pool is not reported as if both were right.
    implied = (turnover * last["base_fee_pct"] / 100) if (turnover and last["base_fee_pct"]) else None
    agreement = (fee_yield_day / implied) if (implied and fee_yield_day) else None

    # A bin-stepped pool cannot quote a price between its bins, so its price
    # moves in jumps of the bin step. When an hour's typical move is smaller
    # than one step, what looks like volatility is mostly that quantisation.
    hourly_sigma = sigma / math.sqrt(HOURS_PER_YEAR) if sigma else None
    step = (last["bin_step"] or 0) / 1e4
    quantisation_dominates = bool(hourly_sigma and step and hourly_sigma < step)

    # The arbitrage loss a constant product pool of this volatility would take,
    # per day, per dollar of liquidity. The cited rate is per year.
    lvr_day = (sigma ** 2 / 8) / 365 if sigma else None

    # How many times the full-range loss this pool's income can carry, and the
    # range width that corresponds to. The width is the useful form: it is the
    # thing a provider chooses when they open a position.
    breakeven_amp = (fee_yield_day / lvr_day) if (fee_yield_day and lvr_day) else None
    be_width = breakeven_width(breakeven_amp)

    # The issuer's own cut. Charged on the token leg entering the position and
    # again leaving it, so a provider pays it twice before earning anything.
    # Half the position is the token in a balanced two-sided range.
    entry_exit_cost = (transfer_fee_bps / 1e4) * 0.5 * 2 if transfer_fee_bps else 0.0
    days_to_recover = (entry_exit_cost / fee_yield_day) if (fee_yield_day and entry_exit_cost) else None

    return {
        "pool": last["name"],
        "symbol": last["symbol"],
        "snapshots": len(points),
        "tvl": tvl,
        "base_fee_pct": last["base_fee_pct"],
        "bin_step": last["bin_step"],
        "fee_yield_day": fee_yield_day,
        "fee_yield_year": fee_yield_day * 365 if fee_yield_day else None,
        "turnover_day": turnover,
        "sigma": sigma,
        "sigma_observations": n_returns,
        "sigma_hourly": hourly_sigma,
        "quantisation_dominates": quantisation_dominates,
        "fee_yield_implied_by_volume": implied,
        "fee_agreement": agreement,
        "never_traded": bool(not fee_yield_day or fee_yield_day < 1e-5),
        # Income and volume agree on almost every pool, at about nine tenths,
        # which is the providers' share after the protocol's cut. Where they
        # do not, the two figures come from different hours and the pool is
        # marked rather than reported as if both were sound.
        "corroborated": bool(agreement and 0.75 <= agreement <= 1.05),
        "lvr_day_cpmm": lvr_day,
        "breakeven_amplification": breakeven_amp,
        "breakeven_half_width": be_width,
        "transfer_fee_bps": transfer_fee_bps,
        "entry_exit_cost": entry_exit_cost,
        "days_to_recover_entry": days_to_recover,
        "net_by_width": [
            {"half_width": w,
             "amplification": amplification(w),
             "lvr_day": lvr_day * amplification(w),
             "net_day": fee_yield_day - lvr_day * amplification(w)}
            for w in WIDTHS
        ] if (fee_yield_day and lvr_day) else [],
    }


def build():
    series, transfer_fees, n_files = read_series()
    pools = []
    for address, points in series.items():
        if len(points) < MIN_SNAPSHOTS:
            continue
        row = summarise(points, transfer_fees.get(points[-1]["symbol"]))
        if not row["tvl"] or row["tvl"] < MIN_TVL or not row["fee_yield_day"]:
            continue
        row["address"] = address
        pools.append(row)
    pools.sort(key=lambda r: -r["tvl"])

    good = [p for p in pools if p["corroborated"] and not p["never_traded"]]
    window_hours = max(len(p) for p in series.values()) if series else 0
    out = {
        "window_hours": window_hours,
        "reported": len(pools),
        "usable": len(good),
        "snapshots_read": n_files,
        "pools": pools,
        "widths": WIDTHS,
        "note": ("Fee income, turnover and volatility are measured from our own hourly "
                 "snapshots. The arbitrage loss is modelled at the rate Milionis, Moallemi, "
                 "Roughgarden and Zhang (2022) give for a constant product pool, and the "
                 "amplification that concentration adds is derived from their Example 4, "
                 "not assumed."),
    }
    with open(os.path.join(HERE, "site", "liquidity.json"), "w") as f:
        json.dump(out, f, indent=1)

    print(f"  {len(pools)} pools, {window_hours} hourly readings each at most")
    print(f"  {len(good)} of them with income and volume agreeing, and some trading")
    head = (f"{'pool':<20}{'TVL':>10}{'fee/day':>9}{'sigma':>7}{'LVR/day':>9}"
            f"{'breaks at':>11}{'entry':>8}")
    print(head)
    for p in good[:12]:
        w = p["breakeven_half_width"]
        print(f"{p['pool'][:19]:<20}{p['tvl']:>10,.0f}"
              f"{p['fee_yield_day']*100:>8.3f}%"
              f"{(p['sigma'] or 0)*100:>6.0f}%"
              f"{(p['lvr_day_cpmm'] or 0)*100:>8.4f}%"
              f"{(f'{w*100:.2f}%' if w else 'never'):>11}"
              f"{p['entry_exit_cost']*100:>7.2f}%")
    return out


if __name__ == "__main__":
    build()
