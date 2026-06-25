"""Define the investable universe for the B4 screen.

The competition restricts equities to constituents of the **Nifty Total Market
Index** (~750 names). The official list is published by NSE as a CSV:

    https://archives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv

When that host is reachable we use it as the source of truth. When it is not
(e.g. inside a locked-down sandbox whose egress policy blocks NSE), we fall back
to a curated seed list of thesis-relevant names shipped in ``data/``. Either way
the rest of the screener only sees a tidy DataFrame of tickers.
"""

from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass

import pandas as pd
import requests

log = logging.getLogger(__name__)

NSE_LIST_URL = "https://archives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv"

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SEED_PATH = os.path.join(_DATA_DIR, "nifty_total_market_seed.csv")

# NSE list columns -> our schema. We map NSE's "Industry" to a coarse thesis
# sector via fundamentals.py later; here we just normalise tickers.
_NSE_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "text/csv,application/csv,*/*",
}


@dataclass
class UniverseResult:
    df: pd.DataFrame
    source: str  # "nse" or "seed"


def _load_seed() -> pd.DataFrame:
    df = pd.read_csv(SEED_PATH, comment="#")
    df["ticker"] = df["ticker"].str.strip()
    df["name"] = df["name"].str.strip()
    df["thesis_sector"] = df["thesis_sector"].str.strip()
    return df


def _fetch_nse(timeout: int = 20) -> pd.DataFrame:
    """Fetch and normalise the official Nifty Total Market constituent list.

    Raises on any network/parse failure so the caller can fall back to the seed.
    """
    resp = requests.get(NSE_LIST_URL, headers=_NSE_BROWSER_HEADERS, timeout=timeout)
    resp.raise_for_status()
    raw = pd.read_csv(io.StringIO(resp.text))
    # NSE CSV columns: "Company Name","Industry","Symbol","Series","ISIN Code"
    out = pd.DataFrame(
        {
            "ticker": raw["Symbol"].str.strip() + ".NS",
            "name": raw["Company Name"].str.strip(),
            "thesis_sector": pd.NA,  # filled from fundamentals' GICS sector later
            "nse_industry": raw["Industry"].str.strip(),
        }
    )
    return out


def load_universe(prefer_nse: bool = True, timeout: int = 20) -> UniverseResult:
    """Return the investable universe as a DataFrame.

    Tries the official NSE list first (when ``prefer_nse``); on any failure logs
    a warning and returns the curated seed so the screener still runs offline.
    """
    if prefer_nse:
        try:
            df = _fetch_nse(timeout=timeout)
            log.info("Loaded %d names from official NSE Nifty Total Market list", len(df))
            return UniverseResult(df=df, source="nse")
        except Exception as exc:  # noqa: BLE001 - we deliberately degrade gracefully
            log.warning(
                "Could not fetch NSE list (%s). Falling back to curated seed list. "
                "This is expected in sandboxes that block nseindia.com.",
                exc,
            )
    df = _load_seed()
    log.info("Loaded %d names from curated seed list", len(df))
    return UniverseResult(df=df, source="seed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = load_universe()
    print(f"source={res.source}  n={len(res.df)}")
    print(res.df.head(10).to_string(index=False))
