"""Backtester orchestrator: projection + metrics + tax + Monte Carlo + Excel.

Input priority for what's actually held
---------------------------------------
1. ``--holdings FILE``  : YOUR chosen stocks/bonds + quantities (see portfolio.py
                          and data/holdings_template.csv). Baskets are built from it.
2. ``--picks FILE``     : screener shortlist — used only for the B4 equity metrics;
                          baskets come from config defaults.
3. neither              : pure config defaults.

Usage
-----
    # Backtest the exact instruments you picked
    python -m backtester.run --holdings data/holdings.csv

    # Use the screener shortlist for the B4 equity metrics, config baskets otherwise
    python -m backtester.run --picks data/b4_shortlist.csv

    # Projection + Monte Carlo + tax only (no network / no metrics)
    python -m backtester.run --no-metrics
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
from .portfolio import (
    allocation_table,
    basket_tax_classes,
    build_baskets_from_holdings,
    equity_picks,
    load_holdings,
)
from .projection import cagr, goal_reconciliation, project_portfolio
from .tax import net_of_tax

log = logging.getLogger("backtester")

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run the Singhania four-basket backtester")
    p.add_argument("--holdings", default=os.path.join(_DATA_DIR, "holdings.csv"),
                   help="YOUR holdings CSV (stocks/bonds + quantities). Built into baskets.")
    p.add_argument("--picks", default=os.path.join(_DATA_DIR, "b4_shortlist.csv"),
                   help="screener shortlist CSV (B4 equity metrics only; used if no --holdings)")
    p.add_argument("--no-metrics", action="store_true",
                   help="skip live equity metrics (no yfinance needed)")
    p.add_argument("--sims", type=int, default=1000, help="Monte Carlo paths")
    p.add_argument("--out", default=os.path.join(_DATA_DIR, "singhania_backtest.xlsx"),
                   help="output Excel workbook")
    return p


def resolve_inputs(args):
    """Pick baskets + equity sleeve + per-basket tax classes from the best source.

    Returns (baskets, eq_tickers, eq_weights, tax_classes, source, alloc_df).
    """
    # config defaults
    baskets = config.BASKETS
    tax_classes = {b: ("equity" if b == "B4" else "debt") for b in baskets}
    eq_tickers: list[str] = []
    eq_weights: list[float] = []
    alloc_df = None

    # 1. holdings file (preferred)
    if args.holdings and os.path.exists(args.holdings):
        try:
            holdings = load_holdings(args.holdings)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read holdings %s: %s", args.holdings, exc)
            holdings = pd.DataFrame()
        if not holdings.empty:
            baskets = build_baskets_from_holdings(holdings)
            tax_classes = basket_tax_classes(holdings)
            eq_tickers, eq_weights = equity_picks(holdings)
            alloc_df = allocation_table(holdings, baskets)
            return baskets, eq_tickers, eq_weights, tax_classes, \
                f"holdings:{args.holdings}", alloc_df
        log.warning("holdings file %s has no rows; falling back to screener/defaults",
                    args.holdings)

    # 2. screener picks (equity sleeve only)
    source = "config defaults"
    if args.picks and os.path.exists(args.picks):
        try:
            eq_tickers, eq_weights = load_picks(args.picks)
            source = f"config baskets + screener picks ({args.picks})"
        except Exception as exc:  # noqa: BLE001
            log.warning("could not load picks %s: %s", args.picks, exc)
    return baskets, eq_tickers, eq_weights, tax_classes, source, alloc_df


def run(baskets, eq_tickers, eq_weights, tax_classes, source,
        do_metrics: bool, n_sims: int, out_path: str, alloc_df=None) -> dict:
    print("\n" + "=" * 72)
    print(f"PORTFOLIO SOURCE: {source}")
    print("=" * 72)
    if alloc_df is not None:
        print("DERIVED ALLOCATION (from your holdings)")
        print(alloc_df.to_string(index=False))

    # --- 1. Deterministic projection ---
    proj = project_portfolio(
        baskets, config.EVENTS, config.WITHDRAWALS,
        config.START_YEAR, config.END_YEAR,
    )
    recon = goal_reconciliation(proj, baskets)

    print("\n" + "=" * 72)
    print("DETERMINISTIC PROJECTION → 2036")
    print("=" * 72)
    print(proj.timeline.round(0).to_string())
    print("\nGOAL RECONCILIATION")
    print(recon.to_string(index=False))

    # Overall portfolio CAGR (initial corpus -> final total, capturing withdrawals)
    total_final = proj.timeline.loc[config.END_YEAR, "total"]
    initial_corpus = sum(b.initial for b in baskets.values())
    overall_cagr = cagr(initial_corpus, total_final + sum(w[3] for w in proj.withdrawals_made),
                        config.END_YEAR - config.START_YEAR)
    print(f"\nInitial corpus: ₹{initial_corpus:,.0f}")
    print(f"Overall portfolio CAGR (incl. withdrawals captured): {overall_cagr * 100:.2f}%")

    # --- 2. Tax layer at milestones ---
    print("\n" + "-" * 72)
    print("NET-OF-TAX AT MILESTONES")
    print("-" * 72)
    for label, year, basket, amount in proj.withdrawals_made:
        cls = tax_classes.get(basket, "debt")
        invested = baskets[basket].initial
        res = net_of_tax(invested, amount, cls, held_long_term=True)
        print(f"{label} ({year}, {cls}): gross ₹{res['current_value']:,.0f}  "
              f"tax ₹{res['tax']:,.0f}  net ₹{res['net_value']:,.0f}")
    # B4 exit at 2036
    if "B4" in baskets:
        b4_cls = tax_classes.get("B4", "equity")
        b4_tax = net_of_tax(baskets["B4"].initial, proj.final_values["B4"], b4_cls,
                            held_long_term=True)
        print(f"B4 exit (2036, {b4_cls}): gross ₹{b4_tax['current_value']:,.0f}  "
              f"tax ₹{b4_tax['tax']:,.0f}  net ₹{b4_tax['net_value']:,.0f}")

    # --- 3. Monte Carlo ---
    print("\n" + "-" * 72)
    print(f"MONTE CARLO ({n_sims} paths)")
    print("-" * 72)
    mc = run_monte_carlo(
        baskets, config.EVENTS, config.WITHDRAWALS,
        config.START_YEAR, config.END_YEAR, n_sims=n_sims,
    )
    for b, p in mc.goal_probabilities.items():
        print(f"  {b}: P(goal met) = {p * 100:5.1f}%   "
              f"(target ₹{baskets[b].target:,.0f})")
    print("\nFinal-value percentiles (₹):")
    print(mc.final_value_percentiles.round(0).to_string())

    # --- 4. Equity metrics (live) ---
    metrics_summary = None
    metrics_per_stock = None
    if do_metrics:
        if not eq_tickers:
            print("\n[!] No equity tickers to score (add stocks via --holdings or --picks).")
        else:
            try:
                print("\n" + "-" * 72)
                print(f"EQUITY METRICS  ({len(eq_tickers)} holdings)")
                print("-" * 72)
                m = compute_metrics(eq_tickers, eq_weights)
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
    baskets, eq_tickers, eq_weights, tax_classes, source, alloc_df = resolve_inputs(args)
    run(baskets, eq_tickers, eq_weights, tax_classes, source,
        do_metrics=not args.no_metrics, n_sims=args.sims, out_path=args.out,
        alloc_df=alloc_df)
    return 0


if __name__ == "__main__":
    sys.exit(main())
