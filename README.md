# Singhania Portfolio Backtester

A backtester for the **PMC '26 Singhania Family Portfolio Management Competition**.

It takes your chosen investments (stocks, bonds, gold, REITs), projects them over 10 years (2026–2036), handles the two competition events, computes taxes, runs 1,000 Monte Carlo simulations, and exports a ready-to-submit Excel workbook.

---

## Quick Start (3 Steps)

### Step 1: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 2: Add your holdings

Open `data/holdings.csv` and fill in your actual investments. Each row is one holding, tagged with the basket it belongs to (`B1`–`B4`).

```
basket,ticker,name,asset_class,quantity,price,value_inr,return_override,vol_override
B1,,Liquid fund,gsec,,,1200000,,
B2,,AAA corporate bonds,bond,,,3550000,,
B3,,Long G-Sec 2036,gsec,,,2000000,,
B4,HAL.NS,Hindustan Aeronautics,equity_large,300,4900,,,
```

**Column guide:**

| Column | What to fill | Required? |
|---|---|---|
| `basket` | `B1`, `B2`, `B3`, or `B4` | Yes |
| `ticker` | Yahoo Finance symbol (e.g. `HAL.NS`) — only for stocks | Only for stocks |
| `name` | Any label you want | Optional |
| `asset_class` | Type of investment (see below) | Yes |
| `quantity` | Number of shares/units | Either qty+price… |
| `price` | Price per share/unit in ₹ | …or value_inr |
| `value_inr` | Total ₹ value of the position | Either this or qty+price |
| `return_override` | Custom annual return (e.g. `0.12` = 12%) | Optional |
| `vol_override` | Custom annual volatility | Optional |

**Allowed asset classes:** `equity_large`, `equity_midsmall`, `gsec`, `bond`, `gold`, `sgb`, `reit_invit`, `cash`

> **Tip:** For stocks, use `quantity × price`. For bonds/gold/REITs, just put the total ₹ amount in `value_inr`. Add as many rows as you want — there's no limit.

### Step 3: Run the backtester

```bash
python -m backtester.run --holdings data/holdings.csv
```

This will:
1. Read your holdings and compute each basket's blended return
2. Project all 4 baskets year-by-year to 2036
3. Apply the 2029 RBI rate-cut and 2033 defence events
4. Handle the ₹50L property withdrawal in 2031
5. Calculate taxes (LTCG/STCG/debt)
6. Run 1,000 Monte Carlo simulations
7. Compute equity metrics (Beta, Sharpe, Treynor, Jensen's Alpha) for your stocks
8. Generate `data/singhania_backtest.xlsx`

---

## Understanding the Output

### Goal Reconciliation
Shows whether each basket hits its competition target:

| Basket | Goal | Target |
|---|---|---|
| B1 — Liquidity | ₹20L accessible by 2028 | Safety net |
| B2 — Property | ₹50L withdrawn in 2031 | Property purchase |
| B3 — Vikram | ₹1.5 Cr by 2036 | Retirement corpus |
| B4 — Aarya | ₹2 Cr by 2036 | Growth pool |

### Monte Carlo
Shows the probability of meeting each goal across 1,000 random market scenarios. Higher % = more robust plan.

### Equity Metrics (Bonus)
Computed from 5 years of real Yahoo Finance price data for your stock holdings:
- **Beta** = sensitivity to market (Nifty 50)
- **Sharpe Ratio** = return per unit of risk
- **Treynor Ratio** = return per unit of market risk
- **Jensen's Alpha** = excess return over CAPM prediction

### Excel Workbook
`data/singhania_backtest.xlsx` contains 6 sheets: Allocation, Projection, GoalReconciliation, B4Metrics, MonteCarlo, Assumptions.

---

## Project Structure

```
backtester/
  config.py        # ALL assumptions: returns, events, tax rates, targets
  portfolio.py     # Reads holdings.csv → builds baskets
  projection.py    # Year-by-year projection to 2036
  metrics.py       # Beta / Sharpe / Treynor / Jensen's Alpha
  tax.py           # LTCG / STCG / debt tax
  montecarlo.py    # 1,000-path stochastic simulation
  excel_export.py  # Generates the .xlsx workbook
  run.py           # CLI orchestrator

screener/          # (Optional) Stock screener for finding B4 equity picks

data/
  holdings_template.csv  # Template — copy to holdings.csv
  holdings.csv           # YOUR investments (you edit this)
  singhania_backtest.xlsx # Generated output
```

---

## Customising the Model

All competition assumptions live in `backtester/config.py`:
- Basket targets and target years
- Baseline return assumptions (Rf, Rm, large-cap, mid/small, G-Sec, etc.)
- Event shocks (2029 rate cut, 2033 defence re-rating)
- Tax rates
- Withdrawal schedule

Edit `config.py` if you want to change the event shocks or add new events. Edit `data/holdings.csv` to change what you're investing in.

---

## Other Commands

```bash
# Run without equity metrics (no internet needed)
python -m backtester.run --holdings data/holdings.csv --no-metrics

# Run with more Monte Carlo paths for smoother probabilities
python -m backtester.run --holdings data/holdings.csv --sims 5000

# Run unit tests
python -m pytest tests/ -q
```
