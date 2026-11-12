import pandas as pd

from cac40val.config import Company
from cac40val.ingest.market import LINE_ITEM_MAP, normalize_statements
from cac40val.valuation.forecast import CANONICAL_ITEMS


def _raw():
    return pd.read_csv("tests/fixtures/yf_income.csv", index_col=0)


def test_normalize_statements_maps_and_drops():
    df = normalize_statements(_raw(), "MC.PA", "EUR")
    assert set(df["line_item"]) <= set(CANONICAL_ITEMS)
    assert set(df["line_item"]) == {"revenue", "ebit", "capex", "interest_expense", "tax_expense"}
    assert df["fiscal_year"].dtype.kind == "i"
    assert set(df["fiscal_year"]) == {2023, 2024}
    assert (df["source"] == "yfinance").all() and (df["currency"] == "EUR").all()
    assert (df["ticker"] == "MC.PA").all()


def test_normalize_statements_capex_stored_positive():
    df = normalize_statements(_raw(), "MC.PA", "EUR")
    row = df[(df.line_item == "capex") & (df.fiscal_year == 2024)].iloc[0]
    assert row["value"] == 5_000_000_000


def test_line_item_map_values_canonical():
    assert set(LINE_ITEM_MAP.values()) <= set(CANONICAL_ITEMS)


def test_normalize_drops_nan():
    raw = _raw()
    raw.loc["EBIT", "2023-12-31"] = float("nan")
    df = normalize_statements(raw, "MC.PA", "EUR")
    assert len(df[df.line_item == "ebit"]) == 1


def test_download_deu_none_when_no_url(tmp_path):
    from cac40val.ingest.deu import download_deu

    c = Company("MC.PA", "LVMH", "EUR", True, deu_url=None)
    assert download_deu(c, tmp_path) is None


def test_download_deu_skips_existing(tmp_path):
    from cac40val.ingest.deu import download_deu

    c = Company("MC.PA", "LVMH", "EUR", True, deu_url="http://invalid.test/x.pdf")
    (tmp_path / "MC.PA.pdf").write_bytes(b"x")
    assert download_deu(c, tmp_path) == tmp_path / "MC.PA.pdf"
