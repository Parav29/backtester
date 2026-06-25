"""Build the four baskets from a user-defined holdings file.

This lets you skip the screener and specify EXACTLY what you hold — individual
stocks (with quantities), bonds, G-Secs, gold/SGB, REIT/InvIT, cash — grouped by
basket. The backtester then derives each basket's:

  * initial value      = sum of its positions (quantity x price, or value_inr)
  * blended return     = value-weighted average of per-asset-class returns
  * blended volatility  = value-weighted average of per-asset-class vols

and runs the same projection / Monte Carlo / tax / Excel pipeline on YOUR mix.
The equity positions are also handed to ``metrics.py`` for Beta / Sharpe /
Treynor / Jensen's Alpha.

Targets, target years, names, purposes, the 2029/2033 events and withdrawals all
still come from ``config`` — those are the competition goals and don't change
with your instrument choices.

Holdings CSV columns (``#`` lines are comments):

    basket           B1 | B2 | B3 | B4
    ticker           yfinance symbol for equities (e.g. HAL.NS); blank for bonds/cash
    name             free-text label
    asset_class      equity_large | equity_midsmall | gsec | bond | gold | sgb |
                     reit_invit | cash
    quantity         number of shares/units   ┐ give EITHER quantity+price …
    price            price per share/unit INR ┘
    value_inr        … OR the rupee value of the position directly
    return_override  optional annual return fraction (e.g. 0.12); blank = asset default
    vol_override     optional annual volatility fraction; blank = asset default

If the file is missing or empty, the runner falls back to the screener picks /
config defaults.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import pandas as pd

from . import config
from .config import Basket

log = logging.getLogger(__name__)

# asset_class -> (annual_return, annual_vol), drawn from the competition baseline
# assumptions in config. Override per row with return_override / vol_override.
ASSET_CLASSES: dict[str, tuple[float, float]] = {
    "equity_large":    (config.LARGE_CAP_RETURN,    config.VOL_LARGE_CAP),
    "equity_midsmall": (config.MIDSMALL_CAP_RETURN, config.VOL_MIDSMALL_CAP),
    "gsec":            (config.GSEC_RETURN,         config.VOL_GSEC),
    "bond":            (config.AAA_BOND_RETURN,     config.VOL_BOND),
    "gold":            (config.GOLD_RETURN,         config.VOL_GOLD),
    "sgb":             (config.GOLD_RETURN,         config.VOL_GOLD),     # SGB tracks gold
    "reit_invit":      (config.REIT_INVIT_RETURN,   config.VOL_REIT_INVIT),
    "cash":            (config.RF,                  0.005),
}

# asset_class -> tax bucket used by tax.net_of_tax
TAX_CLASS: dict[str, str] = {
    "equity_large": "equity", "equity_midsmall": "equity",
    "gsec": "debt", "bond": "debt", "cash": "debt",
    "gold": "debt", "reit_invit": "debt",
    "sgb": "sgb",
}

REQUIRED_COLS = {"basket", "asset_class"}


def load_holdings(path: str) -> pd.DataFrame:
    """Read a holdings CSV. Returns an empty DataFrame if there are no data rows."""
    df = pd.read_csv(path, comment="#", skip_blank_lines=True)
    df.columns = [c.strip() for c in df.columns]
    df = df.dropna(how="all")
    if df.empty:
        return df
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"holdings file missing required column(s): {sorted(missing)}")
    df["basket"] = df["basket"].astype(str).str.strip()
    df["asset_class"] = df["asset_class"].astype(str).str.strip()
    return df


def _present(v) -> bool:
    return pd.notna(v) and str(v).strip() != ""


def _row_value(row: pd.Series) -> float:
    """Position value in INR: value_inr if given, else quantity x price."""
    if _present(row.get("value_inr")):
        return float(row["value_inr"])
    if _present(row.get("quantity")) and _present(row.get("price")):
        return float(row["quantity"]) * float(row["price"])
    label = row.get("ticker") or row.get("name") or row.get("asset_class")
    raise ValueError(f"holding '{label}': provide value_inr OR both quantity and price")


def _row_return(row: pd.Series) -> float:
    if _present(row.get("return_override")):
        return float(row["return_override"])
    ac = row["asset_class"]
    if ac not in ASSET_CLASSES:
        raise ValueError(f"unknown asset_class '{ac}' (allowed: {sorted(ASSET_CLASSES)})")
    return ASSET_CLASSES[ac][0]


def _row_vol(row: pd.Series) -> float:
    if _present(row.get("vol_override")):
        return float(row["vol_override"])
    return ASSET_CLASSES[row["asset_class"]][1]


def build_baskets_from_holdings(
    holdings: pd.DataFrame,
    base: dict[str, Basket] = config.BASKETS,
) -> dict[str, Basket]:
    """Derive a baskets dict (initial / blended_return / blended_vol from the
    actual holdings; target / target_year / name / purpose kept from ``base``)."""
    h = holdings.copy()
    h["__value"] = h.apply(_row_value, axis=1)
    h["__ret"] = h.apply(_row_return, axis=1)
    h["__vol"] = h.apply(_row_vol, axis=1)

    baskets: dict[str, Basket] = {}
    for bid, grp in h.groupby("basket", sort=True):
        total = float(grp["__value"].sum())
        if total <= 0:
            log.warning("basket %s has zero value; skipping", bid)
            continue
        w = grp["__value"] / total
        blended_return = float((w * grp["__ret"]).sum())
        # Value-weighted vol IGNORES correlation -> conservative (overstates risk).
        # Flagged in the Assumptions Sheet. Good enough for goal-probability work.
        blended_vol = float((w * grp["__vol"]).sum())

        tmpl = base.get(bid)
        if tmpl is not None:
            baskets[bid] = replace(tmpl, initial=total,
                                   blended_return=blended_return,
                                   blended_vol=blended_vol)
        else:
            baskets[bid] = Basket(name=bid, purpose="(from holdings)", initial=total,
                                  target=0.0, target_year=config.END_YEAR,
                                  blended_return=blended_return, blended_vol=blended_vol)
    return baskets


def equity_picks(holdings: pd.DataFrame) -> tuple[list[str], list[float]]:
    """Tickers + value-weights for every equity holding with a ticker, for metrics."""
    eq = holdings[holdings["asset_class"].astype(str).str.startswith("equity")].copy()
    eq = eq[eq["ticker"].apply(_present)]
    if eq.empty:
        return [], []
    eq["__value"] = eq.apply(_row_value, axis=1)
    tickers = eq["ticker"].astype(str).str.strip().tolist()
    weights = eq["__value"].astype(float).tolist()
    return tickers, weights


def basket_tax_classes(holdings: pd.DataFrame) -> dict[str, str]:
    """Tax bucket per basket = the bucket of its largest-value asset class."""
    h = holdings.copy()
    h["__value"] = h.apply(_row_value, axis=1)
    out: dict[str, str] = {}
    for bid, grp in h.groupby("basket"):
        dominant = grp.groupby("asset_class")["__value"].sum().idxmax()
        out[bid] = TAX_CLASS.get(dominant, "debt")
    return out


def allocation_table(holdings: pd.DataFrame, baskets: dict[str, Basket]) -> pd.DataFrame:
    """Human-readable per-basket allocation summary for console/Excel."""
    h = holdings.copy()
    h["__value"] = h.apply(_row_value, axis=1)
    rows = []
    for bid, bk in baskets.items():
        grp = h[h["basket"] == bid]
        holdings_str = ", ".join(
            f"{(r['ticker'] if _present(r.get('ticker')) else r.get('name', '?'))}"
            f"={r['__value']:,.0f}"
            for _, r in grp.iterrows()
        )
        rows.append({
            "basket": bid,
            "value_INR": round(bk.initial, 0),
            "blended_return_%": round(bk.blended_return * 100, 2),
            "blended_vol_%": round(bk.blended_vol * 100, 2),
            "holdings": holdings_str,
        })
    return pd.DataFrame(rows)
