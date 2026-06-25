# Singhania Portfolio — Screener + Backtester

Two tools for the Singhania Family Portfolio Management Competition:

1. **`screener/`** — picks **B4 (Aarya's Growth Pool)** candidates from the Nifty
   Total Market universe by sector, market cap, and growth metrics.
2. **`backtester/`** — projects all four baskets (B1–B4) to 2036 with event-driven
   rebalancing, computes the bonus risk metrics, applies tax, runs Monte Carlo,
   and exports an Excel workbook for the judges.

## Backtester quick start

You can drive the backtester three ways — it uses the first one available:

1. **Your own holdings** (recommended): list the exact stocks/bonds + quantities.
2. **Screener shortlist**: use the screener's picks for the equity sleeve.
3. **Config defaults**: the hard-coded four-basket allocation.

```bash
# 1. Backtest the EXACT instruments you chose (stocks, bonds, gold, REITs ...)
cp data/holdings_template.csv data/holdings.csv   # then edit data/holdings.csv
python -m backtester.run --holdings data/holdings.csv

# 2. Use the screener shortlist for the equity metrics, config baskets otherwise
python -m backtester.run --picks data/b4_shortlist.csv

# 3. Projection + Monte Carlo + tax only (no network, no metrics)
python -m backtester.run --no-metrics
```

Outputs `data/singhania_backtest.xlsx` with sheets: Allocation, Projection,
GoalReconciliation, B4Metrics, MonteCarlo, Assumptions.

### Choosing your own stocks & quantities (`data/holdings.csv`)

Copy `data/holdings_template.csv` to `data/holdings.csv` and fill in one row per
holding, grouped by basket. Columns:

| column | meaning |
|---|---|
| `basket` | `B1`–`B4` |
| `ticker` | yfinance symbol for equities (e.g. `HAL.NS`); blank for bonds/cash |
| `name` | free-text label |
| `asset_class` | `equity_large` \| `equity_midsmall` \| `gsec` \| `bond` \| `gold` \| `sgb` \| `reit_invit` \| `cash` |
| `quantity` + `price` | shares/units × price per unit … |
| `value_inr` | … **or** the rupee value of the position directly |
| `return_override` | optional annual return fraction (blank = asset-class default) |
| `vol_override` | optional annual volatility fraction (blank = asset-class default) |

From this the backtester computes each basket's **initial value** (sum of
positions), **blended return** and **blended volatility** (value-weighted), then
runs projection / Monte Carlo / tax on *your* mix. Targets, target years and the
2029/2033 events stay fixed by the competition (in `config.py`).

### Where are Sharpe / Treynor / Jensen's Alpha / Beta?

Computed in `metrics.py` and printed as the **EQUITY METRICS** step of a run —
but only when (a) you don't pass `--no-metrics`, (b) there are equity tickers
(from `--holdings` or `--picks`), and (c) `yfinance` can fetch ~5y of monthly
prices. They need live market data, so run on a machine with open egress to
Yahoo Finance; in a blocked sandbox the step self-skips with a warning.

### Backtester layout

```
backtester/
  config.py       # ALL assumptions: baskets, returns, events, tax, withdrawals
  portfolio.py    # build baskets from YOUR holdings.csv (stocks/bonds + quantities)
  projection.py   # deterministic year-by-year projection to 2036 + goal recon
  metrics.py      # Beta / Sharpe / Treynor / Jensen's Alpha (market proxy ^NSEI)
  tax.py          # LTCG/STCG equity, slab debt tax, SGB exemption
  montecarlo.py   # N-path stochastic sim -> goal-achievement probability
  excel_export.py # structured .xlsx workbook for judges
  run.py          # orchestrator / CLI
```

`config.py` is the single source of truth for assumptions — edit returns, the
2029/2033 events, targets and tax rates there. `data/holdings.csv` is the single
source of truth for *what you actually hold*; nothing downstream hard-codes it.

---

This is step 1 of the broader backtester (data pipeline → screen → metrics →
projection → events → tax → Monte Carlo → Excel export).

## Screener Layout

```
screener/
  universe.py      # Nifty Total Market constituent list (NSE live, seed fallback)
  fundamentals.py  # yfinance fetch -> normalised fundamentals (+ cache)
  filters.py       # PURE functions: cap buckets, sector/cap/growth gates, scoring
  screen.py        # CLI orchestrator -> ranked CSV + console summary
data/
  nifty_total_market_seed.csv        # curated thesis-sector seed (used if NSE blocked)
  sample_fundamentals_SYNTHETIC.csv  # ILLUSTRATIVE data to demo the offline path
tests/
  test_filters.py  # unit tests for the screening logic (no network)
```

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
# Live: fetch the official NSE list + fundamentals from Yahoo Finance, then screen
python -m screener.screen

# Use the curated seed universe instead of fetching the NSE list
python -m screener.screen --no-nse

# Offline / reproducible: screen a CSV of already-fetched fundamentals
python -m screener.screen --input data/fundamentals_cache.csv

# Tune the shortlist
python -m screener.screen --target-count 15 --max-per-sector 3
```

Outputs: `data/b4_shortlist.csv` (ranked picks + justification metrics) and
`data/b4_scored.csv` (every name that cleared the gates).

## How the screen works

1. **Universe** — official Nifty Total Market list from NSE; falls back to a
   curated seed of thesis-sector names when NSE is unreachable.
2. **Sector gate** — keep only the six thesis sectors (Consumption, Financials,
   Industrials, Defence, Digital, Healthcare). Yahoo GICS sectors are mapped to
   these; the seed list tags Defence explicitly (Yahoo files it under Industrials).
3. **Market-cap gate** — drop micro-caps below `min_market_cap_cr`; tag each name
   large / mid / small by INR-crore cutoffs so the final mix spans `~11%` (large)
   and `~13%` (mid/small) return buckets per the competition baseline.
4. **Growth gate** — require at least N of {revenue growth, earnings growth, ROE}
   to clear their thresholds, plus loose leverage/valuation guardrails.
5. **Score** — weighted sum of z-scored growth + quality metrics.
6. **Select** — top names by score under a per-sector diversification cap.

All thresholds live in `ScreenConfig` (`screener/filters.py`) so they're auditable
and tunable in one place — useful for the Assumptions Sheet.

## Tests

```bash
python -m pytest tests/ -q
```

## ⚠️ Network note

`fundamentals.py` and `universe.py` need outbound access to Yahoo Finance and
nseindia.com. Some networks (incl. the remote sandbox this was built in) block
those hosts at the egress proxy (HTTP 403). When that happens:

- the universe loader logs a warning and falls back to the curated seed list, and
- the fundamentals fetcher reports the tickers it couldn't fetch instead of crashing.

To get **live data**, run on a machine with open egress to Yahoo Finance. To test
the pipeline without any network, use `--input` with a fundamentals CSV. The
`sample_fundamentals_SYNTHETIC.csv` file contains **illustrative, hand-made numbers
for plumbing tests only — not real market data**; do not use it for the actual
submission.
