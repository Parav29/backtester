"""Unit tests for the pure screening logic (no network required)."""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screener.filters import (  # noqa: E402
    ScreenConfig,
    assign_cap_buckets,
    filter_by_growth,
    filter_by_market_cap,
    filter_by_sector,
    run_screen,
    score_growth,
    select_balanced,
)


def _mk(**kw):
    base = dict(
        ticker="X.NS", name="X", thesis_sector="Consumption", yahoo_sector="Consumer Cyclical",
        price=100.0, market_cap_cr=100000.0, cap_bucket=None, trailing_pe=30.0,
        forward_pe=25.0, peg=1.5, revenue_growth=0.15, earnings_growth=0.18,
        profit_margin=0.12, roe=0.20, debt_to_equity=0.5,
    )
    base.update(kw)
    return base


@pytest.fixture
def df():
    rows = [
        _mk(ticker="LARGE.NS", market_cap_cr=200000.0),
        _mk(ticker="MID.NS", market_cap_cr=40000.0),
        _mk(ticker="SMALL.NS", market_cap_cr=12000.0),
        _mk(ticker="MICRO.NS", market_cap_cr=2000.0),
    ]
    return pd.DataFrame(rows)


def test_cap_buckets(df):
    cfg = ScreenConfig()
    out = assign_cap_buckets(df, cfg)
    buckets = dict(zip(out["ticker"], out["cap_bucket"]))
    assert buckets["LARGE.NS"] == "large"
    assert buckets["MID.NS"] == "mid"
    assert buckets["SMALL.NS"] == "small"


def test_market_cap_floor_drops_micro(df):
    cfg = ScreenConfig(min_market_cap_cr=5000.0)
    out = filter_by_market_cap(df, cfg)
    assert "MICRO.NS" not in set(out["ticker"])
    assert len(out) == 3


def test_sector_filter():
    cfg = ScreenConfig()
    data = pd.DataFrame([
        _mk(ticker="A.NS", thesis_sector="Defence"),
        _mk(ticker="B.NS", thesis_sector="Energy"),       # not in allowed thesis sectors
        _mk(ticker="C.NS", thesis_sector="Healthcare"),
    ])
    out = filter_by_sector(data, cfg)
    assert set(out["ticker"]) == {"A.NS", "C.NS"}


def test_growth_gate_requires_min_criteria():
    cfg = ScreenConfig(min_growth_criteria_met=2)
    data = pd.DataFrame([
        _mk(ticker="GOOD.NS", revenue_growth=0.20, earnings_growth=0.25, roe=0.22),
        _mk(ticker="ONE.NS", revenue_growth=0.20, earnings_growth=0.02, roe=0.05),  # only 1 gate
        _mk(ticker="NONE.NS", revenue_growth=0.01, earnings_growth=0.01, roe=0.01),
    ])
    out = filter_by_growth(data, cfg)
    assert set(out["ticker"]) == {"GOOD.NS"}


def test_growth_gate_excludes_overlevered():
    cfg = ScreenConfig(max_debt_to_equity=2.0)
    data = pd.DataFrame([
        _mk(ticker="OK.NS", debt_to_equity=1.0),
        _mk(ticker="LEVERED.NS", debt_to_equity=3.5),
    ])
    out = filter_by_growth(data, cfg)
    assert set(out["ticker"]) == {"OK.NS"}


def test_growth_gate_keeps_missing_de():
    cfg = ScreenConfig(max_debt_to_equity=2.0)
    data = pd.DataFrame([_mk(ticker="NODE.NS", debt_to_equity=None)])
    out = filter_by_growth(data, cfg)
    assert set(out["ticker"]) == {"NODE.NS"}


def test_score_orders_by_growth():
    data = pd.DataFrame([
        _mk(ticker="HI.NS", revenue_growth=0.40, earnings_growth=0.40, roe=0.35, profit_margin=0.25),
        _mk(ticker="LO.NS", revenue_growth=0.11, earnings_growth=0.11, roe=0.14, profit_margin=0.05),
    ])
    out = score_growth(data, ScreenConfig())
    assert out.iloc[0]["ticker"] == "HI.NS"


def test_select_balanced_respects_sector_cap():
    rows = [_mk(ticker=f"C{i}.NS", thesis_sector="Consumption",
                revenue_growth=0.2 + i * 0.01, earnings_growth=0.2, roe=0.2) for i in range(5)]
    rows += [_mk(ticker="F1.NS", thesis_sector="Financials")]
    data = score_growth(pd.DataFrame(rows), ScreenConfig())
    out = select_balanced(data, ScreenConfig(max_per_sector=2, target_count=10))
    counts = out["thesis_sector"].value_counts().to_dict()
    assert counts["Consumption"] == 2
    assert counts["Financials"] == 1


def test_run_screen_end_to_end():
    rows = [
        _mk(ticker="HDFCBANK.NS", thesis_sector="Financials", market_cap_cr=1200000,
            revenue_growth=0.18, earnings_growth=0.20, roe=0.17),
        _mk(ticker="HAL.NS", thesis_sector="Defence", market_cap_cr=300000,
            revenue_growth=0.22, earnings_growth=0.28, roe=0.27),
        _mk(ticker="JUNK.NS", thesis_sector="Energy", market_cap_cr=8000,  # wrong sector
            revenue_growth=0.30, earnings_growth=0.30, roe=0.30),
        _mk(ticker="WEAK.NS", thesis_sector="Healthcare", market_cap_cr=50000,
            revenue_growth=0.02, earnings_growth=0.01, roe=0.04),  # fails growth
    ]
    res = run_screen(pd.DataFrame(rows), ScreenConfig(target_count=12, max_per_sector=3))
    sl = set(res["shortlist"]["ticker"])
    assert "HDFCBANK.NS" in sl and "HAL.NS" in sl
    assert "JUNK.NS" not in sl   # filtered by sector
    assert "WEAK.NS" not in sl   # filtered by growth
    assert res["summary"]["n_shortlist"] == 2
