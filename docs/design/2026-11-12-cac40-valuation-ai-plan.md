# CAC 40 Luxury Valuation AI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible pipeline that values 5 CAC 40 luxury companies (DCF + comps + football field), enriched with LLM-extracted guidance and risks from their DEU annual reports, delivered as Excel models, a Streamlit app and PDF one-pagers.

**Architecture:** Layered Python package `cac40val` (ingest → DuckDB warehouse → AI extraction → pure-function valuation engine → outputs), orchestrated by `cac40val.pipeline`. The valuation engine has no I/O and is fully unit-tested; AI results are cached as JSON so everything runs without an API key.

**Tech Stack:** Python 3.11+, pandas, numpy, yfinance, requests, duckdb, pandera, pydantic v2, pymupdf, anthropic, openpyxl, matplotlib, plotly, streamlit, pyyaml, pytest, ruff, GitHub Actions.

**Spec:** `docs/design/2026-11-12-cac40-valuation-ai-design.md`

## Global Constraints

- Language: all code, comments, docs in English; README ends with a "Résumé en français" section.
- All valuations in EUR; non-EUR peers (CHF, HKD) converted at valuation-date FX for multiples only.
- Targets: `MC.PA`, `RMS.PA`, `KER.PA`, `OR.PA`, `EL.PA`. Peers (comps only): `CFR.SW`, `MONC.MI`, `1913.HK`, `BC.MI`.
- Tax rate 25.8%; default terminal growth g = 2.0%; beta = 60 monthly returns vs `^STOXX50E`, Blume-adjusted; cost of debt floored at rf.
- Sensitivity grid: WACC ±100 bp, g ±50 bp.
- Every AI-extracted fact must carry a page number; facts without one are rejected.
- Segment-sum cross-check tolerance: ±2% of total revenue.
- The repo must run end to end with no API key (cached AI JSON in `data/ai_cache/` is committed). API is called only with `--refresh` and `ANTHROPIC_API_KEY` set.
- LLM model is configured in `config/settings.yaml` (default `claude-sonnet-5-5`); no model name hard-coded elsewhere.
- No network calls in tests/CI.
- Disclaimer "Educational project, not investment advice" in README and app footer.

## Review Focus

1. **WACC ≤ g** (user override or sensitivity corner): the engine must raise `ValueError` for a single valuation and put `NaN` in that sensitivity cell — never a negative or infinite terminal value. → Task 2.
2. **Net cash companies** (Hermès has net cash, i.e. negative net debt): equity bridge must add cash back, not flip sign errors. → Task 2.
3. **Missing yfinance fields** (e.g. no `Minority Interest` row for some EU tickers): treated as 0 and flagged in the data-quality report, not a crash. → Tasks 3 and 5.
4. **Peers with negative EBITDA or earnings**: excluded from that multiple's median (EV/EBITDA, P/E), not averaged in as negative multiples. → Task 4.
5. **LLM returns malformed output or facts without pages**: invalid facts dropped and counted, valid ones kept; missing cache without API key yields a clear message, and the pipeline continues on historical-average drivers. → Task 7.

---

## File structure

```
pyproject.toml, Makefile, .gitignore, .github/workflows/ci.yml
config/settings.yaml          # model, rf/erp overrides, g, tax
config/sources.yaml           # tickers, roles, currency, DEU URLs, section hints
config/assumptions/<ticker>.yaml   # optional analyst overrides
cac40val/
  __init__.py
  config.py                   # load YAML → typed dataclasses
  valuation/wacc.py           # cost of equity, beta, WACC
  valuation/dcf.py            # FCFF, discounting, TV, bridge, sensitivity
  valuation/forecast.py       # historical drivers, scenarios, projections
  valuation/comps.py          # multiples, peer stats, implied ranges, football field data
  warehouse/schema.sql        # DDL
  warehouse/db.py             # connect, create, load/read helpers
  warehouse/quality.py        # pandera schemas + report writer
  ingest/market.py            # yfinance prices, statements, FX
  ingest/rates.py             # ECB OAT 10y, Damodaran ERP snapshot reader
  ingest/deu.py               # DEU PDF downloader
  ai_extraction/models.py     # pydantic models
  ai_extraction/pdf.py        # page text + section locator
  ai_extraction/llm.py        # LLMClient protocol + AnthropicClient
  ai_extraction/extract.py    # orchestration, cache, cross-check
  outputs/excel.py, outputs/onepager.py
  pipeline.py                 # CLI entry point
app/streamlit_app.py
tests/  (mirrors package; fixtures in tests/fixtures/)
docs/   business_requirements.md, data_dictionary.md, data_model.md, methodology.md
```

---

### Task 1: Project scaffold, config and CI

**Files:**
- Create: `pyproject.toml`, `Makefile`, `.gitignore`, `.github/workflows/ci.yml`, `config/settings.yaml`, `config/sources.yaml`, `cac40val/__init__.py`, `cac40val/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass Company(ticker: str, name: str, currency: str, is_target: bool, deu_url: str | None, section_hints: list[str])`
  - `@dataclass Settings(llm_model: str, tax_rate: float, terminal_growth: float, rf_override: float | None, erp_override: float | None)`
  - `load_companies(path: Path = Path("config/sources.yaml")) -> list[Company]`
  - `load_settings(path: Path = Path("config/settings.yaml")) -> Settings`
  - `load_overrides(ticker: str, root: Path = Path("config/assumptions")) -> dict` (empty dict if file absent)

- [ ] **Step 1: Write failing tests** in `tests/test_config.py`:
  - `test_companies_has_5_targets_and_4_peers`: `sum(c.is_target)==5`, total 9, tickers equal the Global Constraints lists.
  - `test_settings_defaults`: `tax_rate==0.258`, `terminal_growth==0.02`, `llm_model=="claude-sonnet-5-5"`.
  - `test_overrides_missing_file_returns_empty`: `load_overrides("XXX", tmp_path) == {}`.
- [ ] **Step 2: Run** `pytest tests/test_config.py -v` → FAIL (module not found).
- [ ] **Step 3: Implement** pyproject (package `cac40val`, deps from Tech Stack, `[project.optional-dependencies] dev = [pytest, ruff]`), YAML configs, `config.py`. `.gitignore`: `data/raw/`, `data/*.duckdb`, `.env`, `__pycache__/`. Makefile targets: `install`, `test`, `lint`, `pipeline`, `app`. CI: Python 3.11, `pip install -e .[dev]`, `ruff check .`, `pytest`.
- [ ] **Step 4: Run** `pytest -v && ruff check .` → PASS.
- [ ] **Step 5: Commit** `chore: scaffold package, config and CI`.

---

### Task 2: WACC and DCF engine

**Files:**
- Create: `cac40val/valuation/__init__.py`, `cac40val/valuation/wacc.py`, `cac40val/valuation/dcf.py`
- Test: `tests/valuation/test_wacc.py`, `tests/valuation/test_dcf.py`

**Interfaces:**
- Produces (`wacc.py`):
  - `regress_beta(stock_returns: pd.Series, index_returns: pd.Series) -> float` (OLS slope on aligned, non-null pairs; raises `ValueError` if < 24 pairs)
  - `blume_adjust(raw_beta: float) -> float` (= 0.67·raw + 0.33)
  - `cost_of_equity(rf: float, beta: float, erp: float) -> float`
  - `cost_of_debt(interest_expense: float, avg_gross_debt: float, rf: float) -> float` (pre-tax, floored at rf; returns rf if debt ≤ 0)
  - `wacc(equity_value: float, debt_value: float, ke: float, kd_pre_tax: float, tax_rate: float) -> float`
- Produces (`dcf.py`):
  - `fcff(ebit: float, tax_rate: float, da: float, capex: float, delta_nwc: float) -> float`
  - `discount(cash_flows: Sequence[float], rate: float) -> float` (end-of-year, year 1..n)
  - `gordon_terminal_value(last_fcff: float, rate: float, g: float) -> float` (raises `ValueError` if rate ≤ g)
  - `exit_multiple_terminal_value(last_ebitda: float, multiple: float) -> float`
  - `enterprise_value(fcffs: Sequence[float], rate: float, g: float) -> float`
  - `equity_bridge(ev: float, net_debt: float, minorities: float = 0.0, associates: float = 0.0) -> float`
  - `sensitivity_grid(fcffs: Sequence[float], base_rate: float, base_g: float, net_debt: float, shares: float, minorities: float = 0.0, associates: float = 0.0) -> pd.DataFrame` (index: rate offsets `[-0.01,-0.005,0,0.005,0.01]` added to base; columns: g offsets `[-0.005,-0.0025,0,0.0025,0.005]`; values = per-share value; `NaN` where rate ≤ g)

- [ ] **Step 1: Write failing tests** (hand-calculated reference case, `pytest.approx(rel=1e-6)`):
  ```python
  assert blume_adjust(1.3) == approx(1.201)
  assert cost_of_equity(0.03, 1.1, 0.055) == approx(0.0905)
  assert cost_of_debt(8, 200, 0.03) == approx(0.04)
  assert cost_of_debt(2, 200, 0.03) == approx(0.03)        # floor
  assert wacc(800, 200, 0.0905, 0.04, 0.258) == approx(0.078336)
  assert fcff(100, 0.25, 20, 30, 5) == approx(60)
  assert discount([100, 110], 0.10) == approx(181.818182)
  assert gordon_terminal_value(110, 0.10, 0.02) == approx(1402.5)
  assert exit_multiple_terminal_value(150, 12) == approx(1800)
  assert enterprise_value([100, 110], 0.10, 0.02) == approx(1340.909091)
  assert equity_bridge(1340.909091, 200, 40, 10) == approx(1110.909091)
  assert equity_bridge(1000, -300) == approx(1300)          # net cash (Review Focus 2)
  ```
  - `test_gordon_raises_when_rate_le_g`: `pytest.raises(ValueError)` for `(110, 0.02, 0.02)` (Review Focus 1).
  - `test_sensitivity_grid_shape_center_and_nan`: 5×5; center cell == `1110.909091/100` for `sensitivity_grid([100,110], 0.10, 0.02, 200, 100, 40, 10)`; with `base_rate=0.025, base_g=0.02` the cell (rate offset −0.005, g offset 0) is `NaN`.
  - `test_regress_beta_recovers_slope`: synthetic `stock = 1.5*index + small noise`, 60 points → ≈1.5 (abs 0.05); 10 points → `ValueError`.
- [ ] **Step 2: Run** `pytest tests/valuation -v` → FAIL.
- [ ] **Step 3: Implement** both modules (numpy `polyfit` or covariance/variance for beta).
- [ ] **Step 4: Run** `pytest tests/valuation -v` → PASS.
- [ ] **Step 5: Commit** `feat(valuation): WACC and DCF engine with reference tests`.

---

### Task 3: Historical drivers, scenarios and forecast

**Files:**
- Create: `cac40val/valuation/forecast.py`
- Test: `tests/valuation/test_forecast.py`, fixture `tests/fixtures/financials_sample.csv` (5 fiscal years, long format: `fiscal_year,line_item,value`)

**Interfaces:**
- Consumes: `fcff`, `enterprise_value`, `equity_bridge` (Task 2); `load_overrides` (Task 1).
- Line items used (canonical names, also the warehouse vocabulary): `revenue, ebit, ebitda, da, capex, nwc, tax_expense, pretax_income, interest_expense, gross_debt, cash, minorities, associates, shares_outstanding`.
- Produces:
  - `@dataclass Drivers(revenue_growth: list[float], ebit_margin: list[float], da_pct: float, capex_pct: float, nwc_pct: float, tax_rate: float, sources: dict[str, str])` — growth/margin lists have length 5; `sources` maps driver name → `"historical" | "guidance" | "override"`.
  - `historical_drivers(fin: pd.DataFrame) -> dict[str, float]` (5-year averages: growth, ebit_margin, da_pct, capex_pct, nwc_pct, effective_tax_rate; missing line items → excluded from average, key `missing` lists them)
  - `build_scenarios(hist: dict, guidance_growth: float | None, guidance_margin: float | None, overrides: dict, tax_rate: float) -> dict[str, Drivers]` keys `"bear","base","bull"`. Base = guidance if present else historical; bear = base growth −3 pp and margin −2 pp; bull = +3 pp / +2 pp; flat across 5 years. Overrides (YAML keys `revenue_growth`, `ebit_margin` as scalar or 5-list, per scenario) win and set source `"override"`.
  - `project(last_revenue: float, last_nwc: float, d: Drivers) -> pd.DataFrame` (rows years 1–5; columns `revenue, ebit, da, capex, nwc, delta_nwc, fcff, ebitda`)

- [ ] **Step 1: Write failing tests:**
  - `test_historical_drivers_from_fixture`: growth, margin averages equal values hand-computed from the fixture (write the fixture with round numbers so averages are exact, e.g. revenue 100→110→121→133.1→146.41 gives growth 0.10).
  - `test_missing_line_item_is_flagged` (Review Focus 3): drop `minorities` rows → `"minorities" in hist["missing"]`, no exception.
  - `test_scenarios_spread`: with hist growth 0.10, margin 0.25, no guidance → bear growth 0.07/margin 0.23, bull 0.13/0.27, all sources `"historical"`.
  - `test_guidance_overrides_base_source`: `guidance_growth=0.08` → base growth 0.08, source `"guidance"`.
  - `test_yaml_override_wins`: overrides `{"base": {"ebit_margin": 0.30}}` → base margin 0.30 all years, source `"override"`.
  - `test_project_fcff_year1`: last_revenue 100, growth 0.10, margin 0.25, da 0.05, capex 0.06, nwc 0.10, tax 0.25, last_nwc 10 → year-1 revenue 110, ebit 27.5, delta_nwc 1.0, fcff = 27.5·0.75 + 5.5 − 6.6 − 1.0 = 18.525.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `forecast.py`.
- [ ] **Step 4: Run** `pytest tests/valuation -v` → PASS.
- [ ] **Step 5: Commit** `feat(valuation): historical drivers, scenarios and projections`.

---

### Task 4: Trading comps and football field data

**Files:**
- Create: `cac40val/valuation/comps.py`
- Test: `tests/valuation/test_comps.py`

**Interfaces:**
- Produces:
  - `compute_multiples(peers: pd.DataFrame) -> pd.DataFrame` — input columns `ticker, market_cap_eur, net_debt_eur, minorities_eur, revenue_eur, ebitda_eur, net_income_eur`; output adds `ev_sales, ev_ebitda, pe`; a multiple is `NaN` when its denominator ≤ 0 (Review Focus 4).
  - `peer_stats(multiples: pd.DataFrame, exclude: Sequence[str] = ()) -> pd.DataFrame` — index `ev_sales, ev_ebitda, pe`; columns `q1, median, q3, n` (NaN-skipping).
  - `implied_values(target: pd.Series, stats: pd.DataFrame, shares: float) -> pd.DataFrame` — per-share low (q1) / mid (median) / high (q3) per multiple; EV multiples bridged with target net debt and minorities.
  - `football_field(dcf_range: tuple[float, float], comps_range: tuple[float, float], week52: tuple[float, float], price: float) -> pd.DataFrame` — rows `DCF (bear–bull)`, `Trading comps (IQR)`, `52-week range`; columns `low, high`; attribute `df.attrs["price"]`.

- [ ] **Step 1: Write failing tests:**
  - `test_multiples_basic`: mcap 1000, net debt 100, minorities 0, revenue 500, ebitda 110, NI 50 → ev_sales 2.2, ev_ebitda 10.0, pe 20.0.
  - `test_negative_ebitda_excluded`: a peer with ebitda −10 → its ev_ebitda NaN and `peer_stats.loc["ev_ebitda","n"]` counts only valid peers.
  - `test_peer_stats_exclude`: excluding `OR.PA, EL.PA` changes `n` by 2.
  - `test_implied_values_ev_bridge`: median EV/EBITDA 10, target ebitda 100, net debt 200, minorities 0, shares 80 → mid = 10.0.
  - `test_football_field_rows`: 3 rows, `attrs["price"]` preserved.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(valuation): trading comps and football field`.

---

### Task 5: DuckDB warehouse and data-quality layer

**Files:**
- Create: `cac40val/warehouse/__init__.py`, `schema.sql`, `db.py`, `quality.py`
- Test: `tests/warehouse/test_db.py`, `tests/warehouse/test_quality.py`

**Interfaces:**
- Tables exactly as spec §3.2 (`dim_company, dim_date, fact_financials, fact_prices, fact_market_params, fact_ai_extraction`); `fact_financials.line_item` uses Task 3 vocabulary; `value` in reporting currency, `currency` column kept.
- Produces:
  - `connect(path: Path | str = "data/warehouse.duckdb") -> duckdb.DuckDBPyConnection` (creates schema if absent; `":memory:"` allowed)
  - `upsert(con, table: str, df: pd.DataFrame) -> int` (delete-then-insert on table's natural key; returns rows written)
  - `read_financials(con, ticker: str) -> pd.DataFrame` (long format as in Task 3 fixture)
  - `read_prices(con, ticker: str) -> pd.Series` (adj_close indexed by date)
  - `run_quality_checks(con) -> list[QualityIssue]`, `@dataclass QualityIssue(check: str, ticker: str | None, detail: str, severity: Literal["error","warning"])`
  - `write_quality_report(issues: list[QualityIssue], path: Path = Path("data_quality_report.md")) -> None`
- Checks: non-null keys; revenue > 0; |assets − (liabilities + equity)| / assets ≤ 1% (warning); one currency per ticker in `fact_financials`; missing canonical line items per ticker/year (warning, Review Focus 3); AI segment-sum within ±2% of revenue (error).

- [ ] **Step 1: Write failing tests** using `connect(":memory:")`:
  - `test_schema_created`: all 6 tables exist.
  - `test_upsert_is_idempotent`: upserting same df twice → row count unchanged.
  - `test_read_financials_roundtrip`: load Task 3 fixture → `read_financials` equals it (sorted).
  - `test_negative_revenue_is_error`, `test_missing_minorities_is_warning`, `test_segment_sum_mismatch_is_error` (segments 90 vs revenue 100 → error; 99 vs 100 → none).
  - `test_report_written`: markdown file contains each issue's `check`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(warehouse): DuckDB star schema and data-quality checks`.

---

### Task 6: Ingestion (market data, rates, DEU download)

**Files:**
- Create: `cac40val/ingest/__init__.py`, `market.py`, `rates.py`, `deu.py`; `data/reference/damodaran_erp.csv` (columns `country, erp, source_date`; France row filled from Damodaran's latest file, with download date)
- Test: `tests/ingest/test_market.py`, `tests/ingest/test_rates.py`, fixtures `tests/fixtures/yf_income.csv`, `tests/fixtures/ecb_oat.csv`

**Interfaces:**
- Consumes: `Company` (Task 1), `upsert` (Task 5).
- Produces:
  - `LINE_ITEM_MAP: dict[str, str]` — yfinance row label → canonical line item (e.g. `"Total Revenue"→"revenue"`, `"EBIT"→"ebit"`, `"Minority Interest"→"minorities"`, ...).
  - `normalize_statements(raw: pd.DataFrame, ticker: str, currency: str) -> pd.DataFrame` (wide yfinance frame → long `fact_financials` rows; unknown labels dropped; `source="yfinance"`)
  - `fetch_company(company: Company) -> tuple[pd.DataFrame, pd.DataFrame]` (financials long, prices) — network.
  - `fetch_fx(currency: str, date: str) -> float` (EUR per 1 unit; 1.0 for EUR) — network.
  - `parse_ecb_csv(text: str) -> pd.DataFrame` (columns `date, rf_oat10y` as decimal, e.g. 3.12 → 0.0312)
  - `fetch_oat10y() -> pd.DataFrame` — network; ECB series `IRS.M.FR.L.L40.CI.0000.EUR.N.Z`.
  - `load_erp(path: Path = Path("data/reference/damodaran_erp.csv"), country: str = "France") -> float`
  - `download_deu(company: Company, dest: Path = Path("data/raw/deu")) -> Path | None` (skips if file exists; returns None if no URL)
- Network functions save the raw response under `data/raw/<source>/<timestamp>` before parsing (lineage).

- [ ] **Step 1: Write failing tests** (fixtures only, no network):
  - `test_normalize_statements_maps_and_drops`: fixture with `Total Revenue`, `EBIT`, `Some Unknown Row` → only canonical rows, `line_item` set ⊆ canonical vocabulary, `fiscal_year` int.
  - `test_parse_ecb_csv_percent_to_decimal`.
  - `test_load_erp_france` returns a float between 0.03 and 0.10.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Manual smoke** (not in CI): `python -c "from cac40val.ingest.market import fetch_company; ..."` for `MC.PA` returns non-empty frames; note any missing labels and extend `LINE_ITEM_MAP`.
- [ ] **Step 6: Commit** `feat(ingest): yfinance, ECB OAT, Damodaran ERP and DEU download`.

---

### Task 7: AI extraction from DEU reports

**Files:**
- Create: `cac40val/ai_extraction/__init__.py`, `models.py`, `pdf.py`, `llm.py`, `extract.py`
- Test: `tests/ai_extraction/test_models.py`, `test_pdf.py`, `test_extract.py`; fixtures `tests/fixtures/mini_deu.pdf` (3 pages, generated in the test setup with pymupdf), `tests/fixtures/llm_response.json`

**Interfaces:**
- Consumes: `Settings`, `Company` (Task 1); `upsert` (Task 5).
- Produces (`models.py`, pydantic v2; fields exactly as spec §3.3):
  - `GuidanceItem(metric, statement, direction: Literal["up","flat","down"], horizon, page: int)`
  - `RiskItem(category, description, severity: int (1–5), page: int)`
  - `SegmentItem(segment_name, revenue_eur_m: float, fiscal_year: int, page: int)`
  - `ManagementTone(label: Literal["positive","neutral","cautious"], rationale: str)`
  - `Extraction(ticker, fiscal_year, model, extracted_at: datetime, guidance: list[GuidanceItem], risks: list[RiskItem], segments: list[SegmentItem], management_tone: ManagementTone, rejected_count: int = 0)`
- `pdf.py`: `read_pages(path: Path) -> list[tuple[int, str]]` (1-based); `locate_sections(pages, keywords: Sequence[str], window: int = 2) -> list[tuple[int, str]]` (pages matching any keyword case-insensitively, plus `window` following pages, deduplicated, ordered). Default keywords: `perspectives, outlook, facteurs de risque, risk factors, segment, information sectorielle` + company `section_hints`.
- `llm.py`: `class LLMClient(Protocol): def extract(self, prompt: str, schema: type[BaseModel]) -> dict`; `class AnthropicClient` (reads model from `Settings.llm_model`, key from env `ANTHROPIC_API_KEY`; uses the `anthropic` SDK with the pydantic JSON schema passed as a tool's `input_schema` and returns the tool input dict).
- `extract.py`:
  - `parse_extraction(raw: dict, ticker: str, fiscal_year: int, model: str) -> Extraction` — validates item by item; items failing validation or lacking `page` are dropped and counted in `rejected_count` (Review Focus 5).
  - `segment_check(ex: Extraction, total_revenue_eur_m: float, tol: float = 0.02) -> bool`
  - `get_extraction(company: Company, fiscal_year: int, *, refresh: bool, client: LLMClient | None, cache_dir: Path = Path("data/ai_cache")) -> Extraction | None` — returns cached JSON if present and not `refresh`; if no cache and (`not refresh` or no client) → logs `"No AI cache for <ticker>; run with --refresh and ANTHROPIC_API_KEY to extract"` and returns `None`; otherwise calls client with located sections, parses, writes cache.
  - `to_rows(ex: Extraction) -> pd.DataFrame` (rows for `fact_ai_extraction`).
- Prompt text lives in `ai_extraction/prompts/extract_v1.md` (English; instructs: quote only facts in the provided pages, always give page number, revenue in EUR millions).

- [ ] **Step 1: Write failing tests:**
  - `test_fact_without_page_is_rejected`: raw with 2 risks, one missing `page` → 1 risk kept, `rejected_count == 1`.
  - `test_malformed_item_rejected_others_kept`: severity 9 → rejected; valid guidance kept.
  - `test_locate_sections_finds_keyword_and_window`: mini PDF with "Outlook" on page 2 → pages {2, 3}.
  - `test_segment_check_tolerance`: segments 99 vs total 100 → True; 90 → False.
  - `test_cache_hit_does_not_call_client`: fake client that raises if called; cached file present → returns Extraction.
  - `test_no_cache_no_refresh_returns_none_with_message` (use `caplog`).
  - `test_refresh_with_fake_client_writes_cache`: fake client returns `llm_response.json` → cache file created and round-trips.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Real extraction** (manual, needs key): `python -m cac40val.pipeline --refresh --only-ai` for the 5 targets; review each JSON for plausibility; commit `data/ai_cache/*.json`.
- [ ] **Step 6: Commit** `feat(ai): DEU extraction with page citations, validation and cache`.

---

### Task 8: Pipeline orchestration

**Files:**
- Create: `cac40val/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `@dataclass CompanyValuation(ticker: str, price: float, scenarios: dict[str, float]  # per-share value bear/base/bull, wacc: float, g: float, ev_base: float, sensitivity: pd.DataFrame, projections: dict[str, pd.DataFrame], drivers: dict[str, Drivers], comps_implied: pd.DataFrame, football: pd.DataFrame, extraction: Extraction | None, tv_gordon_vs_exit_gap: float)`
  - `value_company(con, company: Company, settings: Settings, peers_multiples: pd.DataFrame, extraction: Extraction | None) -> CompanyValuation` — pure aside from DB reads.
  - `main(argv: list[str] | None = None) -> int` — CLI flags `--refresh` (AI), `--offline` (skip network ingest; use existing DB), `--only-ai`, `--tickers MC.PA ...`. Steps: ingest → load DB → quality checks + report → AI extraction → comps → value each target → outputs (Task 9). Saves results to `outputs/valuations.json`.
- Guidance mapping: base `guidance_growth` / `guidance_margin` taken from `GuidanceItem`s with `metric` in {`revenue_growth`, `organic_growth`} / {`operating_margin`, `ebit_margin`} when the statement contains a parseable percentage; otherwise `None`.

- [ ] **Step 1: Write failing test** `test_value_company_on_seeded_db`: in-memory DB seeded with Task 3 fixture for a fake target + 3 fake peers + prices + market params; `value_company` returns bear < base < bull, 5×5 sensitivity, football field with 3 rows, `extraction is None` handled.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Real run:** `make pipeline` → `outputs/valuations.json` with 5 targets; `data_quality_report.md` generated; inspect for absurd values (per-share value within 0.2×–5× of price; otherwise investigate data before moving on).
- [ ] **Step 6: Commit** `feat: end-to-end valuation pipeline`.

---

### Task 9: Excel models and PDF one-pagers

**Files:**
- Create: `cac40val/outputs/__init__.py`, `excel.py`, `onepager.py`
- Test: `tests/outputs/test_excel.py`, `tests/outputs/test_onepager.py`

**Interfaces:**
- Consumes: `CompanyValuation` (Task 8).
- Produces:
  - `write_excel(v: CompanyValuation, path: Path) -> Path` — sheets `Summary, Assumptions, Historicals, DCF, WACC, Sensitivity, Comps`. Assumption cells are inputs (font color `0000FF`); DCF/WACC cells are **Excel formulas** referencing Assumptions (e.g. revenue year t = previous × (1 + growth), FCFF, discount factors, Gordon TV, EV, equity value, per-share). Summary shows formula-driven base per-share value and the driver sources.
  - `write_onepager(v: CompanyValuation, path: Path) -> Path` — single A4 PDF (matplotlib): header, key metrics table, football field chart with price line, top 3 risks by severity with page refs, verdict (`Undervalued` if base > price × 1.10, `Overvalued` if < price × 0.90, else `Fairly valued`) and disclaimer.
- Pipeline calls both for each target into `outputs/<ticker>/`. Commit one sample (LVMH) of each.

- [ ] **Step 1: Write failing tests:**
  - `test_excel_sheets_and_formulas`: open with openpyxl → 7 sheet names; DCF EV cell `data_type == "f"`; an Assumptions input cell font color ends with `0000FF`.
  - `test_excel_engine_check_cell`: CI cannot evaluate Excel formulas, so the Summary sheet also stores the engine's base value as a static cell labelled "Engine check"; assert it equals `v.scenarios["base"]` (the formula result is compared to it manually in Step 5).
  - `test_onepager_is_single_page_pdf`: file exists, starts with `%PDF`, pymupdf page count == 1.
  - `test_verdict_thresholds`: helper `verdict(base: float, price: float) -> str` for 115/100, 100/100, 85/100.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Manual check:** open `outputs/MC.PA/MC.PA_model.xlsx` in Excel; formula base value equals "Engine check" within rounding.
- [ ] **Step 6: Commit** `feat(outputs): Excel model with live formulas and PDF one-pager`.

---

### Task 10: Streamlit app

**Files:**
- Create: `app/streamlit_app.py`, `app/charts.py`, `requirements.txt` (for Streamlit Cloud)
- Test: `tests/app/test_charts.py`

**Interfaces:**
- Consumes: `outputs/valuations.json`, DuckDB, `ai_cache`, Task 2–4 functions for live recomputation.
- Produces: `football_chart(ff: pd.DataFrame) -> go.Figure`, `sensitivity_heatmap(grid: pd.DataFrame) -> go.Figure`.
- App: sidebar company selector + scenario radio; sliders for base growth and EBIT margin that recompute value live via Task 3/2 functions; tabs **Valuation** (football field, scenario table, sensitivity heatmap), **AI insights** (guidance and risks tables with page citations, tone, rejected count), **Comps** (peer table, toggle "exclude L'Oréal & EssilorLuxottica"), **Data quality** (report). Footer disclaimer. Works when `extraction` is None (shows "No AI extraction available").

- [ ] **Step 1: Failing tests:** `test_football_chart_has_price_line` (figure has a shape/line at price), `test_heatmap_dims` (5×5 z-values).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Manual:** `make app`, click through all 5 companies and tabs; no exceptions.
- [ ] **Step 6: Commit** `feat(app): Streamlit valuation explorer`. Deploy on Streamlit Community Cloud after the repo is on GitHub (user action; record URL in README).

---

### Task 11: Documentation, governance and README

**Files:**
- Create: `README.md`, `docs/business_requirements.md`, `docs/data_dictionary.md`, `docs/data_model.md`, `docs/methodology.md`, `LICENSE` (MIT)

**Content requirements:**
- `business_requirements.md`: context, stakeholders (M&A analyst, associate, MD), 6–8 user stories in "As a … I want … so that …" form, each with acceptance criteria; KPI definitions (EV, equity value per share, upside %, WACC, EV/EBITDA).
- `data_dictionary.md`: every table and column from `schema.sql` with type, description, source, transformation.
- `data_model.md`: Mermaid `erDiagram` of the star schema + Mermaid flowchart of the pipeline (lineage).
- `methodology.md`: each formula from Tasks 2–4 with parameter values from Global Constraints, scenario rules, comps exclusion rule, limitations (yfinance gaps; L'Oréal/EssilorLuxottica not pure luxury).
- `README.md` order: title + CI badge + live-app link placeholder until deployed → **Business problem** → screenshot/GIF of app → **Results table** (5 targets: price, base value, upside, verdict) → How it works (diagram) → AI with guardrails → Data governance → Quickstart (`make install && make pipeline && make app`) → Project structure → Disclaimer → **Résumé en français** (≈120 words).

- [ ] **Step 1:** Write docs; verify every table in `schema.sql` appears in the data dictionary (`grep`).
- [ ] **Step 2:** Run `make test && make lint` → PASS. In a fresh clone with `ANTHROPIC_API_KEY` unset, `make install && make pipeline && make app` runs end to end using the committed AI cache.
- [ ] **Step 3: Commit** `docs: README, business requirements, data dictionary, methodology`.
- [ ] **Step 4 (user, after GitHub push):** create a GitHub Projects board with one card per user story; link it in the README.
