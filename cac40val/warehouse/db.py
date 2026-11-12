"""DuckDB connection, schema creation, upserts and typed readers."""

from pathlib import Path

import duckdb
import pandas as pd

_SCHEMA = Path(__file__).parent / "schema.sql"

NATURAL_KEYS: dict[str, list[str]] = {
    "dim_company": ["ticker"],
    "dim_date": ["date"],
    "fact_financials": ["ticker", "fiscal_year", "line_item"],
    "fact_prices": ["ticker", "date"],
    "fact_market_params": ["date"],
    "fact_fx": ["date", "currency"],
    "fact_ai_extraction": ["ticker", "fiscal_year"],
}


def connect(path: Path | str = "data/warehouse.duckdb") -> duckdb.DuckDBPyConnection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(_SCHEMA.read_text())
    return con


def upsert(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame) -> int:
    """Delete rows matching the incoming natural keys, then insert df. Returns rows written."""
    if table not in NATURAL_KEYS:
        raise ValueError(f"Unknown table '{table}'")
    if df.empty:
        return 0
    keys = NATURAL_KEYS[table]
    cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    missing = set(cols) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns for {table}: {sorted(missing)}")
    data = df[cols]
    con.register("_incoming", data)
    try:
        con.execute("BEGIN")
        cond = " AND ".join(f"t.{k} IS NOT DISTINCT FROM i.{k}" for k in keys)
        con.execute(
            f"DELETE FROM {table} AS t WHERE EXISTS "
            f"(SELECT 1 FROM (SELECT DISTINCT {', '.join(keys)} FROM _incoming) i WHERE {cond})"
        )
        con.execute(f"INSERT INTO {table} SELECT * FROM _incoming")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.unregister("_incoming")
    return len(data)


def read_financials(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.DataFrame:
    return con.execute(
        "SELECT fiscal_year, line_item, value FROM fact_financials WHERE ticker = ? "
        "ORDER BY fiscal_year, line_item",
        [ticker],
    ).df()


def read_prices(con: duckdb.DuckDBPyConnection, ticker: str) -> pd.Series:
    df = con.execute(
        "SELECT date, adj_close FROM fact_prices WHERE ticker = ? ORDER BY date", [ticker]
    ).df()
    return pd.Series(df["adj_close"].to_numpy(), index=pd.to_datetime(df["date"]), name="adj_close")
