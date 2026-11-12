"""Data-quality checks over the warehouse. Failures are reported, never silently passed."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import duckdb
import pandas as pd
import pandera.pandas as pa

from cac40val.valuation.forecast import CANONICAL_ITEMS

BALANCE_TOLERANCE = 0.01
SEGMENT_TOLERANCE = 0.02


@dataclass
class QualityIssue:
    check: str
    ticker: str | None
    detail: str
    severity: Literal["error", "warning"]


_FINANCIALS_SCHEMA = pa.DataFrameSchema(
    {
        "ticker": pa.Column(str, nullable=False, coerce=True),
        "fiscal_year": pa.Column(int, nullable=False, coerce=True),
        "line_item": pa.Column(str, nullable=False, coerce=True),
        "value": pa.Column(float, nullable=True, coerce=True),
        "currency": pa.Column(str, nullable=True, coerce=True),
    },
    checks=[
        pa.Check(
            lambda df: ~((df["line_item"] == "revenue") & (df["value"] <= 0)),
            element_wise=False,
            error="revenue must be > 0",
        )
    ],
)
_KEY_SCHEMAS = {
    "dim_company": pa.DataFrameSchema({"ticker": pa.Column(str, nullable=False)}),
    "dim_date": pa.DataFrameSchema({"date": pa.Column(nullable=False)}),
    "fact_prices": pa.DataFrameSchema(
        {"ticker": pa.Column(str, nullable=False), "date": pa.Column(nullable=False)}
    ),
    "fact_market_params": pa.DataFrameSchema({"date": pa.Column(nullable=False)}),
    "fact_fx": pa.DataFrameSchema(
        {"date": pa.Column(nullable=False), "currency": pa.Column(str, nullable=False)}
    ),
    "fact_ai_extraction": pa.DataFrameSchema(
        {"ticker": pa.Column(str, nullable=False), "fiscal_year": pa.Column(nullable=False)}
    ),
}


def _pandera_issues(name: str, schema: pa.DataFrameSchema, df: pd.DataFrame) -> list[QualityIssue]:
    if df.empty:
        return []
    try:
        schema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        out = []
        for _, r in exc.failure_cases.iterrows():
            row = r["index"]
            ticker = None
            if "ticker" in df.columns and pd.notna(row) and row in df.index:
                t = df.loc[row, "ticker"]
                ticker = None if pd.isna(t) else str(t)
            check = "revenue_positive" if "revenue" in str(r["check"]) else f"{name}_schema"
            out.append(
                QualityIssue(check, ticker, f"{name}: {r['column']} failed {r['check']}", "error")
            )
        return out
    return []


def run_quality_checks(con: duckdb.DuckDBPyConnection) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    fin = con.execute("SELECT * FROM fact_financials").df()
    issues += _pandera_issues("fact_financials", _FINANCIALS_SCHEMA, fin)
    for table, schema in _KEY_SCHEMAS.items():
        issues += _pandera_issues(table, schema, con.execute(f"SELECT * FROM {table}").df())

    fin = fin.dropna(subset=["ticker", "fiscal_year", "line_item"])
    if fin.empty:
        return issues

    # balance sheet identity
    wide = fin.pivot_table(
        index=["ticker", "fiscal_year"], columns="line_item", values="value", aggfunc="last"
    )
    if {"total_assets", "total_liabilities", "total_equity"} <= set(wide.columns):
        for (ticker, fy), r in wide.iterrows():
            a, li, e = r["total_assets"], r["total_liabilities"], r["total_equity"]
            if pd.isna(a) or pd.isna(li) or pd.isna(e) or a == 0:
                continue
            # yfinance liabilities and stockholders' equity both exclude minority interest
            m = r.get("minorities", 0.0)
            m = 0.0 if pd.isna(m) else m
            gap = abs(a - (li + e + m)) / abs(a)
            if gap > BALANCE_TOLERANCE:
                issues.append(
                    QualityIssue(
                        "balance_sheet_identity",
                        ticker,
                        f"FY{int(fy)}: assets vs liabilities+equity+minorities off by {gap:.1%}",
                        "warning",
                    )
                )

    # one currency per ticker
    cur = fin.dropna(subset=["currency"]).groupby("ticker")["currency"].unique()
    for ticker, cs in cur.items():
        if len(cs) > 1:
            issues.append(
                QualityIssue(
                    "currency_consistency", ticker, f"multiple currencies: {sorted(cs)}", "error"
                )
            )

    # missing canonical items
    for (ticker, fy), grp in fin.groupby(["ticker", "fiscal_year"]):
        missing = [i for i in CANONICAL_ITEMS if i not in set(grp["line_item"])]
        if missing:
            issues.append(
                QualityIssue(
                    "missing_line_items",
                    ticker,
                    f"FY{int(fy)}: missing {', '.join(missing)}",
                    "warning",
                )
            )

    # AI segment sum vs revenue (revenue in full units, segments in EUR millions)
    seg = con.execute(
        "SELECT ticker, fiscal_year, sum(value_num) AS seg_sum FROM fact_ai_extraction "
        "WHERE field = 'segment' AND value_num IS NOT NULL GROUP BY ticker, fiscal_year"
    ).df()
    rev = fin[fin["line_item"] == "revenue"].set_index(["ticker", "fiscal_year"])["value"]
    for r in seg.itertuples():
        key = (r.ticker, r.fiscal_year)
        if key not in rev.index:
            continue
        rev_m = rev.loc[key] / 1e6
        if pd.isna(rev_m) or rev_m <= 0:
            continue
        gap = abs(r.seg_sum - rev_m) / rev_m
        if gap > SEGMENT_TOLERANCE:
            issues.append(
                QualityIssue(
                    "segment_sum_mismatch",
                    r.ticker,
                    f"FY{int(r.fiscal_year)}: segments sum {r.seg_sum:,.1f}m vs revenue "
                    f"{rev_m:,.1f}m ({gap:.1%} off)",
                    "error",
                )
            )
    return issues


def write_quality_report(
    issues: list[QualityIssue], path: Path = Path("data_quality_report.md")
) -> None:
    lines = ["# Data quality report", ""]
    if not issues:
        lines.append("No issues found.")
    else:
        errors = sum(i.severity == "error" for i in issues)
        lines += [f"{errors} error(s), {len(issues) - errors} warning(s).", ""]
        lines += ["| Severity | Check | Ticker | Detail |", "|---|---|---|---|"]
        for i in sorted(issues, key=lambda x: (x.severity != "error", x.check)):
            detail = i.detail.replace("|", "\\|")
            lines.append(f"| {i.severity} | {i.check} | {i.ticker or '-'} | {detail} |")
    Path(path).write_text("\n".join(lines) + "\n")
