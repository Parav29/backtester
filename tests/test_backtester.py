"""Unit tests for the backtester (pure logic, no network)."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtester import config  # noqa: E402
from backtester.config import Basket, Event  # noqa: E402
from backtester.metrics import compute_metrics  # noqa: E402
from backtester.montecarlo import run_monte_carlo  # noqa: E402
from backtester.projection import cagr, goal_reconciliation, project_portfolio  # noqa: E402
from backtester.tax import debt_tax, equity_ltcg_tax, equity_stcg_tax, net_of_tax  # noqa: E402


# ---------- projection ----------

def test_single_basket_compounds():
    baskets = {"X": Basket("X", "test", initial=100.0, target=200.0,
                           target_year=2036, blended_return=0.10, blended_vol=0.0)}
    res = project_portfolio(baskets, [], [], 2026, 2036)
    # 100 * 1.1^10 = 259.37
    assert res.final_values["X"] == pytest.approx(100 * 1.1 ** 10, rel=1e-6)


def test_transfer_moves_capital_between_baskets():
    baskets = {
        "A": Basket("A", "", initial=1000.0, target=0, target_year=2036, blended_return=0.0, blended_vol=0.0),
        "B": Basket("B", "", initial=0.0, target=0, target_year=2036, blended_return=0.0, blended_vol=0.0),
    }
    ev = Event(year=2029, name="t", description="", transfers=[("A", "B", 300.0)])
    res = project_portfolio(baskets, [ev], [], 2026, 2036)
    assert res.final_values["A"] == pytest.approx(700.0)
    assert res.final_values["B"] == pytest.approx(300.0)


def test_value_shock_applied():
    baskets = {"A": Basket("A", "", initial=100.0, target=0, target_year=2036,
                           blended_return=0.0, blended_vol=0.0)}
    ev = Event(year=2029, name="shock", description="", value_shocks={"A": 1.05})
    res = project_portfolio(baskets, [ev], [], 2026, 2036)
    assert res.final_values["A"] == pytest.approx(105.0)


def test_withdrawal_reduces_basket():
    baskets = {"A": Basket("A", "", initial=1000.0, target=0, target_year=2036,
                           blended_return=0.0, blended_vol=0.0)}
    res = project_portfolio(baskets, [], [("w", 2028, "A", 200.0)], 2026, 2036)
    assert res.final_values["A"] == pytest.approx(800.0)
    assert len(res.withdrawals_made) == 1


def test_cagr():
    assert cagr(100, 200, 10) == pytest.approx(0.07177, abs=1e-4)
    assert np.isnan(cagr(0, 100, 10))


def test_goal_reconciliation_flags_met():
    baskets = {"A": Basket("A", "n", initial=100.0, target=150.0, target_year=2036,
                           blended_return=0.10, blended_vol=0.0)}
    res = project_portfolio(baskets, [], [], 2026, 2036)
    recon = goal_reconciliation(res, baskets)
    assert bool(recon.iloc[0]["met"]) is True   # 100*1.1^10 = 259 > 150


# ---------- tax ----------

def test_equity_ltcg_exemption():
    # gain below exemption -> no tax
    assert equity_ltcg_tax(100_000) == 0.0
    # gain above exemption -> 12.5% on excess
    g = 3_25_000  # ₹3.25L gain; ₹1.25L exempt -> ₹2L taxable
    assert equity_ltcg_tax(g) == pytest.approx(2_00_000 * 0.125)


def test_equity_stcg():
    assert equity_stcg_tax(100_000) == pytest.approx(20_000)


def test_debt_tax_slab():
    assert debt_tax(100_000) == pytest.approx(30_000)


def test_sgb_exempt():
    r = net_of_tax(100_000, 150_000, "sgb")
    assert r["tax"] == 0.0
    assert r["net_value"] == 150_000


def test_net_of_tax_no_gain_no_tax():
    r = net_of_tax(100_000, 90_000, "equity")
    assert r["tax"] == 0.0


# ---------- metrics (synthetic returns) ----------

def _synthetic_returns(n=60, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", periods=n, freq="MS")
    market = pd.Series(rng.normal(0.009, 0.04, n), index=idx)
    # stock A = 1.2*market + noise (beta ~1.2); stock B = 0.6*market (beta ~0.6)
    a = 1.2 * market + pd.Series(rng.normal(0, 0.01, n), index=idx)
    b = 0.6 * market + pd.Series(rng.normal(0, 0.01, n), index=idx)
    return {"A.NS": a, "B.NS": b, "^NSEI": market}


def test_metrics_beta_recovers_construction():
    returns = _synthetic_returns()
    m = compute_metrics(["A.NS", "B.NS"], [0.5, 0.5], returns=returns)
    assert m.individual_betas["A.NS"] == pytest.approx(1.2, abs=0.15)
    assert m.individual_betas["B.NS"] == pytest.approx(0.6, abs=0.15)
    # portfolio beta ~ average of 1.2 and 0.6 = 0.9
    assert m.portfolio_beta == pytest.approx(0.9, abs=0.15)


def test_metrics_jensen_alpha_formula():
    returns = _synthetic_returns()
    m = compute_metrics(["A.NS", "B.NS"], [0.5, 0.5], returns=returns)
    expected = m.portfolio_return - (config.RF + (config.RM - config.RF) * m.portfolio_beta)
    assert m.jensen_alpha == pytest.approx(expected, rel=1e-9)


def test_metrics_weights_normalised():
    returns = _synthetic_returns()
    m = compute_metrics(["A.NS", "B.NS"], [2.0, 2.0], returns=returns)  # un-normalised
    assert sum(m.weights) == pytest.approx(1.0)


# ---------- monte carlo ----------

def test_monte_carlo_deterministic_when_zero_vol():
    baskets = {"A": Basket("A", "n", initial=100.0, target=150.0, target_year=2036,
                           blended_return=0.10, blended_vol=0.0)}
    mc = run_monte_carlo(baskets, [], [], 2026, 2036, n_sims=100)
    # zero vol -> always meets (100*1.1^10=259) -> prob 1.0
    assert mc.goal_probabilities["A"] == 1.0


def test_monte_carlo_probability_between_0_and_1():
    mc = run_monte_carlo(config.BASKETS, config.EVENTS, config.WITHDRAWALS,
                         config.START_YEAR, config.END_YEAR, n_sims=200)
    for p in mc.goal_probabilities.values():
        assert 0.0 <= p <= 1.0
