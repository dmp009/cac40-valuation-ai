CREATE TABLE IF NOT EXISTS dim_company (
    ticker VARCHAR, name VARCHAR, country VARCHAR, currency VARCHAR,
    sector VARCHAR, is_target BOOLEAN
);
CREATE TABLE IF NOT EXISTS dim_date (
    date DATE, year INTEGER, month INTEGER, quarter INTEGER
);
CREATE TABLE IF NOT EXISTS fact_financials (
    ticker VARCHAR, fiscal_year INTEGER, line_item VARCHAR, value DOUBLE,
    currency VARCHAR, source VARCHAR
);
CREATE TABLE IF NOT EXISTS fact_prices (
    ticker VARCHAR, date DATE, close DOUBLE, adj_close DOUBLE
);
CREATE TABLE IF NOT EXISTS fact_market_params (
    date DATE, rf_oat10y DOUBLE, erp_france DOUBLE
);
CREATE TABLE IF NOT EXISTS fact_fx (
    date DATE, currency VARCHAR, eur_per_unit DOUBLE
);
CREATE TABLE IF NOT EXISTS fact_ai_extraction (
    ticker VARCHAR, fiscal_year INTEGER, field VARCHAR, value VARCHAR,
    value_num DOUBLE, page INTEGER, model VARCHAR, extracted_at TIMESTAMP
);
