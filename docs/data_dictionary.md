# Data dictionary

Warehouse: DuckDB file `data/warehouse.duckdb` (not committed), created from
`cac40val/warehouse/schema.sql`. A parquet copy of every table is committed in
`data/snapshot/<table>.parquet` and is what the Streamlit app reads.

Writes go through `warehouse.db.upsert`: rows matching the incoming natural key are deleted,
then the new rows are inserted, in one transaction. Re-running the pipeline is therefore
idempotent.

Row counts are from the snapshot of 12 November 2026.

| Table | Type | Grain (natural key) | Rows |
|---|---|---|---|
| `dim_company` | Dimension | `ticker` | 9 |
| `dim_date` | Dimension | `date` | 1,281 |
| `fact_financials` | Fact | `ticker`, `fiscal_year`, `line_item` | 580 |
| `fact_prices` | Fact | `ticker`, `date` | 12,689 |
| `fact_market_params` | Fact | `date` | 491 |
| `fact_fx` | Fact | `date`, `currency` | 2 |
| `fact_ai_extraction` | Fact | replaced per `ticker`, `fiscal_year`; one row per extracted item | 0 (cache empty) |

## dim_company

One row per company in `config/sources.yaml` (5 targets and 4 extra peers).

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `ticker` | VARCHAR | Yahoo Finance ticker, e.g. `MC.PA`. Natural key. | `config/sources.yaml` | None |
| `name` | VARCHAR | Company name | `config/sources.yaml` | None |
| `country` | VARCHAR | Country of listing. Currently always NULL (not populated). | — | — |
| `currency` | VARCHAR | Listing (trading) currency: EUR, CHF or HKD | `config/sources.yaml` | None |
| `sector` | VARCHAR | Sector label | Pipeline constant | Set to `Luxury & Consumer` for all rows |
| `is_target` | BOOLEAN | TRUE for the 5 companies valued, FALSE for comps-only peers | `config/sources.yaml` | None |

## dim_date

Calendar dimension covering every trading date present in `fact_prices`.

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `date` | DATE | Calendar date. Natural key. | `fact_prices.date` | Distinct dates |
| `year` | INTEGER | Calendar year | Derived | `date.year` |
| `month` | INTEGER | Month 1–12 | Derived | `date.month` |
| `quarter` | INTEGER | Quarter 1–4 | Derived | `date.quarter` |

## fact_financials

Annual financial statement items in long format, one row per company, fiscal year and line
item. Values are in full currency units (not millions).

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `ticker` | VARCHAR | Company ticker (FK to `dim_company`) | yfinance | None |
| `fiscal_year` | INTEGER | Calendar year of the fiscal period end | yfinance statement column | `Timestamp(period).year` |
| `line_item` | VARCHAR | Canonical line item (list below) | yfinance row label | Mapped by `ingest.market.LINE_ITEM_MAP`; when several labels map to one item, the first label in the map wins |
| `value` | DOUBLE | Amount in full units of `currency` | yfinance | `capex`, `interest_expense`, `tax_expense` stored as absolute values; `nwc` computed (see below) |
| `currency` | VARCHAR | Currency of `value` | `config/sources.yaml` | Copied from the company's configured currency (see methodology, limitations) |
| `source` | VARCHAR | Data provider | Pipeline | Always `yfinance` today; reserved for overrides and filings |

**Line items** (`line_item` values) and the yfinance labels they come from:

| line_item | yfinance label(s) | Statement |
|---|---|---|
| `revenue` | Total Revenue, Operating Revenue | Income |
| `ebit` | EBIT, Operating Income | Income |
| `ebitda` | EBITDA | Income |
| `da` | Reconciled Depreciation, Depreciation And Amortization In Income Statement | Income / cash flow |
| `capex` | Capital Expenditure (absolute value) | Cash flow |
| `tax_expense` | Tax Provision (absolute value) | Income |
| `pretax_income` | Pretax Income | Income |
| `interest_expense` | Interest Expense (absolute value) | Income |
| `gross_debt` | Total Debt | Balance |
| `cash` | Cash And Cash Equivalents | Balance |
| `minorities` | Minority Interest | Balance |
| `associates` | Investments In Other Ventures Under Equity Method | Balance |
| `shares_outstanding` | Ordinary Shares Number | Balance |
| `total_assets` | Total Assets | Balance |
| `total_liabilities` | Total Liabilities Net Minority Interest | Balance |
| `total_equity` | Stockholders Equity, Common Stock Equity | Balance |
| `nwc` | Computed: Receivables (or Accounts Receivable) + Inventory − Payables (or Accounts Payable). Fallback: Working Capital − Cash And Cash Equivalents. Missing inventory counts as 0. | Balance |

## fact_prices

Daily closing prices, five years of history, for all 9 companies and the Euro Stoxx 50
benchmark (`^STOXX50E`).

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `ticker` | VARCHAR | Company ticker or `^STOXX50E` | yfinance | None |
| `date` | DATE | Trading date | yfinance history index | Timezone removed, normalised to the date |
| `close` | DOUBLE | Closing price in listing currency | yfinance `Close` | Rows with a null close dropped. Used for the current price and the 52-week range. |
| `adj_close` | DOUBLE | Close adjusted for dividends and splits | yfinance `Adj Close` | Used for monthly returns in the beta regression |

## fact_market_params

Market-wide inputs to the cost of capital.

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `date` | DATE | Observation date (monthly ECB dates, plus one row at the valuation date) | ECB / pipeline | ECB `TIME_PERIOD` parsed as a date |
| `rf_oat10y` | DOUBLE | French 10-year government bond yield, decimal (0.0489 = 4.89%) | ECB Data Portal, series `IRS.M.FR.L.L40.CI.0000.EUR.N.Z` | Percent / 100; the valuation-date row repeats the latest value or `rf_override` |
| `erp_france` | DOUBLE | Equity risk premium for France, decimal | Damodaran country risk premiums, snapshotted in `data/reference/damodaran_erp.csv` with its download date | Same value on every row, or `erp_override` |

## fact_fx

FX rates used to convert non-EUR peers into EUR for comps.

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `date` | DATE | Valuation date | Pipeline | Latest benchmark trading date |
| `currency` | VARCHAR | ISO currency code (CHF, HKD) | `config/sources.yaml` and `fact_financials.currency` | Every non-EUR currency in use |
| `eur_per_unit` | DOUBLE | EUR value of 1 unit of `currency` | yfinance `<CUR>EUR=X` | Last close on or before the valuation date (10-day look-back) |

## fact_ai_extraction

Facts extracted by the LLM from the latest DEU. One row per guidance item, risk, segment and
one row for management tone. The cache is currently empty, so the table has no rows until the
extraction is run with an API key.

| Column | Type | Description | Source | Transformation |
|---|---|---|---|---|
| `ticker` | VARCHAR | Company ticker | Pipeline | None |
| `fiscal_year` | INTEGER | Latest fiscal year in `fact_financials` for the company | Pipeline | `max(fiscal_year)` |
| `field` | VARCHAR | Fact type: `guidance`, `risk`, `segment` or `tone` | Pipeline | One value per pydantic list |
| `value` | VARCHAR | Full validated item as JSON (e.g. metric, statement, direction, horizon, page for guidance) | LLM output | `model_dump_json()` of the pydantic item |
| `value_num` | DOUBLE | Numeric value: segment revenue in EUR millions; NULL for other fields | LLM output | Copied from `revenue_eur_m` |
| `page` | INTEGER | 1-based DEU page cited for the fact; NULL only for `tone` | LLM output | Validated: must be ≥ 1 and among the pages sent to the model |
| `model` | VARCHAR | LLM model identifier, e.g. `claude-sonnet-5-5` | `config/settings.yaml` | None |
| `extracted_at` | TIMESTAMP | UTC time of the extraction | Pipeline | `datetime.now(UTC)` |

## Files outside the warehouse

| File | Content | Producer |
|---|---|---|
| `data/raw/<source>/<UTC timestamp>.<ext>` | Raw API responses (yfinance statements, prices, FX; ECB CSV; DEU PDFs). Not committed. | `ingest` |
| `data/reference/damodaran_erp.csv` | `country`, `erp`, `source_date`, `source_url` | Manual snapshot |
| `data/ai_cache/<ticker>_<fiscal_year>.json` | Validated extraction, including `rejected_count` | `ai_extraction` |
| `data_quality_report.md` | Data-quality issues by severity | `warehouse.quality` |
| `outputs/valuations.json` | Per target: `ticker`, `price`, `scenarios` (bear/base/bull per share), `wacc`, `g`, `ev_base`, `upside_base`, `tv_gordon_vs_exit_gap`, `driver_sources` | `pipeline.write_outputs` |
