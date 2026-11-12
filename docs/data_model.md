# Data model and lineage

## Star schema

Two dimensions (company, date) and five fact tables. DuckDB does not enforce the foreign keys;
they are logical relationships used in joins and checked by the data-quality layer (non-null
keys). Column details are in [data_dictionary.md](data_dictionary.md).

```mermaid
erDiagram
    dim_company ||--o{ fact_financials : "ticker"
    dim_company ||--o{ fact_prices : "ticker"
    dim_company ||--o{ fact_ai_extraction : "ticker"
    dim_date ||--o{ fact_prices : "date"
    dim_date ||--o{ fact_market_params : "date"
    dim_date ||--o{ fact_fx : "date"

    dim_company {
        VARCHAR ticker PK
        VARCHAR name
        VARCHAR country
        VARCHAR currency
        VARCHAR sector
        BOOLEAN is_target
    }
    dim_date {
        DATE date PK
        INTEGER year
        INTEGER month
        INTEGER quarter
    }
    fact_financials {
        VARCHAR ticker FK
        INTEGER fiscal_year
        VARCHAR line_item
        DOUBLE value
        VARCHAR currency
        VARCHAR source
    }
    fact_prices {
        VARCHAR ticker FK
        DATE date FK
        DOUBLE close
        DOUBLE adj_close
    }
    fact_market_params {
        DATE date FK
        DOUBLE rf_oat10y
        DOUBLE erp_france
    }
    fact_fx {
        DATE date FK
        VARCHAR currency
        DOUBLE eur_per_unit
    }
    fact_ai_extraction {
        VARCHAR ticker FK
        INTEGER fiscal_year
        VARCHAR field
        VARCHAR value
        DOUBLE value_num
        INTEGER page
        VARCHAR model
        TIMESTAMP extracted_at
    }
```

Notes:

- `fact_financials` is in long format (one row per line item) so that new line items need no
  schema change. The valuation code pivots it to one column per line item.
- `fact_prices` also holds the benchmark `^STOXX50E`, which has no row in `dim_company`.
- `fact_market_params` and `fact_fx` dates are monthly ECB dates or the valuation date, which
  are not always trading dates in `dim_date`.

## Pipeline lineage

`python -m cac40val.pipeline` (or `make pipeline`) runs the steps below in order.
`--offline` skips ingestion and reuses the existing warehouse, `--refresh` re-runs the AI
extraction (needs `ANTHROPIC_API_KEY`), `--only-ai` stops after extraction and `--tickers`
restricts the valuation targets.

```mermaid
flowchart TD
    subgraph Sources
        YF[yfinance<br/>statements, prices, FX]
        ECB[ECB Data Portal<br/>French OAT 10y]
        DAM[Damodaran<br/>data/reference/damodaran_erp.csv]
        DEU[Company DEU PDF]
        CFG[config/<br/>sources, settings, assumptions]
    end

    subgraph Ingest
        RAW[data/raw/source/timestamp<br/>raw responses]
        NORM[Normalise<br/>line-item map, abs values, operating NWC]
    end

    subgraph Warehouse[DuckDB warehouse]
        DC[dim_company]
        DD[dim_date]
        FF[fact_financials]
        FP[fact_prices]
        FM[fact_market_params]
        FX[fact_fx]
        FA[fact_ai_extraction]
    end

    subgraph AI[AI extraction]
        LOC[Locate pages by keyword]
        LLM[LLM tool call<br/>pydantic schema]
        VAL[Validate items<br/>page cited and sent]
        CACHE[data/ai_cache/ticker_fy.json]
    end

    DQ[Data-quality checks<br/>data_quality_report.md]

    subgraph Valuation
        WACC[WACC<br/>beta, Ke, Kd]
        DRV[Drivers and scenarios<br/>historical / guidance / override]
        DCF[DCF, terminal value,<br/>equity bridge, sensitivity]
        CMP[Trading comps<br/>EUR multiples, IQR]
        FB[Football field]
    end

    subgraph Outputs
        XL[Excel model]
        PDF[PDF one-pager]
        JS[outputs/valuations.json]
        SNAP[data/snapshot/*.parquet]
        APP[Streamlit app]
        RD[README results table]
    end

    YF --> RAW --> NORM
    NORM --> FF
    NORM --> FP
    NORM --> FX
    ECB --> RAW
    ECB --> FM
    DAM --> FM
    CFG --> DC
    FP --> DD

    DEU --> LOC --> LLM --> VAL --> CACHE --> FA

    Warehouse --> DQ

    FP --> WACC
    FM --> WACC
    FF --> WACC
    FF --> DRV
    FA --> DRV
    CFG --> DRV
    WACC --> DCF
    DRV --> DCF
    FF --> CMP
    FP --> CMP
    FX --> CMP
    DCF --> FB
    CMP --> FB
    FP --> FB

    DCF --> XL
    CMP --> XL
    FB --> PDF
    FA --> PDF
    DCF --> JS --> RD
    Warehouse --> SNAP --> APP
    CACHE --> APP
    DQ --> APP
```

## Lineage guarantees

| Question | Where the answer is |
|---|---|
| Which API response did this number come from? | Timestamped file in `data/raw/<source>/` |
| Which provider supplied a financial figure? | `fact_financials.source` |
| Which page of the DEU supports an AI fact, and which model produced it? | `fact_ai_extraction.page`, `.model`, `.extracted_at` |
| Is a forecast driver historical, from guidance or an analyst override? | `driver_sources` in `outputs/valuations.json`, the app caption and the Excel Assumptions tab |
| When was the ERP taken from Damodaran? | `source_date` in `data/reference/damodaran_erp.csv` |
| What data did a published result use? | `data/snapshot/*.parquet`, committed with the outputs |
