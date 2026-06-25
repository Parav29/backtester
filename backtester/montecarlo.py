"""Monte Carlo simulation of the four baskets to 2036.

Each basket grows with a random annual return ~ Normal(blended_return, vol).
Events (shocks/transfers) and withdrawals apply exactly as in the deterministic
projection. We run N paths and report the probability each goal is met.

This is a simplification (annual i.i.d. normal returns, independent baskets) —
flagged in the Assumptions Sheet. It answers "how robust is the plan to return
variability", not "what's the true joint distribution of Indian asset returns".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Basket, Event


@dataclass
class MonteCarloResult:
    n_sims: int
    goal_probabilities: dict[str, float]       # basket -> P(meet target)
    final_value_percentiles: pd.DataFrame      # basket -> p5/p25/p50/p75/p95
    total_percentiles: dict[str, float]


def run_monte_carlo(
    baskets: dict[str, Basket],
    events: list[Event],
    withdrawals: list[tuple[str, int, str, float]],
    start_year: int,
    end_year: int,
    n_sims: int = 1000,
    seed: int | None = 42,
) -> MonteCarloResult:
    rng = np.random.default_rng(seed)
    events_by_year = {e.year: e for e in events}
    ids = list(baskets.keys())

    # For goal probability we track, per sim, whether each basket met its target
    # at its target year. For B1/B2 the target is the withdrawal amount, so we
    # check the value just before withdrawal; for B3/B4 the end value.
    withdrawal_baskets = {w[2]: (w[1], w[3]) for w in withdrawals}

    finals = {b: np.zeros(n_sims) for b in ids}
    met_counts = {b: 0 for b in ids}
    totals = np.zeros(n_sims)

    for i in range(n_sims):
        # Track pre-withdrawal value for withdrawal baskets
        values = {b: baskets[b].initial for b in ids}
        pre_withdrawal_val = {}
        for year in range(start_year + 1, end_year + 1):
            for b in ids:
                r = rng.normal(baskets[b].blended_return, baskets[b].blended_vol)
                values[b] *= (1 + r)
            ev = events_by_year.get(year)
            if ev:
                for b, shock in ev.value_shocks.items():
                    if b in values:
                        values[b] *= shock
                for src, dst, amt in ev.transfers:
                    move = min(amt, values.get(src, 0.0))
                    values[src] -= move
                    values[dst] = values.get(dst, 0.0) + move
            for _label, wyear, basket, amount in withdrawals:
                if wyear == year:
                    pre_withdrawal_val[basket] = values.get(basket, 0.0)
                    values[basket] -= min(amount, values.get(basket, 0.0))

        for b in ids:
            finals[b][i] = values[b]
            target = baskets[b].target
            if b in withdrawal_baskets:
                wyear, wamt = withdrawal_baskets[b]
                achieved = pre_withdrawal_val.get(b, values[b])
                if achieved >= target:
                    met_counts[b] += 1
            else:
                if values[b] >= target:
                    met_counts[b] += 1
        totals[i] = sum(values[b] for b in ids)

    goal_prob = {b: met_counts[b] / n_sims for b in ids}
    pct_rows = []
    for b in ids:
        pct_rows.append({
            "basket": b,
            "p5": np.percentile(finals[b], 5),
            "p25": np.percentile(finals[b], 25),
            "p50": np.percentile(finals[b], 50),
            "p75": np.percentile(finals[b], 75),
            "p95": np.percentile(finals[b], 95),
        })
    total_pct = {
        "p5": float(np.percentile(totals, 5)),
        "p50": float(np.percentile(totals, 50)),
        "p95": float(np.percentile(totals, 95)),
    }

    return MonteCarloResult(
        n_sims=n_sims,
        goal_probabilities=goal_prob,
        final_value_percentiles=pd.DataFrame(pct_rows).set_index("basket"),
        total_percentiles=total_pct,
    )
