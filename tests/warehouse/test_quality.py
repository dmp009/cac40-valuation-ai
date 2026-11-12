import json
from pathlib import Path

import pandas as pd

from cac40val.warehouse.db import connect, upsert
from cac40val.warehouse.quality import QualityIssue, run_quality_checks, write_quality_report

FIXTURE = Path(__file__).parent.parent / "fixtures" / "financials_sample.csv"


def _fin(ticker="MC.PA", scale=1.0) -> pd.DataFrame:
    df = pd.read_csv(FIXTURE)
    df["value"] = df["value"] * scale
    df["ticker"] = ticker
    df["currency"] = "EUR"
    df["source"] = "test"
    return df


def _seg(values, ticker="MC.PA", fy=2024) -> pd.DataFrame:
    rows = [
        {
            "ticker": ticker,
            "fiscal_year": fy,
            "field": "segment",
            "value": json.dumps({"segment_name": f"s{i}"}),
            "value_num": v,
            "page": 1,
            "model": "m",
            "extracted_at": pd.Timestamp("2025-01-01"),
        }
        for i, v in enumerate(values)
    ]
    return pd.DataFrame(rows)


def _checks(issues):
    return {i.check for i in issues}


def test_clean_data_has_no_issues():
    con = connect(":memory:")
    upsert(con, "fact_financials", _fin())
    assert run_quality_checks(con) == []


def test_negative_revenue_is_error():
    con = connect(":memory:")
    df = _fin()
    df.loc[(df.line_item == "revenue") & (df.fiscal_year == 2024), "value"] = -5
    upsert(con, "fact_financials", df)
    issues = run_quality_checks(con)
    errs = [i for i in issues if i.severity == "error"]
    assert errs and errs[0].ticker == "MC.PA"


def test_missing_minorities_is_warning():
    con = connect(":memory:")
    df = _fin()
    df = df[df.line_item != "minorities"]
    upsert(con, "fact_financials", df)
    issues = run_quality_checks(con)
    miss = [i for i in issues if "minorities" in i.detail]
    assert miss and all(i.severity == "warning" for i in miss)


def test_balance_sheet_identity_warning():
    con = connect(":memory:")
    df = _fin()
    df.loc[(df.line_item == "total_assets") & (df.fiscal_year == 2024), "value"] *= 1.5
    upsert(con, "fact_financials", df)
    issues = run_quality_checks(con)
    assert any(i.severity == "warning" and "2024" in i.detail for i in issues)


def test_balance_identity_counts_minority_interest():
    # yfinance: liabilities and stockholders' equity both exclude minority interest,
    # so assets = liabilities + equity + minorities must not be flagged.
    con = connect(":memory:")
    df = _fin()
    df = df[df.fiscal_year == 2024]
    vals = {"total_assets": 200.0, "total_liabilities": 100.0, "total_equity": 80.0, "minorities": 20.0}
    for item, v in vals.items():
        df.loc[df.line_item == item, "value"] = v
    upsert(con, "fact_financials", df)
    assert "balance_sheet_identity" not in _checks(run_quality_checks(con))


def test_mixed_currency_flagged():
    con = connect(":memory:")
    df = _fin()
    df.loc[df.fiscal_year == 2024, "currency"] = "USD"
    upsert(con, "fact_financials", df)
    assert any(i.ticker == "MC.PA" for i in run_quality_checks(con))


def test_null_key_is_reported_not_raised():
    con = connect(":memory:")
    con.execute("INSERT INTO fact_financials VALUES (NULL, 2024, 'revenue', 1.0, 'EUR', 's')")
    assert run_quality_checks(con)


def test_segment_sum_mismatch_is_error():
    con = connect(":memory:")
    upsert(con, "fact_financials", _fin(scale=1e6))  # 2024 revenue in full units
    rev_m = con.execute(
        "SELECT value/1e6 FROM fact_financials WHERE line_item='revenue' AND fiscal_year=2024"
    ).fetchone()[0]
    upsert(con, "fact_ai_extraction", _seg([rev_m * 0.5, rev_m * 0.4]))
    issues = run_quality_checks(con)
    assert any(i.severity == "error" and i.ticker == "MC.PA" for i in issues)
    upsert(con, "fact_ai_extraction", _seg([rev_m * 0.6, rev_m * 0.39]))
    assert run_quality_checks(con) == []


def test_report_written(tmp_path):
    issues = [
        QualityIssue("revenue_positive", "MC.PA", "bad", "error"),
        QualityIssue("missing_items", None, "x", "warning"),
    ]
    p = tmp_path / "r.md"
    write_quality_report(issues, p)
    text = p.read_text()
    assert "revenue_positive" in text and "missing_items" in text


def test_report_clean(tmp_path):
    p = tmp_path / "r.md"
    write_quality_report([], p)
    assert p.exists()
