"""Tax layer: LTCG/STCG on equity, slab tax on debt, SGB exemption.

Applied at exit/withdrawal milestones to produce net-of-tax corpus. Rates from
config (context: "Tax Treatment"). All functions are pure.
"""

from __future__ import annotations

from .config import (
    DEBT_TAX_RATE,
    LTCG_EQUITY,
    LTCG_EQUITY_EXEMPTION,
    STCG_EQUITY,
)


def equity_ltcg_tax(gain: float, exemption: float = LTCG_EQUITY_EXEMPTION) -> float:
    """Long-term capital gains tax on equity: 12.5% on gains above ₹1.25L/yr."""
    if gain <= 0:
        return 0.0
    taxable = max(0.0, gain - exemption)
    return taxable * LTCG_EQUITY


def equity_stcg_tax(gain: float) -> float:
    """Short-term capital gains tax on equity: 20%."""
    return max(0.0, gain) * STCG_EQUITY


def debt_tax(gain: float, rate: float = DEBT_TAX_RATE) -> float:
    """G-Sec/bond gains taxed at slab rate (assume 30%)."""
    return max(0.0, gain) * rate


def net_of_tax(invested: float, current_value: float, asset_class: str,
               held_long_term: bool = True) -> dict:
    """Return gross gain, tax, and net value for a position.

    asset_class: 'equity' | 'debt' | 'sgb'
    """
    gain = current_value - invested
    if asset_class == "equity":
        tax = equity_ltcg_tax(gain) if held_long_term else equity_stcg_tax(gain)
    elif asset_class == "debt":
        tax = debt_tax(gain)
    elif asset_class == "sgb":
        tax = 0.0   # SGB redemption at maturity is tax-exempt
    else:
        raise ValueError(f"unknown asset_class: {asset_class}")
    return {
        "invested": round(invested, 0),
        "current_value": round(current_value, 0),
        "gross_gain": round(gain, 0),
        "tax": round(tax, 0),
        "net_value": round(current_value - tax, 0),
    }
