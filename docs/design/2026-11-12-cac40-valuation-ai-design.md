# CAC 40 Luxury Valuation AI — Design Spec

Date: 2026-11-12 · Status: draft for review

## 1. Purpose

**Business problem.** An M&A / equity analyst spends days reading a 400-page *Document
d'Enregistrement Universel* (DEU) and building a DCF. This tool automates data collection,
extraction and valuation mechanics, while keeping the analyst in control of the assumptions.

**Portfolio goal.** Show French recruiters (M&A / valuation, corporate finance, DAIS data and
business-analyst roles) three skills in one repo: rigorous corporate finance, data engineering
and BI with governance, and practical, validated use of LLMs.

**Success criteria**
- Valuation of 5 CAC 40 luxury companies with DCF (3 scenarios), trading comps and a football field.
- A recruiter can clone and run the full pipeline **without any API key** (cached AI outputs).
- A live Streamlit app is linkable from the CV.
- CI is green: financial formulas and data-quality checks are tested.
- The README explains the business problem first and has a French summary.

## 2. Scope

**Targets (valued):** LVMH `MC.PA`, Hermès `RMS.PA`, Kering `KER.PA`, L'Oréal `OR.PA`,
EssilorLuxottica `EL.PA`.

**Comparable peers (comps only):** the 5 targets + Richemont `CFR.SW`, Moncler `MONC.MI`,
Prada `1913.HK`, Brunello Cucinelli `BC.MI`.

**Out of scope (YAGNI):** Q&A chatbot over filings (that is project 3), real-time data,
user accounts, precedent-transaction comps (no free reliable data source).

## 3. Architecture

```
ingest/  ──►  warehouse/ (DuckDB)  ──►  valuation/  ──►  outputs/
                    ▲                       ▲
              ai_extraction/ ───────────────┘
```

Each layer is a Python package with one responsibility and a small public interface.
All layers are orchestrated by `make pipeline` (or `python -m cac40val.pipeline`).

### 3.1 Ingestion (`cac40val/ingest/`)

| Source | Data | Method |
|--------|------|--------|
| yfinance | Prices (5y, daily), income statement, balance sheet, cash flow (annual), shares outstanding | `yfinance` |
| ECB Data Portal API | French 10y OAT yield (risk-free rate) | HTTP, SDMX/CSV |
| Damodaran (NYU Stern) | Country equity risk premium for France | Annual Excel file, snapshotted into `data/reference/` with download date |
| Company IR websites | Latest DEU (PDF) per target | URLs listed in `config/sources.yaml`; script downloads to `data/raw/deu/` (gitignored, large) |
| Euro Stoxx 50 index | Benchmark for beta regression | yfinance `^STOXX50E` |

Raw pulls are saved to `data/raw/` with a timestamp, so every number is traceable (lineage).
yfinance gaps for non-US companies are expected: the ingest step records missing fields
rather than failing, and the data-quality layer reports them.

### 3.2 Warehouse (`cac40val/warehouse/`)

DuckDB file `data/warehouse.duckdb`, star schema:

- `dim_company` (ticker, name, country, currency, sector, is_target)
- `dim_date`
- `fact_financials` (ticker, fiscal_year, line_item, value, currency, source)
- `fact_prices` (ticker, date, close, adj_close)
- `fact_market_params` (date, rf_oat10y, erp_france)
- `fact_ai_extraction` (ticker, fiscal_year, field, value, page, model, extracted_at)

**Data quality (pandera schemas):** non-null keys, positive revenue, balance sheet identity
within tolerance (assets ≈ liabilities + equity), currency consistency, and a cross-check
that AI-extracted segment revenues sum to the reported total revenue (±2%). Failures go to a
`data_quality_report.md` and do not silently pass.

**Currency:** all valuations in EUR. Non-EUR peers (CHF, HKD) are converted at the FX rate on
the valuation date (yfinance FX tickers) for multiples only.

### 3.3 AI extraction (`cac40val/ai_extraction/`)

- PDF parsed with `pymupdf`, page by page, keeping page numbers.
- Relevant sections located by keyword search (e.g. "perspectives", "outlook", "facteurs de
  risque", "risk factors", "segment") to limit tokens, then sent to the LLM.
- **Provider-agnostic interface:** `LLMClient.extract(prompt, schema) -> pydantic model`.
  Default implementation: Anthropic Claude API (model set in `config/settings.yaml`).
  A second adapter can be added without changing callers.
- **Structured output (pydantic):**
  - `guidance`: list of {metric, statement, direction, horizon, page}
  - `risks`: list of {category, description, severity 1-5, page}
  - `segments`: list of {segment_name, revenue_eur_m, fiscal_year, page}
  - `management_tone`: {label: positive/neutral/cautious, rationale}
- Every extracted fact **must cite a page**; facts without a page are rejected.
- Results cached as JSON in `data/ai_cache/<ticker>_<fy>.json` and **committed**, so the repo
  runs without an API key. The extractor only calls the API when `--refresh` is passed and
  `ANTHROPIC_API_KEY` is set.

### 3.4 Valuation engine (`cac40val/valuation/`)

Pure functions, no I/O, fully unit-tested.

- **Historicals:** 5 fiscal years: revenue growth, EBIT margin, D&A % sales, capex % sales,
  NWC % sales, effective tax rate.
- **Forecast:** 5 explicit years driven by revenue growth and EBIT margin paths; other
  drivers default to the 5-year historical average.
- **Scenarios:** bear / base / bull. Base is anchored on AI-extracted guidance when available,
  otherwise on historical averages. All drivers are overridable in `config/assumptions/<ticker>.yaml`
  (analyst-in-the-loop); the source of each driver (historical / guidance / override) is shown
  in the outputs.
- **WACC:** rf = OAT 10y; beta = OLS regression of 60 monthly returns vs Euro Stoxx 50
  (Blume-adjusted); ERP = Damodaran France; cost of debt = interest expense / average gross
  debt (floored at rf); tax = 25.8% statutory; weights from market cap and book debt.
- **Terminal value:** Gordon growth (default g = 2.0%) cross-checked against an exit EV/EBITDA
  multiple (peer median); the gap between the two is reported.
- **Equity bridge:** EV − net debt − minorities (+ associates where available) → per-share value.
- **Sensitivity:** WACC (±100 bp) × g (±50 bp) grid.
- **Trading comps:** EV/Sales, EV/EBITDA, P/E (LTM); peer median and interquartile range;
  implied value range per target.
- **Football field:** DCF range (bear–bull), comps IQR range, 52-week price range, current price.

### 3.5 Outputs (`cac40val/outputs/`)

- **Excel model** per target (`openpyxl`) with **live formulas**, bank formatting conventions
  (blue inputs, black formulas), tabs: Summary, Assumptions, Historicals, DCF, WACC,
  Sensitivity, Comps.
- **Streamlit app** (`app/`): company selector, scenario toggle, editable drivers, football
  field, sensitivity heatmap, AI-extracted risks and guidance with page citations.
  Reads only from DuckDB + cache. Deployed on Streamlit Community Cloud.
- **One-pager PDF** per target (key metrics, football field, top 3 risks, verdict vs price).

## 4. DAIS / governance deliverables

- `docs/business_requirements.md`: context, stakeholders (M&A analyst, associate),
  user stories, KPI definitions.
- `docs/data_dictionary.md`: every table and column, type, source, transformation.
- `docs/data_model.md`: star-schema diagram (Mermaid).
- `docs/methodology.md`: valuation methodology and assumption rationale.
- GitHub Projects board with the backlog built from the user stories.
- Disclaimer: educational project, not investment advice.

## 5. Testing

- **pytest unit tests** for the valuation engine against a hand-calculated reference case
  (WACC, FCFF, discounting, terminal value, equity bridge, sensitivity grid).
- **pandera** schema tests on warehouse tables (run on fixture data in CI).
- **AI extraction tests** with a recorded fake LLM response: validates schema parsing, page
  citation enforcement and the segment-sum cross-check (no network calls in CI).
- **GitHub Actions:** lint (ruff) + tests on every push; status badge in README.

## 6. Repository layout

```
cac40-valuation-ai/
├── README.md               # business problem → demo → results → tech → Résumé en français
├── pyproject.toml
├── Makefile
├── config/                 # settings.yaml, sources.yaml, assumptions/<ticker>.yaml
├── cac40val/
│   ├── ingest/  warehouse/  ai_extraction/  valuation/  outputs/
│   └── pipeline.py
├── app/                    # Streamlit
├── data/                   # raw/ (gitignored), reference/, ai_cache/, warehouse.duckdb (gitignored)
├── outputs/                # generated Excel + PDFs (samples committed)
├── docs/
├── tests/
└── .github/workflows/ci.yml
```

## 7. Risks and mitigations

| Risk | Mitigation |
|------|------------|
| yfinance incomplete for EU companies | Report gaps in data-quality report; allow manual overrides in `config/` with source noted |
| DEU PDFs large / format differs per company | Keyword-based section targeting; per-company section hints in `sources.yaml` |
| LLM hallucination | Mandatory page citations, pydantic validation, segment-sum cross-check, human override |
| API cost | Targeted sections only; cached results committed; API used only with `--refresh` |
| L'Oréal / EssilorLuxottica are not pure luxury | Documented in methodology; comps median also shown excluding them |
