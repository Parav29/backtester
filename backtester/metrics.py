"""B4 equity risk/return metrics: Beta, Sharpe, Treynor, Jensen's Alpha.

    Beta           = Cov(stock, market) / Var(market)
    Sharpe         = (Rp - Rf) / σp
    Treynor        = (Rp - Rf) / βp
    Jensen's Alpha = Rp - [Rf + (Rm - Rf) × βp]

Rf and Rm are competition-mandated (config.RF, config.RM). The portfolio beta is
the weight-weighted average of individual stock betas; σp is computed from the
weighted historical return series (so it captures diversification, not just a
weighted sum of stdevs).

Price history comes from yfinance. The market proxy is the Nifty 50 index ``^NSEI``.
On blocked egress the functions raise and the runner reports it — same graceful
degradation as the screener.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import RF, RM

log = logging.getLogger(__name__)

MARKET_TICKER = "^NSEI"   # Nifty 50 index


@dataclass
class PortfolioMetrics:
    tickers: list[str]
    weights: list[float]
    portfolio_return: float            # Rp, annualised
    portfolio_std: float               # σp, annualised
    portfolio_beta: float              # βp
    sharpe_ratio: float
    treynor_ratio: float
    jensen_alpha: float
    max_drawdown: float
    market_return_realised: float      # realised Rm over the window (for reference)
    risk_free_rate: float = RF
    market_return: float = RM          # competition Rm used in ratios
    individual_betas: dict[str, float] = field(default_factory=dict)
    annualised_returns: dict[str, float] = field(default_factory=dict)


def _monthly_returns_from_download(raw: pd.DataFrame, ticker: str) -> pd.Series:
    """Extract a clean monthly return series from a yfinance download frame.

    yfinance returns either a flat frame or a column MultiIndex when multiple
    tickers are requested; and uses 'Adj Close' or falls back to 'Close'.
    """
    if isinstance(raw.columns, pd.MultiIndex):
        # pick the price level for this ticker
        field_level = "Adj Close" if "Adj Close" in raw.columns.get_level_values(0) else "Close"
        prices = raw[field_level]
        prices = prices[ticker] if ticker in prices.columns else prices.iloc[:, 0]
    else:
        col = "Adj Close" if "Adj Close" in raw.columns else "Close"
        prices = raw[col]
    prices = prices.dropna()
    return np.log(prices / prices.shift(1)).dropna()


def fetch_monthly_returns(tickers: list[str], period: str = "5y") -> dict[str, pd.Series]:
    """Fetch monthly log returns for tickers + market. Raises on total failure."""
    import yfinance as yf

    all_tickers = list(dict.fromkeys(tickers + [MARKET_TICKER]))
    raw = yf.download(all_tickers, period=period, interval="1mo",
                      auto_adjust=False, progress=False)
    if raw is None or raw.empty:
        raise ValueError("yfinance returned no data (host blocked or bad tickers?)")

    out: dict[str, pd.Series] = {}
    for tk in all_tickers:
        try:
            r = _monthly_returns_from_download(raw, tk)
            if len(r) >= 12:
                out[tk] = r
            else:
                log.warning("skip %s: only %d monthly returns", tk, len(r))
        except Exception as exc:  # noqa: BLE001
            log.warning("skip %s: %s", tk, exc)
    if MARKET_TICKER not in out:
        raise ValueError(f"could not build market series ({MARKET_TICKER})")
    return out


def _annualise(monthly: pd.Series) -> float:
    return (1 + monthly.mean()) ** 12 - 1


def _max_drawdown(cum_returns: pd.Series) -> float:
    """Max drawdown from a cumulative-return (wealth index) series."""
    wealth = (1 + cum_returns).cumprod()
    running_max = wealth.cummax()
    drawdown = wealth / running_max - 1
    return float(drawdown.min())


def compute_metrics(tickers: list[str], weights: list[float],
                    returns: dict[str, pd.Series] | None = None,
                    period: str = "5y") -> PortfolioMetrics:
    """Compute weighted portfolio metrics.

    ``returns`` may be supplied (for tests/offline); otherwise fetched live.
    Weights are normalised to sum to 1.
    """
    if len(tickers) != len(weights):
        raise ValueError("tickers and weights length mismatch")
    total_w = sum(weights)
    if total_w <= 0:
        raise ValueError("weights must sum to a positive number")
    weights = [w / total_w for w in weights]

    if returns is None:
        returns = fetch_monthly_returns(tickers, period=period)

    market = returns[MARKET_TICKER]

    # Align everything on the common monthly index
    usable = [t for t in tickers if t in returns]
    if not usable:
        raise ValueError("no usable ticker return series")
    frame = pd.DataFrame({t: returns[t] for t in usable})
    frame["__market__"] = market
    frame = frame.dropna()
    if len(frame) < 12:
        raise ValueError(f"only {len(frame)} aligned months; need >= 12")

    mkt = frame["__market__"]
    var_mkt = np.var(mkt, ddof=1)

    individual_betas: dict[str, float] = {}
    annualised: dict[str, float] = {}
    for t in usable:
        cov = np.cov(frame[t], mkt)[0, 1]
        individual_betas[t] = float(cov / var_mkt) if var_mkt else float("nan")
        annualised[t] = _annualise(frame[t])

    # Re-normalise weights across usable tickers only
    w_map = {t: w for t, w in zip(tickers, weights)}
    usable_w = np.array([w_map[t] for t in usable])
    usable_w = usable_w / usable_w.sum()

    # Portfolio monthly return series (captures covariance/diversification)
    port_monthly = (frame[usable] * usable_w).sum(axis=1)
    portfolio_return = _annualise(port_monthly)
    portfolio_std = float(port_monthly.std(ddof=1) * np.sqrt(12))
    portfolio_beta = float(np.dot(usable_w, [individual_betas[t] for t in usable]))
    max_dd = _max_drawdown(port_monthly)

    excess = portfolio_return - RF
    sharpe = excess / portfolio_std if portfolio_std else float("nan")
    treynor = excess / portfolio_beta if portfolio_beta else float("nan")
    jensen = portfolio_return - (RF + (RM - RF) * portfolio_beta)

    return PortfolioMetrics(
        tickers=usable,
        weights=list(usable_w),
        portfolio_return=portfolio_return,
        portfolio_std=portfolio_std,
        portfolio_beta=portfolio_beta,
        sharpe_ratio=sharpe,
        treynor_ratio=treynor,
        jensen_alpha=jensen,
        max_drawdown=max_dd,
        market_return_realised=_annualise(mkt),
        individual_betas=individual_betas,
        annualised_returns=annualised,
    )


def load_picks(path: str) -> tuple[list[str], list[float]]:
    """Read a B4 picks CSV. Uses 'weight' or 'allocation_pct' column if present,
    else equal-weights. Expects a 'ticker' column."""
    df = pd.read_csv(path)
    if "ticker" not in df.columns:
        raise ValueError(f"{path} has no 'ticker' column")
    tickers = df["ticker"].astype(str).str.strip().tolist()
    if "weight" in df.columns:
        weights = df["weight"].astype(float).tolist()
    elif "allocation_pct" in df.columns:
        weights = df["allocation_pct"].astype(float).tolist()
    else:
        weights = [1.0 / len(tickers)] * len(tickers)
    return tickers, weights


def format_metrics(m: PortfolioMetrics) -> str:
    lines = [
        "=" * 60,
        "B4 PORTFOLIO METRICS (Aarya's Growth Pool)",
        "=" * 60,
        f"Portfolio Return  Rp : {m.portfolio_return * 100:>7.2f}%",
        f"Risk-Free Rate    Rf : {m.risk_free_rate * 100:>7.2f}%   (competition)",
        f"Market Return     Rm : {m.market_return * 100:>7.2f}%   (competition)",
        f"Realised Mkt (5y)    : {m.market_return_realised * 100:>7.2f}%",
        f"Portfolio Std Dev σp : {m.portfolio_std * 100:>7.2f}%",
        f"Portfolio Beta    βp : {m.portfolio_beta:>7.3f}",
        "-" * 60,
        f"Sharpe Ratio         : {m.sharpe_ratio:>7.3f}",
        f"Treynor Ratio        : {m.treynor_ratio:>7.3f}",
        f"Jensen's Alpha       : {m.jensen_alpha * 100:>7.2f}%",
        f"Max Drawdown         : {m.max_drawdown * 100:>7.2f}%",
        "=" * 60,
        "Individual betas:",
    ]
    for t in m.tickers:
        lines.append(f"  {t:<14} β={m.individual_betas.get(t, float('nan')):>6.3f}  "
                     f"ann.ret={m.annualised_returns.get(t, float('nan')) * 100:>6.1f}%")
    return "\n".join(lines)
