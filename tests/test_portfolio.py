"""Unit tests for holdings -> baskets construction (pure logic, no network)."""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtester import config  # noqa: E402
from backtester.portfolio import (  # noqa: E402
    basket_tax_classes,
    build_baskets_from_holdings,
    equity_picks,
)


def _holdings():
    return pd.DataFrame([
        # B4: two equities given by quantity x price
        {"basket": "B4", "ticker": "HAL.NS", "name": "HAL", "asset_class": "equity_large",
         "quantity": 100, "price": 5000, "value_inr": None, "return_override": None, "vol_override": None},
        {"basket": "B4", "ticker": "DIXON.NS", "name": "Dixon", "asset_class": "equity_midsmall",
         "quantity": 10, "price": 15000, "value_inr": None, "return_override": None, "vol_override": None},
        # B3: a bond given directly by value, with a return override
        {"basket": "B3", "ticker": None, "name": "GSec", "asset_class": "gsec",
         "quantity": None, "price": None, "value_inr": 1_000_000, "return_override": 0.072, "vol_override": None},
    ])


def test_value_from_quantity_times_price():
    baskets = build_baskets_from_holdings(_holdings())
    # B4 = 100*5000 + 10*15000 = 500000 + 150000 = 650000
    assert baskets["B4"].initial == pytest.approx(650_000)


def test_value_from_value_inr_column():
    baskets = build_baskets_from_holdings(_holdings())
    assert baskets["B3"].initial == pytest.approx(1_000_000)


def test_blended_return_is_value_weighted():
    baskets = build_baskets_from_holdings(_holdings())
    # B4: 500000 @ large(11%) + 150000 @ midsmall(13%)
    expected = (500_000 * config.LARGE_CAP_RETURN + 150_000 * config.MIDSMALL_CAP_RETURN) / 650_000
    assert baskets["B4"].blended_return == pytest.approx(expected)


def test_return_override_used():
    baskets = build_baskets_from_holdings(_holdings())
    assert baskets["B3"].blended_return == pytest.approx(0.072)


def test_targets_kept_from_config():
    baskets = build_baskets_from_holdings(_holdings())
    # initial is overridden by holdings, but the competition target/year are kept
    assert baskets["B4"].target == config.BASKETS["B4"].target
    assert baskets["B4"].target_year == config.BASKETS["B4"].target_year


def test_equity_picks_extracts_only_equities_with_tickers():
    tickers, weights = equity_picks(_holdings())
    assert set(tickers) == {"HAL.NS", "DIXON.NS"}
    assert weights == pytest.approx([500_000, 150_000])


def test_tax_class_from_dominant_asset():
    tc = basket_tax_classes(_holdings())
    assert tc["B4"] == "equity"   # equities dominate
    assert tc["B3"] == "debt"     # gsec -> debt


def test_missing_value_raises():
    bad = pd.DataFrame([{"basket": "B4", "ticker": "X.NS", "name": "X",
                         "asset_class": "equity_large", "quantity": None, "price": None,
                         "value_inr": None, "return_override": None, "vol_override": None}])
    with pytest.raises(ValueError):
        build_baskets_from_holdings(bad)
