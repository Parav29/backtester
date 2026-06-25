# Singhania Portfolio — B4 Equity Screener

Stock screener for **B4 (Aarya's Growth Pool)** of the Singhania Family Portfolio
Management Competition. It pulls fundamentals for the Nifty Total Market universe
and filters/ranks candidates by **sector**, **market cap**, and **growth metrics**,
producing a shortlist where each name carries the data points needed to justify it.

This is step 1 of the broader backtester (data pipeline → screen → metrics →
projection → events → tax → Monte Carlo → Excel export).

## Layout
screener/
universe.py # Nifty Total Market constituent list (NSE live, seed fallback)
fundamentals.py # yfinance fetch -> normalised fundamentals (+ cache)
filters.py # PURE functions: cap buckets, sector/cap/growth gates, scoring
screen.py # CLI orchestrator -> ranked CSV + console summary
data/
nifty_total_market_seed.csv # curated thesis-sector seed (used if NSE blocked)
sample_fundamentals_SYNTHETIC.csv # ILLUSTRATIVE data to demo the offline path
tests/
test_filters.py # unit tests for the screening logic (no network)

## Install
```bash
pip install -r requirements.txt
```

Run
# Live: fetch the official NSE list + fundamentals from Yahoo Finance, then screen
python -m screener.screen

# Use the curated seed universe instead of fetching the NSE list
python -m screener.screen --no-nse

# Offline / reproducible: screen a CSV of already-fetched fundamentals
python -m screener.screen --input data/fundamentals_cache.csv

# Tune the shortlist
python -m screener.screen --target-count 15 --max-per-sector 3
Outputs: data/b4_shortlist.csv (ranked picks + justification metrics) and
data/b4_scored.csv (every name that cleared the gates).

How the screen works
Universe — official Nifty Total Market list from NSE; falls back to a
curated seed of thesis-sector names when NSE is unreachable.
Sector gate — keep only the six thesis sectors (Consumption, Financials,
Industrials, Defence, Digital, Healthcare). Yahoo GICS sectors are mapped to
these; the seed list tags Defence explicitly (Yahoo files it under Industrials).
Market-cap gate — drop micro-caps below min_market_cap_cr; tag each name
large / mid / small by INR-crore cutoffs so the final mix spans ~11% (large)
and ~13% (mid/small) return buckets per the competition baseline.
Growth gate — require at least N of {revenue growth, earnings growth, ROE}
to clear their thresholds, plus loose leverage/valuation guardrails.
Score — weighted sum of z-scored growth + quality metrics.
Select — top names by score under a per-sector diversification cap.
All thresholds live in ScreenConfig (screener/filters.py) so they're auditable
and tunable in one place — useful for the Assumptions Sheet.

Tests
python -m pytest tests/ -q
⚠️ Network note
fundamentals.py and universe.py need outbound access to Yahoo Finance and
nseindia.com. Some networks (incl. the remote sandbox this was built in) block
those hosts at the egress proxy (HTTP 403). When that happens:

the universe loader logs a warning and falls back to the curated seed list, and
the fundamentals fetcher reports the tickers it couldn't fetch instead of crashing.
To get live data, run on a machine with open egress to Yahoo Finance. To test
the pipeline without any network, use --input with a fundamentals CSV. The
sample_fundamentals_SYNTHETIC.csv file contains illustrative, hand-made numbers
for plumbing tests only — not real market data; do not use it for the actual
submission.
