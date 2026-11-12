from pathlib import Path

import pandas as pd
import pytest

from cac40val.warehouse.db import connect, read_financials, read_prices, upsert

FIXTURE = Path(__file__).parent.parent / "fixtures" / "financials_sample.csv"
TABLES = {
    "dim_company",
    "dim_date",
    "fact_financials",
    "fact_prices",
    "fact_market_params",
    "fact_ai_extraction",
    "fact_fx",
}


def _fixture_df(ticker="MC.PA") -> pd.DataFrame:
    df = pd.read_csv(FIXTURE)
    df["ticker"] = ticker
    df["currency"] = "EUR"
    df["source"] = "test"
    return df[["ticker", "fiscal_year", "line_item", "value", "currency", "source"]]


def test_schema_created():
    con = connect(":memory:")
    names = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert TABLES <= names and len(names) == 7


def test_upsert_is_idempotent():
    con = connect(":memory:")
    df = _fixture_df()
    assert upsert(con, "fact_financials", df) == len(df)
    upsert(con, "fact_financials", df)
    assert con.execute("SELECT count(*) FROM fact_financials").fetchone()[0] == len(df)


def test_upsert_replaces_values():
    con = connect(":memory:")
    df = _fixture_df()
    upsert(con, "fact_financials", df)
    df2 = df.copy()
    df2["value"] = df2["value"] + 1
    upsert(con, "fact_financials", df2)
    out = read_financials(con, "MC.PA").sort_values(["fiscal_year", "line_item"])
    exp = df2.sort_values(["fiscal_year", "line_item"])
    assert out["value"].tolist() == pytest.approx(exp["value"].tolist())


def test_upsert_unknown_table_raises():
    con = connect(":memory:")
    with pytest.raises(ValueError):
        upsert(con, "x; DROP TABLE dim_company", pd.DataFrame({"a": [1]}))


def test_read_financials_roundtrip():
    con = connect(":memory:")
    upsert(con, "fact_financials", _fixture_df())
    orig = pd.read_csv(FIXTURE)
    key = ["fiscal_year", "line_item"]
    out = read_financials(con, "MC.PA")
    pd.testing.assert_frame_equal(
        out.sort_values(key).reset_index(drop=True),
        orig.sort_values(key).reset_index(drop=True),
        check_dtype=False,
    )


def test_read_prices():
    con = connect(":memory:")
    df = pd.DataFrame(
        {
            "ticker": "MC.PA",
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]).date,
            "close": [10.0, 11.0],
            "adj_close": [9.0, 10.0],
        }
    )
    upsert(con, "fact_prices", df)
    s = read_prices(con, "MC.PA")
    assert s.tolist() == [9.0, 10.0]
    assert len(s.index) == 2
