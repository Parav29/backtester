# Methodology — Singhania Portfolio Model

This document explains **exactly what the model does, how each number is
calculated, and how it maps to the competition problem statement**. It is the
written companion to the code in `backtester/` and is meant to be readable by a
judge who never opens the source.

> **What this is.** A forward **goal-projection & reconciliation engine** for the
> Singhania four-basket portfolio, plus the three bonus deliverables (equity risk
> metrics, tax treatment, Excel model).
>
> **What this is not.** It is *not* a security screener (you select securities
> yourself) and it is *not* a classical historical backtester. Only the equity
> **metrics** module uses historical price data; the projection uses the
> competition's *forward* return anchors. Think "Goal Reconciliation calculator,"
> not "trading-strategy replay."

---

## 1. How it maps to the problem statement

| PS requirement | Where the model covers it | Status |
|---|---|---|
| Goal Reconciliation (projections, honest shortfall) | `projection.py`, `montecarlo.py` | Required — covered |
| Response to Events (2029, 2033) | event shocks + transfers in `config.py`, applied by `projection.py`/`montecarlo.py` | Required — *quantified*; you still write the reasoning |
| Portfolio Construction (baskets, allocation) | `portfolio.py` builds baskets from your `holdings.csv` | Supporting |
| Selection Methodology (2 data points/security) | **not in scope** — this is your written analysis | You |
| Investment Philosophy | **not in scope** — your narrative | You |
| Bonus: equity metrics (Beta/Sharpe/Treynor/Jensen) | `metrics.py` | Bonus — covered |
| Bonus: tax treatment (LTCG/STCG/debt) | `tax.py` | Bonus — covered |
| Bonus: Excel model | `excel_export.py` | Bonus — covered |
| Mandatory Assumptions Sheet | `config.py` is the single source; mirrored to the Excel "Assumptions" tab | Covered |

---

## 2. The four baskets (Portfolio Construction)

The ₹1.5 cr is **one consolidated portfolio** organised internally into four
goal-baskets — exactly the "separate naturally into baskets" structure the PS
asks for:

| Basket | Purpose | Target | By |
|---|---|---|---|
| **B1** | Liquidity buffer | ₹20 L *available* | 2028 |
| **B2** | Property purchase | ₹50 L *withdrawn* | 2031 |
| **B3** | Vikram's retirement (preservation) | ≥ ₹1.5 cr | 2036 |
| **B4** | Aarya's growth pool | ≥ ₹2 cr | 2036 |

Targets, target years, the events, and the withdrawal are **fixed by the
competition** and live in `config.py`. What you choose — the actual securities and
amounts — lives in `data/holdings.csv`.

### How a basket's numbers are derived from your holdings (`portfolio.py`)

For each row in `holdings.csv`:

```
position value = value_inr            (if given)
              = quantity × price       (otherwise)
```

Then per basket:

```
initial            = Σ position values in the basket
blended_return     = Σ (weightᵢ × returnᵢ)      # value-weighted
blended_volatility = Σ (weightᵢ × volᵢ)         # value-weighted (see caveat §7)
weightᵢ            = valueᵢ / basket total
```

`returnᵢ` / `volᵢ` come from the asset class (table in §6) unless you set
`return_override` / `vol_override` on that row. This is what keeps the model
**honest**: if B3 holds only G-Secs and bonds, its blended return comes out at
~7–8%, not an invented 13%.

---

## 3. Deterministic projection (`projection.py`)

The base-case ("expected") path. Starting from each basket's 2026 value, step one
year at a time from 2026→2036. **Each year, in this order:**

1. **Grow:** `value × (1 + blended_return)`
2. **Event value-shock** (only in 2029 / 2033): `value × shock` (e.g. ×1.04)
3. **Event transfer** (only in 2029 / 2033): move ₹ between baskets
4. **Withdrawal** (only 2031): subtract the ₹50 L property outflow from B2

**Goal reconciliation** then compares, per basket:
- B1/B2 → the amount *available/withdrawn* at the target year
- B3/B4 → the *projected balance* at 2036

against the target, and reports surplus/shortfall and a met/not-met flag. This is
the "clear demonstration, with projections, of how the portfolio serves all four
goals, and an honest account of any shortfall" the PS requires.

**Overall CAGR** is reported as
`(final_total + withdrawals_captured) / initial_corpus) ^ (1/10) − 1`.

---

## 4. Response to Events (how they are modelled)

The PS gives two macro events; the model encodes a *conservative, explicit*
financial consequence for each (you must still justify these in words):

| Year | Event | Modelled as | Rationale to defend |
|---|---|---|---|
| 2029 | RBI cuts repo 5.25%→3.5% | B3 value **×1.04** + move **₹8 L B1→B3** | Long-duration G-Secs in B3 post a one-off capital gain as yields fall; with rates low, park part of the (now less-needed) liquidity buffer into longer income instruments before reinvestment rates drop further |
| 2033 | India a major defence exporter | B4 value **×1.06** | Defence/aerospace sleeve in B4 re-rates modestly; book partial profits |

> **These shocks are assumptions, not facts.** The PS penalises "aggressive or
> unjustified" numbers, so the +4% / +6% are deliberately small and must be
> defended in the Assumptions Sheet — or replaced with your own reasoning.
> The most defensible use of Event 2 is to **rotate booked B4 gains into B3's
> income instruments**, which simultaneously addresses the structural shortfall
> in §8.

Rebalancing is restricted to the two event years (`REBALANCE_YEARS`), matching
the PS constraint.

---

## 5. Equity risk metrics (`metrics.py`) — the bonus

Computed **only on the equity sleeve** (B4 and any other equity holdings), using
**5 years of monthly price data** from Yahoo Finance, with the **Nifty 50
(`^NSEI`)** as the market proxy. Formulas (matching the PS exactly):

```
monthly return      rₜ = ln(Pₜ / Pₜ₋₁)
annualised return   R  = (1 + mean(r))¹² − 1

Betaᵢ            = Cov(stockᵢ, market) / Var(market)
Portfolio Beta   βp = Σ weightᵢ · Betaᵢ
Portfolio σp     = stdev(weighted monthly returns) × √12
Sharpe           = (Rp − Rf) / σp
Treynor          = (Rp − Rf) / βp
Jensen's Alpha   = Rp − [Rf + (Rm − Rf) · βp]
```

`Rf = 6%` and `Rm = 10.70%` are the **competition-mandated** anchors (not the
realised sample values), so the ratios are comparable across submissions. The
realised 5y market return is reported separately for reference.

> Requires live market data. On a network that blocks Yahoo Finance the step
> self-skips with a warning — run it on an open connection to populate the metrics.

---

## 6. Asset-class return & volatility anchors (`config.py`)

Returns are the **mandated baseline**; volatilities are our own conservative
estimates (flagged as assumptions, since the PS does not mandate them).

| Asset class (holdings tag) | Return | Vol (assumed) |
|---|---|---|
| `equity_large` | 11.0% | 18% |
| `equity_midsmall` | 13.0% | 24% |
| `gsec` | 6.5% | 5% |
| `bond` (AAA) | 7.5% | 4% |
| `gold` / `sgb` | 8.0% | 15% |
| `reit_invit` | 8.5% | 12% |
| `cash` | 6.0% | 0.5% |

---

## 7. Tax treatment (`tax.py`) — the bonus

Applied at exit/withdrawal milestones to get net-of-tax proceeds:

| Asset | Rule |
|---|---|
| Equity LTCG (>1 yr) | 12.5% on gains above the ₹1.25 L/yr exemption |
| Equity STCG (<1 yr) | 20% |
| Debt / G-Sec / bond | 30% (slab; Singhanias assumed top slab) |
| SGB (held to maturity) | **Exempt** |

Each basket's tax bucket is inferred from its dominant asset class
(`basket_tax_classes`), so the property withdrawal (B2, debt) and the B4 equity
exit are taxed correctly.

---

## 8. Monte Carlo (`montecarlo.py`) — robustness add-on

Beyond the single expected path, this answers *"how likely is each goal,
accounting for return variability?"* Each basket grows each year by a random draw
`~ Normal(blended_return, blended_vol)`; events and the withdrawal apply exactly
as in §3; we run N paths (default 1000) and report:

- **P(goal met)** per basket = fraction of paths clearing the target
- **percentile bands** (p5/p25/p50/p75/p95) of each basket's 2036 value

This is *not* required by the PS — it is a credibility add-on showing the base
case isn't a fluke. The gap between "base case met ✓" and a P(goal) near 50% is
itself a finding worth discussing.

---

## 9. Key assumptions & honest limitations

1. **Forward projection, not a historical backtest.** Growth uses mandated
   forward anchors. Only §5 metrics use historical prices.
2. **Value-weighted volatility ignores correlation** → it *overstates* basket
   risk (conservative). A full covariance treatment would raise the goal
   probabilities slightly.
3. **Monte Carlo uses i.i.d. annual Normal returns and independent baskets** — a
   simplification, not a true joint distribution of Indian asset returns.
4. **Event shocks (+4% / +6%) are modelling choices** that must be justified or
   replaced.
5. **The four goals over-subscribe the ₹1.5 cr corpus** at honest mandated
   returns (see below). This is a *feature of the problem*, not a bug in the
   model — and disclosing it is explicitly rewarded.

### The central tension (worked backward at honest returns)

| Goal | Target | Return used | ₹ needed in 2026 |
|---|---|---|---|
| B1 (2028) | ₹20 L | 6.2% | ~₹17.7 L |
| B2 (2031) | ₹50 L | 7.5% | ~₹34.8 L |
| B3 (2036) | ₹1.5 cr | ~8% (preservation cap) | ~₹69.5 L |
| B4 (2036) | ₹2 cr | ~12.5% | ~₹61.6 L |
| | | **Total** | **~₹183.6 L vs ₹150 L** |

The ~₹33 L gap is the heart of the mandate: Vikram's preservation goal (capped at
~8–9% instruments) and Aarya's ₹2 cr growth goal cannot both be fully funded from
₹1.5 cr at mandated returns. Your submission must **reason** about how to close or
disclose it — e.g. lean B3 toward the REIT/InvIT high end, route B4's 2033
defence-rerating gains into B3, or honestly report a controlled shortfall on the
least-binding goal.

---

## 10. How to use it for the submission

```bash
# 1. List your chosen securities + amounts
cp data/holdings_template.csv data/holdings.csv   # then edit it

# 2. Run the full model (metrics need open Yahoo Finance access)
python -m backtester.run --holdings data/holdings.csv

# 3. Read the console output AND data/singhania_backtest.xlsx
```

The Excel workbook (Allocation, Projection, GoalReconciliation, B4Metrics,
MonteCarlo, Assumptions) is the artefact you attach to the PDF. The Assumptions
tab is generated straight from `config.py`, so it can never drift from the numbers
actually used.
