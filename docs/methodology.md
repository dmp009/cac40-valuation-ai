# Valuation methodology

All values are in EUR. The valuation date is the latest trading date of the Euro Stoxx 50
benchmark in the warehouse (12 November 2026 for the committed outputs). The valuation engine
(`cac40val/valuation/`) is made of pure functions with no I/O; each formula below is
unit-tested.

## 1. Global parameters

| Parameter | Value | Source / where to change |
|---|---|---|
| Risk-free rate (rf) | 4.89% | Latest French 10-year government bond yield, ECB series `IRS.M.FR.L.L40.CI.0000.EUR.N.Z`; `rf_override` in `config/settings.yaml` |
| Equity risk premium (ERP) | 5.01% | Damodaran, France, snapshot in `data/reference/damodaran_erp.csv`; `erp_override` |
| Tax rate | 25.8% | French statutory corporate tax rate; `tax_rate` |
| Terminal growth (g) | 2.0% | `terminal_growth` |
| Beta benchmark | Euro Stoxx 50 (`^STOXX50E`) | `benchmark_ticker` |
| Beta window | 60 monthly returns, minimum 24 | `pipeline.BETA_MONTHS`, `wacc.MIN_BETA_OBSERVATIONS` |
| Forecast horizon | 5 years | `forecast.HORIZON` |
| Scenario spreads | ±3 pp revenue growth, ±2 pp EBIT margin | `forecast.GROWTH_SPREAD`, `MARGIN_SPREAD` |
| Verdict thresholds | ±10% base value vs price | `outputs/verdict.py` |

## 2. Cost of capital (WACC)

**Beta.** Month-end adjusted closes are converted to monthly returns for the stock and the
Euro Stoxx 50. The raw beta is the OLS slope over the last 60 aligned months:

    beta_raw = Cov(r_stock, r_index) / Var(r_index)

and is adjusted toward 1 (Blume):

    beta = 0.67 × beta_raw + 0.33

With fewer than 24 monthly observations the pipeline falls back to beta = 1.0 and logs a
warning.

**Cost of equity (CAPM).**

    Ke = rf + beta × ERP

**Cost of debt.** Pre-tax, from the latest interest expense over the average gross debt of the
last two fiscal years, floored at the risk-free rate:

    Kd = max(interest expense / average gross debt, rf)

(If gross debt is zero or missing, Kd = rf.) For all five targets the floor binds today, so
Kd = 4.89%.

**WACC.** Market value of equity (share price × shares outstanding) and book gross debt:

    WACC = E / (E + D) × Ke + D / (E + D) × Kd × (1 − t)

Results at the valuation date:

| Company | Beta (adjusted) | WACC |
|---|---|---|
| LVMH | 1.22 | 9.84% |
| Hermès | 1.31 | 11.32% |
| Kering | 1.31 | 8.01% |
| L'Oréal | 0.86 | 8.92% |
| EssilorLuxottica | 0.81 | 8.17% |

Kering's WACC is lower than LVMH's despite a similar beta because Kering carries much more
debt (44% of the WACC weights, against 16% for LVMH), and debt is cheaper
after tax.

## 3. Historical drivers

From `fact_financials`, pivoted to one column per line item, averaged over all available
fiscal years (four years, FY2022–FY2025, for the targets):

| Driver | Formula |
|---|---|
| Revenue growth | Mean of year-on-year revenue growth |
| EBIT margin | Mean of EBIT / revenue |
| D&A % sales | Mean of D&A / revenue |
| Capex % sales | Mean of capex / revenue |
| NWC % sales | Mean of operating NWC / revenue |
| Effective tax rate | Mean of tax expense / pre-tax income (reported only; the forecast uses the statutory rate) |

**Operating working capital.**

    NWC = trade receivables + inventory − trade payables

Cash is excluded on purpose. Cash is already deducted from debt in the equity bridge (net
debt), so leaving it in NWC would count it twice; and because the forecast charges the change
in NWC against free cash flow, every year of cash accumulation would wrongly reduce FCFF. When
yfinance does not provide receivables or payables, the fallback is reported working capital
minus cash; a missing inventory line counts as zero (relevant for service-like businesses).

## 4. Scenarios

- **Base.** Revenue growth and EBIT margin come from management guidance extracted by the AI
  step when available (percentages parsed from guidance statements on `revenue_growth` /
  `organic_growth` and `operating_margin` / `ebit_margin`; a range such as "5–7%" uses its
  midpoint). Otherwise they are the historical averages. D&A, capex and NWC percentages are
  always historical.
- **Bear / bull.** Base growth −/+3 pp and base EBIT margin −/+2 pp, flat over the five years.
- **Overrides.** `config/assumptions/<ticker>.yaml` can set `revenue_growth` and/or
  `ebit_margin` per scenario, either one value or a list of five yearly values:

  ```yaml
  base:
    revenue_growth: [0.03, 0.04, 0.05, 0.05, 0.05]
    ebit_margin: 0.22
  ```

- **Source labels.** Each driver is tagged `historical`, `guidance` or `override`. The tags are
  written to `outputs/valuations.json`, the Excel model and the app.

In the committed outputs no AI cache and no overrides exist, so every driver is `historical`.

## 5. Forecast and free cash flow

For each year t = 1..5, starting from the latest actual revenue and NWC:

    Revenue_t = Revenue_{t-1} × (1 + growth_t)
    EBIT_t    = Revenue_t × margin_t
    D&A_t     = Revenue_t × D&A%
    Capex_t   = Revenue_t × capex%
    NWC_t     = Revenue_t × NWC%
    ΔNWC_t    = NWC_t − NWC_{t-1}
    FCFF_t    = EBIT_t × (1 − t) + D&A_t − Capex_t − ΔNWC_t
    EBITDA_t  = EBIT_t + D&A_t

Year-1 ΔNWC is measured against the latest actual NWC, so a gap between the actual NWC ratio
and the historical average shows up in year 1.

## 6. Terminal value and enterprise value

**Gordon growth (used in the valuation).**

    TV = FCFF_5 × (1 + g) / (WACC − g)        (requires WACC > g)

**Enterprise value** (end-of-year discounting):

    EV = Σ_{t=1..5} FCFF_t / (1 + WACC)^t + TV / (1 + WACC)^5

**Exit-multiple cross-check (reported, not used).**

    TV_exit = EBITDA_5 × peer median EV/EBITDA
    gap     = (TV_Gordon − TV_exit) / TV_exit

| Company | Gordon vs exit gap |
|---|---|
| LVMH | −53% |
| Hermès | −55% |
| Kering | −48% |
| L'Oréal | −39% |
| EssilorLuxottica | −39% |

A large negative gap means the market prices these companies on multiples that imply either
much higher long-term growth or a lower discount rate than the DCF assumes. It is the main
reason the DCF values sit below the share prices (see section 10).

## 7. Equity bridge

    Equity value = EV − net debt − minority interests + associates
    Net debt     = gross debt − cash and cash equivalents   (negative = net cash)
    Value per share = equity value / shares outstanding

All balance-sheet items are the latest fiscal year. Missing minorities or associates are set to
zero and logged.

## 8. Sensitivity

The base-case value per share is recomputed on a 5 × 5 grid:

- WACC: −100, −50, 0, +50, +100 bp around the computed WACC;
- g: −50, −25, 0, +25, +50 bp around 2.0%.

Cells where WACC ≤ g are left blank.

## 9. Trading comparables

**Peer universe (9 companies).** The 5 targets plus Richemont (`CFR.SW`), Moncler
(`MONC.MI`), Prada (`1913.HK`) and Brunello Cucinelli (`BC.MI`).

**Currency.** Prices are converted with the EUR rate of the listing currency on the valuation
date; financials with the EUR rate of their reporting currency, recorded in
`fact_financials.currency`. The two differ for Richemont (listed in CHF) and Prada (listed in
HKD): both report in euros, so only their share prices are converted. The reporting currency
comes from yfinance (`financialCurrency`), with `reporting_currency` in `config/sources.yaml`
as the fallback.

**Multiples** (latest fiscal year):

    EV        = market cap + net debt + minority interests
    EV/Sales  = EV / revenue
    EV/EBITDA = EV / EBITDA
    P/E       = market cap / (pre-tax income − tax expense)

A multiple is NaN when its denominator is zero, negative or missing, so loss-making years do
not distort the statistics.

**Exclusion rule.** A target is always excluded from its own peer set (8 peers remain). In the
app, a toggle also excludes L'Oréal and EssilorLuxottica, which are premium consumer rather
than pure luxury businesses (6 peers remain).

**Statistics and implied values.** For each multiple: first quartile, median, third quartile
and number of valid peers. Implied value per share:

    EV multiples: (multiple × target metric − net debt − minorities) / shares
    P/E:          (multiple × target net income) / shares

with low / mid / high from Q1 / median / Q3.

## 10. Football field and verdict

The football field shows, per target:

- DCF: bear to bull value per share;
- Trading comps: EV/EBITDA implied value, Q1 to Q3;
- 52-week range of the closing price (last 252 trading days);
- the current price as a vertical line.

**Verdict**: base DCF value more than 10% above the price is *Undervalued*, more than 10%
below is *Overvalued*, otherwise *Fairly valued*.

**Why the DCF values are below market prices.** In the committed run all five targets come
out *Overvalued*. The drivers are visible and each one is a deliberate, adjustable choice:

1. A 4.89% risk-free rate (the latest monthly OAT observation) and a 5.01% ERP give a high
   cost of equity, and betas of 1.2–1.3 against the Euro Stoxx 50 for LVMH, Hermès and Kering
   increase it further.
2. g = 2% is an inflation-like perpetual growth rate. Luxury leaders trade at roughly 16–23× EBITDA
   (Hermès, L'Oréal, Richemont), which implies more long-term growth or more pricing power
   than a 2% Gordon model gives credit for. The −39% to −55% Gordon vs exit gap measures
   this.
3. Drivers are four-year historical averages. Kering's revenue fell from €20.4bn in FY2022 to
   €14.7bn in FY2025 (−10% a year on average), so its base case extends that decline for five
   more years.
4. Five flat forecast years then perpetuity: there is no fade period where high margins
   converge slowly, which penalises high-growth names such as Hermès.

The comps range and the 52-week range on the same chart show where the market sits; the gap
between methods is the useful output for discussion.

## Limitations

- **Short history.** yfinance returns about four annual periods for European issuers, so the
  "historical average" is a four-year average, sensitive to one unusual year.
- **AI extraction not yet run.** The extraction, validation and caching are implemented and
  tested with a recorded response, but `data/ai_cache/` is empty until
  `python -m cac40val.pipeline --refresh` is run with `ANTHROPIC_API_KEY`. Until then the base
  case is purely historical and `fact_ai_extraction` is empty.
- **No DEU URLs configured.** `deu_url` is null in `config/sources.yaml`; the URLs of the
  latest DEUs must be added before the first extraction run.
- **Associates missing.** yfinance does not return equity-accounted investments for any of the
  companies; they are treated as zero (a warning in the data-quality report).
- **Balance-sheet identity.** For LVMH, Kering and EssilorLuxottica, total assets differ from
  liabilities plus equity by 1–2.3% in the yfinance data (mainly how minority interests are
  classified). Flagged as warnings.
- **Comps on the latest fiscal year.** Multiples use the latest annual figures, not a true
  trailing-twelve-months or forward figure; no consensus estimates are used.
- **Not pure luxury.** L'Oréal (beauty) and EssilorLuxottica (eyewear and medical optics) are
  premium consumer companies with different growth and margin profiles. They are valued with
  the same method and kept in the peer set by default; the app toggle removes them from comps.
- **Statutory tax rate.** The forecast uses 25.8% for all companies, although a large part of
  their profit is earned outside France.
- **Simplifications.** End-of-year discounting, flat drivers over five years, no explicit
  treatment of leases, pensions or share buybacks.
