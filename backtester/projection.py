"""Deterministic forward projection of all four baskets to 2036.

Steps year by year. Each year, in order:
  1. grow every basket by its blended return
  2. apply event value-shocks (e.g. B3 +4% on the 2029 rate cut)
  3. apply event transfers (e.g. move ₹8L B1 -> B3 in 2029)
  4. apply scheduled withdrawals (₹20L liquidity 2028, ₹50L property 2031)

Pure function over config objects — no network, fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import Basket, Event


@dataclass
class ProjectionResult:
    """Yearly basket values and milestone checks."""
    timeline: pd.DataFrame              # index=year, columns=basket ids + 'total'
    withdrawals_made: list[tuple[str, int, str, float]]
    final_values: dict[str, float]      # basket -> value at end_year (post any withdrawals)

    def value_at(self, basket: str, year: int) -> float:
        return float(self.timeline.loc[year, basket])


def project_portfolio(
    baskets: dict[str, Basket],
    events: list[Event],
    withdrawals: list[tuple[str, int, str, float]],
    start_year: int,
    end_year: int,
) -> ProjectionResult:
    """Run the joint projection. Returns a ProjectionResult."""
    ids = list(baskets.keys())
    values = {b: baskets[b].initial for b in ids}
    events_by_year = {e.year: e for e in events}

    rows = []
    # Record the starting (start_year) state before any growth
    rows.append({"year": start_year, **values, "total": sum(values.values())})

    withdrawals_made: list[tuple[str, int, str, float]] = []

    for year in range(start_year + 1, end_year + 1):
        # 1. grow
        for b in ids:
            values[b] *= (1 + baskets[b].blended_return)

        # 2 & 3. events
        ev = events_by_year.get(year)
        if ev:
            for b, shock in ev.value_shocks.items():
                if b in values:
                    values[b] *= shock
            for src, dst, amt in ev.transfers:
                move = min(amt, values.get(src, 0.0))
                values[src] -= move
                values[dst] = values.get(dst, 0.0) + move

        # 4. withdrawals
        for label, wyear, basket, amount in withdrawals:
            if wyear == year:
                taken = min(amount, values.get(basket, 0.0))
                values[basket] -= taken
                withdrawals_made.append((label, year, basket, taken))

        rows.append({"year": year, **{b: values[b] for b in ids}, "total": sum(values.values())})

    timeline = pd.DataFrame(rows).set_index("year")
    return ProjectionResult(
        timeline=timeline,
        withdrawals_made=withdrawals_made,
        final_values={b: float(values[b]) for b in ids},
    )


def cagr(start_value: float, end_value: float, years: int) -> float:
    """Compound annual growth rate."""
    if start_value <= 0 or years <= 0:
        return float("nan")
    return (end_value / start_value) ** (1 / years) - 1


def goal_reconciliation(
    result: ProjectionResult,
    baskets: dict[str, Basket],
) -> pd.DataFrame:
    """Compare each basket's projected value at its target year vs its target.

    For baskets with a withdrawal at/before target (B1, B2), compares the
    withdrawal amount captured; for B3/B4 compares the projected value.
    """
    withdrawal_by_basket = {}
    for label, year, basket, amt in result.withdrawals_made:
        withdrawal_by_basket.setdefault(basket, 0.0)
        withdrawal_by_basket[basket] += amt

    rows = []
    for b, basket in baskets.items():
        ty = basket.target_year
        # value available: if there was a withdrawal, that's what the goal captured;
        # otherwise the projected balance at target year.
        if b in withdrawal_by_basket:
            achieved = withdrawal_by_basket[b]
        else:
            achieved = float(result.timeline.loc[ty, b]) if ty in result.timeline.index else float("nan")
        rows.append({
            "basket": b,
            "name": basket.name,
            "target_year": ty,
            "target": basket.target,
            "achieved": round(achieved, 0),
            "surplus_shortfall": round(achieved - basket.target, 0),
            "met": achieved >= basket.target,
        })
    return pd.DataFrame(rows)
