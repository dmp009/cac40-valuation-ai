import json
import math

import numpy as np
import pandas as pd
import pytest

from cac40val.ai_extraction.models import Extraction, GuidanceItem
from cac40val.config import Company, Settings
from cac40val.pipeline import (
    build_multiples,
    export_snapshot,
    guidance_from_extraction,
    load_snapshot,
    value_company,
    write_outputs,
)
from cac40val.warehouse.db import connect, upsert

SETTINGS = Settings(
    llm_model="m",
    tax_rate=0.258,
    terminal_growth=0.02,
    rf_override=None,
    erp_override=None,
    benchmark_ticker="^BENCH",
)
TICKERS = ["TGT", "P1", "P2", "P3"]
COMPANIES = [Company(t, t, "EUR", t == "TGT") for t in TICKERS]


def _prices(ticker: str, seed: int, n: int = 1400) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end="2026-11-10", periods=n)
    px = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    return pd.DataFrame({"ticker": ticker, "date": dates.date, "close": px, "adj_close": px})


def _financials(ticker: str, scale: float) -> pd.DataFrame:
    rows = []
    for i, fy in enumerate([2022, 2023, 2024, 2025]):
        rev = 1000 * scale * (1.05**i)
        items = {
            "revenue": rev,
            "ebit": rev * 0.25,
            "ebitda": rev * 0.30,
            "da": rev * 0.05,
            "capex": rev * 0.06,
            "nwc": rev * 0.10,
            "tax_expense": rev * 0.06,
            "pretax_income": rev * 0.24,
            "interest_expense": 5 * scale,
            "gross_debt": 200 * scale,
            "cash": 100 * scale,
            "shares_outstanding": 50.0,
        }
        rows += [(ticker, fy, k, v, "EUR", "test") for k, v in items.items()]
    return pd.DataFrame(
        rows, columns=["ticker", "fiscal_year", "line_item", "value", "currency", "source"]
    )


@pytest.fixture
def con():
    c = connect(":memory:")
    for i, t in enumerate(TICKERS):
        upsert(c, "fact_financials", _financials(t, 1.0 + 0.2 * i))
        upsert(c, "fact_prices", _prices(t, i))
    upsert(c, "fact_prices", _prices("^BENCH", 99))
    upsert(
        c,
        "fact_market_params",
        pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-11-10").date()],
                "rf_oat10y": [0.035],
                "erp_france": [0.05],
            }
        ),
    )
    return c


def _value(con, extraction=None):
    mult = build_multiples(con, COMPANIES, pd.Timestamp("2026-11-10"))
    return value_company(con, COMPANIES[0], SETTINGS, mult, extraction)


def test_value_company_on_seeded_db(con):
    v = _value(con, None)
    s = v.scenarios
    assert s["bear"] < s["base"] < s["bull"]
    assert v.sensitivity.shape == (5, 5)
    assert len(v.football) == 3
    assert v.extraction is None
    assert v.wacc > v.g
    assert v.drivers["base"].sources["revenue_growth"] == "historical"
    assert not math.isnan(v.tv_gordon_vs_exit_gap)
    assert v.price > 0


def test_guidance_parsing():
    ex = Extraction(
        ticker="X",
        fiscal_year=2025,
        model="m",
        extracted_at=pd.Timestamp("2026-01-01").to_pydatetime(),
        guidance=[
            GuidanceItem(
                metric="organic_growth",
                statement="growth of 5-7%",
                direction="up",
                horizon="2026",
                page=1,
            ),
            GuidanceItem(
                metric="operating_margin",
                statement="margin around 28.5%",
                direction="flat",
                horizon="2026",
                page=2,
            ),
        ],
        risks=[],
        segments=[],
    )
    g, m = guidance_from_extraction(ex)
    assert g == pytest.approx(0.06)
    assert m == pytest.approx(0.285)
    assert guidance_from_extraction(None) == (None, None)


def test_outputs_and_snapshot(con, tmp_path):
    v = _value(con)
    write_outputs([v], tmp_path)
    data = json.loads((tmp_path / "valuations.json").read_text())
    assert data[0]["ticker"] == "TGT"
    assert data[0]["upside_base"] == pytest.approx(v.scenarios["base"] / v.price - 1)
    export_snapshot(con, tmp_path / "snap")
    snap = load_snapshot(tmp_path / "snap")
    n = snap.execute("SELECT count(*) FROM fact_prices").fetchone()[0]
    assert n == con.execute("SELECT count(*) FROM fact_prices").fetchone()[0]
