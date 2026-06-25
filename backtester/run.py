"""Backtester orchestrator: projection + metrics + tax + Monte Carlo + Excel.

Usage
-----
    # Full run (metrics need live yfinance for the B4 picks)
    python -m backtester.run --picks data/b4_shortlist.csv

    # Skip the live equity-metrics step (projection + MC + tax only)
    python -m backtester.run --no-metrics

    # Choose output workbook
    python -m backtester.run --picks data/b4_shortlist.csv --out data/singhania_backtest.xlsx
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import pandas as pd

from . import config
from .excel_export import export_workbook
from .metrics import compute_metrics, format_metrics, load_picks
from .montecarlo import run_monte_carlo
from .projection import cagr, goal_reconciliation, project_portfolio
from .tax import net_of_tax

log = logging.getLogger("backtester")

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the Singhania four-basket backtester")
    p.add_argument("--picks", default=os.path.join(_DATA_DIR, "b4_shortlist.csv"),
                   help="B4 picks CSV (ticker + optional weight/allocation_pct)")
    p.add_argument("--no-metrics", action="store_true",
                   help="skip live equity metrics (no yfinance needed)")
    p.add_argument("--sims", type=int, default=1000, help="Monte Carlo paths")
    p.add_argument("--out", default=os.path.join(_DATA_DIR, "singhania_backtest.xlsx"),
                   help="output Excel workbook")
    return p


def run(picks_path: str, do_metrics: bool, n_sims: int, out_path: str) -> dict:
    # --- 1. Deterministic projection ---
    proj = project_portfolio(
        config.BASKETS, config.EVENTS, config.WITHDRAWALS,
        config.START_YEAR, config.END_YEAR,
    )
    recon = goal_reconciliation(proj, config.BASKETS)

    print("\n" + "=" * 72)
    print("DETERMINISTIC PROJECTION → 2036")
    print("=" * 72)
    print(proj.timeline.round(0).to_string())
    print("\nGOAL RECONCILIATION")
    print(recon.to_string(index=False))

    # Overall portfolio CAGR (initial corpus -> final total, ignoring withdrawals out)
    total_final = proj.timeline.loc[config.END_YEAR, "total"]
    overall_cagr = cagr(config.TOTAL_CORPUS, total_final + sum(w[3] for w in proj.withdrawals_made),
                        config.END_YEAR - config.START_YEAR)
    print(f"\nOverall portfolio CAGR (incl. withdrawals captured): {overall_cagr * 100:.2f}%")

    # --- 2. Tax layer at milestones ---
    print("\n" + "-" * 72)
    print("NET-OF-TAX AT MILESTONES")
    print("-" * 72)
    for label, year, basket, amount in proj.withdrawals_made:
        cls = "debt"  # B1/B2 are debt instruments
        invested = config.BASKETS[basket].initial
        res = net_of_tax(invested, amount, cls, held_long_term=True)
        print(f"{label} ({year}): gross ₹{res['current_value']:,.0f}  "
              f"tax ₹{res['tax']:,.0f}  net ₹{res['net_value']:,.0f}")
    # B4 equity exit at 2036 (LTCG)
    b4_final = proj.final_values["B4"]
    b4_tax = net_of_tax(config.BASKETS["B4"].initial, b4_final, "equity", held_long_term=True)
    print(f"B4 equity exit (2036): gross ₹{b4_tax['current_value']:,.0f}  "
          f"LTCG tax ₹{b4_tax['tax']:,.0f}  net ₹{b4_tax['net_value']:,.0f}")

    # --- 3. Monte Carlo ---
    print("\n" + "-" * 72)
    print(f"MONTE CARLO ({n_sims} paths)")
    print("-" * 72)
    mc = run_monte_carlo(
        config.BASKETS, config.EVENTS, config.WITHDRAWALS,
        config.START_YEAR, config.END_YEAR, n_sims=n_sims,
    )
    for b, p in mc.goal_probabilities.items():
        print(f"  {b}: P(goal met) = {p * 100:5.1f}%   "
              f"(target ₹{config.BASKETS[b].target:,.0f})")
    print("\nFinal-value percentiles (₹):")
    print(mc.final_value_percentiles.round(0).to_string())

    # --- 4. Equity metrics (live) ---
    metrics_summary = None
    metrics_per_stock = None
    if do_metrics:
        try:
            tickers, weights = load_picks(picks_path)
            print("\n" + "-" * 72)
            print(f"B4 EQUITY METRICS  ({len(tickers)} picks from {picks_path})")
            print("-" * 72)
            m = compute_metrics(tickers, weights)
            print(format_metrics(m))
            metrics_summary = {
                "Portfolio Return": round(m.portfolio_return, 4),
                "Portfolio Std Dev": round(m.portfolio_std, 4),
                "Portfolio Beta": round(m.portfolio_beta, 4),
                "Sharpe Ratio": round(m.sharpe_ratio, 4),
                "Treynor Ratio": round(m.treynor_ratio, 4),
                "Jensen's Alpha": round(m.jensen_alpha, 4),
                "Max Drawdown": round(m.max_drawdown, 4),
            }
            metrics_per_stock = pd.DataFrame([
                {"ticker": t, "beta": round(m.individual_betas.get(t, float("nan")), 3),
                 "annual_return": round(m.annualised_returns.get(t, float("nan")), 4)}
                for t in m.tickers
            ])
        except Exception as exc:  # noqa: BLE001
            log.warning("Equity metrics skipped: %s", exc)
            print(f"\n[!] Equity metrics unavailable ({exc}).")
            print("    Run on a machine with open egress to Yahoo Finance.")

    # --- 5. Excel export ---
    out = export_workbook(
        out_path,
        projection_timeline=proj.timeline.round(0),
        goal_recon=recon,
        metrics_summary=metrics_summary,
        metrics_per_stock=metrics_per_stock,
        monte_carlo=mc.goal_probabilities,
        mc_percentiles=mc.final_value_percentiles.round(0),
    )
    print(f"\n→ wrote workbook: {out}")
    return {"projection": proj, "reconciliation": recon, "monte_carlo": mc}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    run(args.picks, do_metrics=not args.no_metrics, n_sims=args.sims, out_path=args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
