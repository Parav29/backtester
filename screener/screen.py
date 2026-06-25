"""CLI entry point: screen the Nifty Total Market universe for B4 candidates.

Usage
-----
    python -m screener.screen                 # live yfinance fetch + screen
    python -m screener.screen --no-nse        # skip NSE list, use curated seed
    python -m screener.screen --input data/fundamentals_cache.csv   # offline screen

Outputs
-------
    data/b4_shortlist.csv   ranked shortlist with the metrics that justify each pick
    data/b4_scored.csv      every name that cleared the gates, with scores
    console summary         funnel counts + sector/cap mix

The two "specific current data points" the competition requires per security are
printed for each shortlisted name (its strongest growth/quality metrics).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

import pandas as pd

from .filters import ScreenConfig, run_screen
from .fundamentals import fetch_many
from .universe import load_universe

log = logging.getLogger("screener")

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _pct(x) -> str:
    return "n/a" if pd.isna(x) else f"{x * 100:.1f}%"


def _justification(row: pd.Series) -> str:
    """Two strongest, most decision-relevant data points for a pick."""
    bits = []
    if pd.notna(row.get("revenue_growth")):
        bits.append(f"rev growth {_pct(row['revenue_growth'])}")
    if pd.notna(row.get("earnings_growth")):
        bits.append(f"earnings growth {_pct(row['earnings_growth'])}")
    if pd.notna(row.get("roe")):
        bits.append(f"ROE {_pct(row['roe'])}")
    if pd.notna(row.get("trailing_pe")):
        bits.append(f"P/E {row['trailing_pe']:.1f}")
    if pd.notna(row.get("profit_margin")):
        bits.append(f"margin {_pct(row['profit_margin'])}")
    return "; ".join(bits[:2]) if bits else "insufficient data"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Screen Nifty Total Market for B4 growth candidates")
    p.add_argument("--input", help="CSV of pre-fetched fundamentals (skips network)")
    p.add_argument("--no-nse", action="store_true", help="use curated seed list, skip NSE fetch")
    p.add_argument("--no-cache", action="store_true", help="ignore/skip fundamentals cache")
    p.add_argument("--target-count", type=int, default=12, help="size of final shortlist")
    p.add_argument("--max-per-sector", type=int, default=3, help="diversification cap per sector")
    p.add_argument("--out-dir", default=_DATA_DIR, help="where to write CSV outputs")
    return p


def get_fundamentals(args) -> tuple[pd.DataFrame, list[str], str]:
    if args.input:
        df = pd.read_csv(args.input)
        log.info("loaded %d rows of fundamentals from %s", len(df), args.input)
        return df, [], f"file:{args.input}"
    uni = load_universe(prefer_nse=not args.no_nse)
    df, failed = fetch_many(uni.df, use_cache=not args.no_cache)
    return df, failed, f"yfinance(universe={uni.source})"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)

    df, failed, source = get_fundamentals(args)
    if df.empty:
        log.error(
            "No fundamentals available (source=%s). If every ticker failed, the "
            "data host is likely blocked by network policy -- run on a machine "
            "with open egress to Yahoo Finance, or pass --input with a CSV.",
            source,
        )
        return 1

    cfg = ScreenConfig(target_count=args.target_count, max_per_sector=args.max_per_sector)
    result = run_screen(df, cfg)
    shortlist, summary = result["shortlist"], result["summary"]

    os.makedirs(args.out_dir, exist_ok=True)
    scored_path = os.path.join(args.out_dir, "b4_scored.csv")
    shortlist_path = os.path.join(args.out_dir, "b4_shortlist.csv")
    result["stages"]["scored"].to_csv(scored_path, index=False)
    shortlist.to_csv(shortlist_path, index=False)

    print("\n" + "=" * 72)
    print("B4 SCREEN — Aarya's Growth Pool (Nifty Total Market)")
    print("=" * 72)
    print(f"data source        : {source}")
    if failed:
        print(f"tickers w/o data   : {len(failed)}  ({', '.join(failed[:8])}{'...' if len(failed) > 8 else ''})")
    print(f"funnel             : {summary['n_input']} in "
          f"-> sector {summary['n_after_sector']} "
          f"-> mcap {summary['n_after_market_cap']} "
          f"-> growth {summary['n_after_growth']} "
          f"-> shortlist {summary['n_shortlist']}")
    print(f"sector mix         : {summary['sector_counts']}")
    print(f"cap mix            : {summary['cap_counts']}")
    print("-" * 72)

    if shortlist.empty:
        print("No names cleared the gates. Loosen ScreenConfig thresholds.")
    else:
        cols_present = shortlist.columns
        print(f"{'#':>2}  {'TICKER':<14}{'SECTOR':<13}{'CAP':<6}{'SCORE':>7}  KEY DATA POINTS")
        for _, r in shortlist.iterrows():
            print(f"{int(r['selected_rank']):>2}  {r['ticker']:<14}"
                  f"{str(r['thesis_sector']):<13}{str(r['cap_bucket']):<6}"
                  f"{r['growth_score']:>7.2f}  {_justification(r)}")
    print("-" * 72)
    print(f"wrote: {shortlist_path}")
    print(f"wrote: {scored_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
