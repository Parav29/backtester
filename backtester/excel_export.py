"""Export backtester outputs to a structured Excel workbook for judges.

Sheets:
  Allocation        — four-basket allocation table
  Projection        — yearly values to 2036
  GoalReconciliation— target vs achieved per basket
  B4Metrics         — Beta/Sharpe/Treynor/Jensen + per-stock betas (if available)
  MonteCarlo        — goal probabilities + percentile bands (if available)
  Assumptions       — every assumption used, for the mandatory Assumptions Sheet
"""

from __future__ import annotations

import pandas as pd

from . import config


def _autosize(ws):
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(width + 2, 50)


def export_workbook(
    path: str,
    projection_timeline: pd.DataFrame,
    goal_recon: pd.DataFrame,
    metrics_summary: dict | None = None,
    metrics_per_stock: pd.DataFrame | None = None,
    monte_carlo: dict | None = None,
    mc_percentiles: pd.DataFrame | None = None,
) -> str:
    """Write all outputs to an .xlsx. Returns the path."""
    with pd.ExcelWriter(path, engine="openpyxl") as xl:
        # Allocation
        alloc = pd.DataFrame([
            {"basket": b, "name": bk.name, "purpose": bk.purpose,
             "initial_INR": bk.initial, "target_INR": bk.target,
             "target_year": bk.target_year,
             "assumed_return_%": round(bk.blended_return * 100, 2)}
            for b, bk in config.BASKETS.items()
        ])
        alloc.to_excel(xl, sheet_name="Allocation", index=False)

        projection_timeline.to_excel(xl, sheet_name="Projection")
        goal_recon.to_excel(xl, sheet_name="GoalReconciliation", index=False)

        if metrics_summary:
            pd.DataFrame([metrics_summary]).T.rename(columns={0: "value"}).to_excel(
                xl, sheet_name="B4Metrics")
        if metrics_per_stock is not None and not metrics_per_stock.empty:
            metrics_per_stock.to_excel(xl, sheet_name="B4Metrics",
                                       startrow=len(metrics_summary or {}) + 3 if metrics_summary else 0)

        if monte_carlo:
            mc_df = pd.DataFrame([
                {"basket": b, "P(goal met)": p} for b, p in monte_carlo.items()
            ])
            mc_df.to_excel(xl, sheet_name="MonteCarlo", index=False)
        if mc_percentiles is not None and not mc_percentiles.empty:
            mc_percentiles.to_excel(xl, sheet_name="MonteCarlo",
                                    startrow=(len(monte_carlo) + 3) if monte_carlo else 0)

        # Assumptions sheet
        assumptions = pd.DataFrame([
            ("Risk-free rate (Rf)", f"{config.RF * 100:.2f}%", "competition-mandated"),
            ("Market return (Rm)", f"{config.RM * 100:.2f}%", "competition-mandated (10Y Nifty 50)"),
            ("Large-cap return", f"{config.LARGE_CAP_RETURN * 100:.1f}%", "competition baseline"),
            ("Mid/small-cap return", f"{config.MIDSMALL_CAP_RETURN * 100:.1f}%", "competition baseline"),
            ("G-Sec return", f"{config.GSEC_RETURN * 100:.1f}%", "competition baseline"),
            ("AAA bond return", f"{config.AAA_BOND_RETURN * 100:.1f}%", "competition baseline"),
            ("Gold return", f"{config.GOLD_RETURN * 100:.1f}%", "competition baseline"),
            ("REIT/InvIT return", f"{config.REIT_INVIT_RETURN * 100:.1f}%", "competition baseline"),
            ("Equity LTCG", f"{config.LTCG_EQUITY * 100:.1f}% > ₹1.25L", ">1yr holding"),
            ("Equity STCG", f"{config.STCG_EQUITY * 100:.1f}%", "<1yr holding"),
            ("Debt/G-Sec tax", f"{config.DEBT_TAX_RATE * 100:.0f}%", "slab rate (assumed)"),
            ("SGB maturity tax", "0%", "tax-exempt for individuals"),
            ("Rebalancing years", ", ".join(map(str, config.REBALANCE_YEARS)), "event points only"),
            ("Horizon", f"{config.START_YEAR}–{config.END_YEAR}", "10-year"),
            ("MC vol (large-cap)", f"{config.VOL_LARGE_CAP * 100:.0f}%", "assumed, not mandated"),
            ("MC vol (mid/small)", f"{config.VOL_MIDSMALL_CAP * 100:.0f}%", "assumed, not mandated"),
        ], columns=["assumption", "value", "note"])
        assumptions.to_excel(xl, sheet_name="Assumptions", index=False)

    # autosize
    from openpyxl import load_workbook
    wb = load_workbook(path)
    for ws in wb.worksheets:
        _autosize(ws)
    wb.save(path)
    return path
