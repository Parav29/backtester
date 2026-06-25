"""Pull per-stock fundamentals used by the B4 screen.

Data source is yfinance (Yahoo Finance). We extract a compact, screen-relevant
set of fields and normalise units (market cap to INR crore). Results are cached
to ``data/fundamentals_cache.csv`` so repeat runs and the backtester don't
re-hammer Yahoo.

NOTE ON NETWORK: Yahoo Finance hosts are blocked by some corporate/sandbox
egress policies (you'll see a proxy 403 / ProxyError). In that case this module
raises ``DataUnavailable`` per ticker and the screener reports which names it
could not fetch rather than crashing. Run on a machine with open egress to
Yahoo Finance to get live data.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, asdict
from typing import Iterable

import pandas as pd

log = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CACHE_PATH = os.path.join(_DATA_DIR, "fundamentals_cache.csv")

# Map Yahoo's GICS-style sector strings to the competition's thesis sectors.
_SECTOR_MAP = {
    "Consumer Cyclical": "Consumption",
    "Consumer Defensive": "Consumption",
    "Financial Services": "Financials",
    "Industrials": "Industrials",
    "Technology": "Digital",
    "Communication Services": "Digital",
    "Healthcare": "Healthcare",
    "Basic Materials": "Industrials",
    "Energy": "Industrials",
    "Utilities": "Industrials",
    "Real Estate": "Financials",
}

# Fields we read from yfinance ``.info``. Kept explicit so the schema is stable.
FIELDS = [
    "ticker",
    "name",
    "thesis_sector",
    "yahoo_sector",
    "price",
    "market_cap_cr",   # INR crore
    "cap_bucket",      # large / mid / small (assigned in filters)
    "trailing_pe",
    "forward_pe",
    "peg",
    "revenue_growth",  # yoy, fraction (0.15 == 15%)
    "earnings_growth", # yoy, fraction
    "profit_margin",   # fraction
    "roe",             # return on equity, fraction
    "debt_to_equity",  # ratio (yahoo reports as %, we store as ratio)
]


class DataUnavailable(Exception):
    """Raised when fundamentals for a ticker cannot be retrieved."""


@dataclass
class Fundamentals:
    ticker: str
    name: str | None = None
    thesis_sector: str | None = None
    yahoo_sector: str | None = None
    price: float | None = None
    market_cap_cr: float | None = None
    cap_bucket: str | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    peg: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    profit_margin: float | None = None
    roe: float | None = None
    debt_to_equity: float | None = None


def _to_cr(market_cap_inr: float | None) -> float | None:
    if market_cap_inr is None:
        return None
    return round(market_cap_inr / 1e7, 1)  # 1 crore = 1e7


def _normalise_de(de: float | None) -> float | None:
    # Yahoo reports debtToEquity as a percentage (e.g. 45.2 == 0.452x).
    if de is None:
        return None
    return round(de / 100.0, 3)


def _is_valid(val) -> bool:
    """Return True if val is a non-null, non-NaN string value."""
    if val is None:
        return False
    try:
        import pandas as _pd
        if _pd.isna(val):
            return False
    except (TypeError, ValueError):
        pass
    return bool(val)


def fetch_one(ticker: str, seed_name: str | None = None,
              seed_sector: str | None = None, retries: int = 2) -> Fundamentals:
    """Fetch fundamentals for a single ticker. Raises ``DataUnavailable`` on failure."""
    import yfinance as yf  # imported lazily so the package isn't required for tests

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            info = yf.Ticker(ticker).info
            if not info or info.get("regularMarketPrice") is None and info.get("currentPrice") is None:
                raise DataUnavailable(f"empty info for {ticker}")
            ysector = info.get("sector")
            return Fundamentals(
                ticker=ticker,
                name=info.get("shortName") or info.get("longName") or seed_name,
                thesis_sector=seed_sector if _is_valid(seed_sector) else _SECTOR_MAP.get(ysector, ysector),
                yahoo_sector=ysector,
                price=info.get("currentPrice") or info.get("regularMarketPrice"),
                market_cap_cr=_to_cr(info.get("marketCap")),
                trailing_pe=info.get("trailingPE"),
                forward_pe=info.get("forwardPE"),
                peg=info.get("pegRatio") or info.get("trailingPegRatio"),
                revenue_growth=info.get("revenueGrowth"),
                earnings_growth=info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth"),
                profit_margin=info.get("profitMargins"),
                roe=info.get("returnOnEquity"),
                debt_to_equity=_normalise_de(info.get("debtToEquity")),
            )
        except DataUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise DataUnavailable(f"{ticker}: {last_exc}")


def fetch_many(universe: pd.DataFrame, use_cache: bool = True,
               pause: float = 0.4) -> tuple[pd.DataFrame, list[str]]:
    """Fetch fundamentals for every ticker in ``universe``.

    Returns ``(dataframe, failed_tickers)``. ``universe`` must have a ``ticker``
    column and optionally ``name`` / ``thesis_sector`` (used as seeds/fallbacks).
    """
    cached: dict[str, dict] = {}
    if use_cache and os.path.exists(CACHE_PATH):
        cdf = pd.read_csv(CACHE_PATH)
        cached = {r["ticker"]: r.to_dict() for _, r in cdf.iterrows()}
        log.info("Loaded %d cached fundamentals from %s", len(cached), CACHE_PATH)

    rows: list[dict] = []
    failed: list[str] = []
    for _, r in universe.iterrows():
        tk = r["ticker"]
        if tk in cached:
            rows.append(cached[tk])
            continue
        try:
            f = fetch_one(tk, seed_name=r.get("name"), seed_sector=r.get("thesis_sector"))
            rows.append(asdict(f))
            log.info("fetched %s (mcap=%s cr)", tk, f.market_cap_cr)
        except DataUnavailable as exc:
            failed.append(tk)
            log.warning("skip %s: %s", tk, exc)
        time.sleep(pause)

    df = pd.DataFrame(rows)
    for col in FIELDS:
        if col not in df.columns:
            df[col] = pd.NA
    df = df[FIELDS]

    if use_cache and not df.empty:
        df.to_csv(CACHE_PATH, index=False)
        log.info("wrote %d fundamentals to %s", len(df), CACHE_PATH)

    return df, failed
