"""Filtering and scoring logic for the B4 (Aarya's Growth Pool) screen.

These are pure functions over a fundamentals DataFrame -- no network, no I/O --
so they can be unit-tested directly. The pipeline is:

    assign_cap_buckets -> filter_by_sector -> filter_by_market_cap
        -> filter_by_growth -> score_growth -> select_balanced

Thresholds live in ``ScreenConfig`` so judges can see exactly what was applied
and so the values can be tuned in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# SEBI classifies large/mid/small by *rank* (top 100 / 101-250 / 251+) rather
# than absolute market cap, but rank data needs the full universe. As a robust
# proxy we use absolute INR-crore cutoffs aligned to the AMFI Jun-2026-ish
# boundaries. Override in ScreenConfig if AMFI revises them.
LARGE_CAP_MIN_CR = 67_000.0   # >= this -> large cap
MID_CAP_MIN_CR = 20_000.0     # [MID, LARGE) -> mid cap; below -> small cap


@dataclass
class ScreenConfig:
    # Universe / sector
    allowed_sectors: tuple[str, ...] = (
        "Consumption", "Financials", "Industrials",
        "Defence", "Digital", "Healthcare",
    )
    # Market-cap gates (INR crore)
    large_cap_min_cr: float = LARGE_CAP_MIN_CR
    mid_cap_min_cr: float = MID_CAP_MIN_CR
    min_market_cap_cr: float = 5_000.0   # drop micro-caps below this

    # Growth gates (fractions: 0.10 == 10%). A name must clear at least
    # `min_growth_criteria_met` of the non-null gates to pass.
    min_revenue_growth: float = 0.10
    min_earnings_growth: float = 0.10
    min_roe: float = 0.13
    min_growth_criteria_met: int = 2

    # Quality / valuation guardrails (growth, not value -- so these are loose)
    max_debt_to_equity: float | None = 2.0   # exclude over-levered names; None disables
    max_trailing_pe: float | None = 120.0    # sanity cap on extreme multiples; None disables

    # Scoring weights (relative; need not sum to 1)
    weights: dict = field(default_factory=lambda: {
        "revenue_growth": 0.30,
        "earnings_growth": 0.30,
        "roe": 0.25,
        "profit_margin": 0.15,
    })

    # Final selection
    target_count: int = 12          # how many names to shortlist for B4
    max_per_sector: int = 3         # diversification cap


def assign_cap_buckets(df: pd.DataFrame, cfg: ScreenConfig) -> pd.DataFrame:
    df = df.copy()

    def bucket(mc):
        if pd.isna(mc):
            return None
        if mc >= cfg.large_cap_min_cr:
            return "large"
        if mc >= cfg.mid_cap_min_cr:
            return "mid"
        return "small"

    df["cap_bucket"] = df["market_cap_cr"].apply(bucket)
    return df


def filter_by_sector(df: pd.DataFrame, cfg: ScreenConfig) -> pd.DataFrame:
    return df[df["thesis_sector"].isin(cfg.allowed_sectors)].copy()


def filter_by_market_cap(df: pd.DataFrame, cfg: ScreenConfig) -> pd.DataFrame:
    return df[df["market_cap_cr"].fillna(0) >= cfg.min_market_cap_cr].copy()


def _count_growth_criteria(row: pd.Series, cfg: ScreenConfig) -> int:
    met = 0
    if pd.notna(row.get("revenue_growth")) and row["revenue_growth"] >= cfg.min_revenue_growth:
        met += 1
    if pd.notna(row.get("earnings_growth")) and row["earnings_growth"] >= cfg.min_earnings_growth:
        met += 1
    if pd.notna(row.get("roe")) and row["roe"] >= cfg.min_roe:
        met += 1
    return met


def filter_by_growth(df: pd.DataFrame, cfg: ScreenConfig) -> pd.DataFrame:
    df = df.copy()
    df["growth_criteria_met"] = df.apply(lambda r: _count_growth_criteria(r, cfg), axis=1)
    mask = df["growth_criteria_met"] >= cfg.min_growth_criteria_met

    if cfg.max_debt_to_equity is not None:
        # Keep names with unknown D/E (NaN) -- don't penalise missing data.
        de_ok = df["debt_to_equity"].isna() | (df["debt_to_equity"] <= cfg.max_debt_to_equity)
        mask &= de_ok
    if cfg.max_trailing_pe is not None:
        pe_ok = df["trailing_pe"].isna() | (df["trailing_pe"] <= cfg.max_trailing_pe)
        mask &= pe_ok

    return df[mask].copy()


def _zscore(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    mu, sd = s.mean(), s.std(ddof=0)
    if not sd or np.isnan(sd):
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


def score_growth(df: pd.DataFrame, cfg: ScreenConfig) -> pd.DataFrame:
    """Composite growth score = weighted sum of z-scored growth/quality metrics."""
    df = df.copy()
    score = pd.Series(0.0, index=df.index)
    for metric, w in cfg.weights.items():
        if metric in df.columns:
            score = score + w * _zscore(df[metric]).fillna(0.0)
    df["growth_score"] = score.round(4)
    return df.sort_values("growth_score", ascending=False)


def select_balanced(df: pd.DataFrame, cfg: ScreenConfig) -> pd.DataFrame:
    """Pick top names by score under a per-sector diversification cap."""
    df = df.sort_values("growth_score", ascending=False)
    per_sector: dict[str, int] = {}
    picks: list[int] = []
    for idx, row in df.iterrows():
        sec = row["thesis_sector"]
        if per_sector.get(sec, 0) >= cfg.max_per_sector:
            continue
        picks.append(idx)
        per_sector[sec] = per_sector.get(sec, 0) + 1
        if len(picks) >= cfg.target_count:
            break
    out = df.loc[picks].copy()
    out["selected_rank"] = range(1, len(out) + 1)
    return out


def run_screen(df: pd.DataFrame, cfg: ScreenConfig | None = None) -> dict:
    """Run the full pipeline. Returns a dict of each stage's DataFrame + summary."""
    cfg = cfg or ScreenConfig()
    stages = {}
    stages["input"] = df
    df = assign_cap_buckets(df, cfg)
    df = filter_by_sector(df, cfg);          stages["after_sector"] = df
    df = filter_by_market_cap(df, cfg);      stages["after_market_cap"] = df
    df = filter_by_growth(df, cfg);          stages["after_growth"] = df
    df = score_growth(df, cfg);              stages["scored"] = df
    shortlist = select_balanced(df, cfg);    stages["shortlist"] = shortlist

    summary = {
        "n_input": len(stages["input"]),
        "n_after_sector": len(stages["after_sector"]),
        "n_after_market_cap": len(stages["after_market_cap"]),
        "n_after_growth": len(stages["after_growth"]),
        "n_shortlist": len(shortlist),
        "sector_counts": shortlist["thesis_sector"].value_counts().to_dict() if not shortlist.empty else {},
        "cap_counts": shortlist["cap_bucket"].value_counts().to_dict() if not shortlist.empty else {},
    }
    return {"stages": stages, "shortlist": shortlist, "summary": summary, "config": cfg}
