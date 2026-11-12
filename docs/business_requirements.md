# Business requirements

## 1. Context

A mid-market M&A advisory team regularly prepares valuation views on large listed French
companies, for pitch books, fairness discussions or as a reference point for private
transactions in the same sector. For each company the team needs the same building blocks:
clean historical financials, a cost of capital, a DCF with scenarios, trading comparables and
a summary of what management says about outlook and risks.

Today this work is manual. Data is copied from data providers and annual reports into Excel,
the 400-page *Document d'Enregistrement Universel* (DEU) is read by hand, and every company
model is built slightly differently. The result is slow, hard to review and hard to reproduce.

**Objective.** Provide a repeatable, documented pipeline that produces a first valuation view
for the five CAC 40 luxury and premium-consumer companies (LVMH, Hermès, Kering, L'Oréal,
EssilorLuxottica) in minutes, with every number traceable to its source and every assumption
visible and overridable by the analyst.

**Out of scope.** Real-time data, precedent-transaction comps (no reliable free data source),
a chatbot over filings, user accounts.

## 2. Stakeholders

| Stakeholder | Role in the deal team | What they need from the tool | Involvement |
|---|---|---|---|
| M&A analyst | Builds the models and the slides | Clean data, a working model to start from, the ability to change drivers quickly | Primary user, daily |
| Associate | Reviews and challenges the analyst's work | Transparent assumptions with sources, consistent methodology across companies, sensitivity tables | Reviewer, weekly |
| Managing Director (MD) | Owns the client relationship and the final view | A one-page answer: value range vs share price and the main risks | Consumer of outputs, per deal |
| Data / IT owner | Maintains data sources and the codebase | Documented data model, data-quality checks, tests and CI | Maintainer |
| Compliance | Controls what leaves the team | Disclaimer, public sources only, no personal data | Sign-off |

## 3. User stories and acceptance criteria

**US-1 Collect data automatically.**
As an M&A analyst, I want market prices, financial statements, the risk-free rate, the equity
risk premium and FX rates to be collected in one command, so that I stop copying numbers by
hand.

- `make pipeline` loads all 9 companies (5 targets, 4 extra peers) into the warehouse.
- Every raw API response is saved with a UTC timestamp under `data/raw/<source>/`.
- A failed source for one company is logged and does not stop the other companies.

**US-2 Trust the data.**
As an associate, I want automated data-quality checks with a written report, so that I know
which numbers to challenge before I review a model.

- Checks run on every pipeline run: non-null keys, positive revenue, balance-sheet identity
  (assets = liabilities + equity within 1%), one currency per company, missing line items.
- Results are written to `data_quality_report.md` with severity (error / warning), check,
  ticker and detail.
- No check failure is silently ignored: an empty report says "No issues found".

**US-3 Value a company with a DCF and scenarios.**
As an M&A analyst, I want a DCF with bear, base and bull scenarios and a WACC computed from
market data, so that I get a value range rather than a single point.

- WACC uses the French 10-year OAT, a regression beta against the Euro Stoxx 50 and the
  Damodaran France ERP; each input is shown in the Excel WACC tab.
- Bear and bull differ from base by −/+3 pp revenue growth and −/+2 pp EBIT margin.
- The equity value per share is reported for each scenario, with a WACC × terminal growth
  sensitivity grid.
- The engine's formulas are unit-tested against a hand-calculated reference case.

**US-4 Compare with trading peers.**
As an associate, I want EV/Sales, EV/EBITDA and P/E multiples for the peer group and the
implied value range for each target, so that I can check the DCF against how the market
prices similar companies.

- Multiples are computed in EUR; non-EUR peers are converted at the valuation-date FX rate.
- The target is excluded from its own peer statistics; median and interquartile range are
  shown with the number of valid peers.
- A multiple is left blank (not zero) when its denominator is negative or missing.
- The analyst can exclude L'Oréal and EssilorLuxottica from the peer set in the app.

**US-5 Get guidance and risks from the annual report, with proof.**
As an M&A analyst, I want guidance, risk factors and segment revenue extracted from the DEU
with page references, so that I save reading time without losing the ability to verify.

- Every extracted fact cites a page; facts without a page, or citing a page that was not sent
  to the model, are rejected and counted.
- Segment revenues are cross-checked against reported revenue (±2%); a mismatch is an error
  in the data-quality report.
- Results are cached in `data/ai_cache/`; without an API key the pipeline runs from the cache
  and never calls the API.

**US-6 Override assumptions.**
As an associate, I want to override any forecast driver and see where each driver comes from,
so that the final view reflects the team's judgement and not only the data.

- Drivers can be set per scenario in `config/assumptions/<ticker>.yaml` (single value or one
  value per forecast year).
- Each driver is labelled `historical`, `guidance` or `override` in `outputs/valuations.json`
  and in the app.
- Risk-free rate and ERP can be overridden in `config/settings.yaml`.

**US-7 One-page summary for the MD.**
As a Managing Director, I want a one-page PDF per company with the value range, the football
field, the top risks and a verdict versus the share price, so that I can form a view in two
minutes.

- One PDF per target in `outputs/<ticker>/`, A4, one page.
- The verdict rule is stated on the page: base value more than 10% above price is
  undervalued, more than 10% below is overvalued, otherwise fairly valued.
- The page states that it is not investment advice.

**US-8 Explore and stress-test interactively.**
As an M&A analyst, I want an interactive app where I change growth and margin and see the
value and sensitivity update, so that I can answer "what do you need to believe?" questions
in a meeting.

- The app lets the user pick a company and a scenario and move revenue growth and EBIT margin
  sliders; the DCF value and the sensitivity heatmap recompute immediately.
- The app shows the football field, the comps, the AI extraction with page numbers and the
  data-quality report.
- The app runs from the committed snapshot, without network access or an API key.

## 4. KPI definitions

All amounts in EUR. "Latest" means the latest fiscal year available in the warehouse.

| KPI | Definition | Formula | Where used |
|---|---|---|---|
| Enterprise value (EV), DCF | Present value of the five forecast free cash flows to the firm plus the discounted terminal value | Σ FCFF_t / (1+WACC)^t + TV / (1+WACC)^5, with TV = FCFF_5 × (1+g) / (WACC − g) | DCF, Excel DCF tab |
| Enterprise value, market | Market value of the operating business | Market cap + net debt + minority interests | Comps |
| Net debt | Financial debt less cash | Gross debt − cash and cash equivalents (negative = net cash) | Equity bridge, comps |
| Equity value per share | Value attributable to one ordinary share | (EV − net debt − minorities + associates) / shares outstanding | Results table, one-pager |
| Upside % | Gap between base DCF value and share price | Base value per share / share price − 1 | Results table, verdict |
| WACC | Weighted average cost of capital, market-value weights | E/(D+E) × Ke + D/(D+E) × Kd × (1 − t), Ke = rf + β × ERP | DCF discount rate |
| EV/EBITDA | Market EV over latest EBITDA | EV / EBITDA (blank if EBITDA ≤ 0) | Comps, exit-multiple cross-check |
| EV/Sales | Market EV over latest revenue | EV / revenue | Comps |
| P/E | Market cap over latest net income | Market cap / (pre-tax income − tax expense) | Comps |
| Verdict | Classification of base value vs price | > +10% Undervalued, < −10% Overvalued, else Fairly valued | Results table, one-pager, Excel |
| Gordon vs exit-multiple gap | How far the Gordon terminal value is from a market-multiple terminal value | (TV_Gordon − TV_exit) / TV_exit, TV_exit = EBITDA_5 × peer median EV/EBITDA | Model sanity check |
