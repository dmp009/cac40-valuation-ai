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


def seed_db():
    """In-memory warehouse with 4 EUR companies, a benchmark and market params."""
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


@pytest.fixture
def con():
    return seed_db()


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


def test_listing_currency_converts_price_but_not_eur_financials(con):
    """HKD-listed peer reporting in EUR: price uses HKD FX, financials stay in EUR."""
    upsert(con, "fact_financials", _financials("HKP", 1.0))  # currency EUR
    upsert(con, "fact_prices", _prices("HKP", 7))
    upsert(
        con,
        "fact_fx",
        pd.DataFrame(
            {
                "date": [pd.Timestamp("2026-11-10").date()],
                "currency": ["HKD"],
                "eur_per_unit": [0.1],
            }
        ),
    )
    peer = Company("HKP", "HKP", "HKD", False, reporting_currency="EUR")
    mult = build_multiples(con, [*COMPANIES, peer], pd.Timestamp("2026-11-10"))
    row = mult[mult["ticker"] == "HKP"].iloc[0]
    close = con.execute(
        "SELECT close FROM fact_prices WHERE ticker='HKP' ORDER BY date DESC LIMIT 1"
    ).fetchone()[0]
    assert row["price_eur"] == pytest.approx(close * 0.1)
    assert row["revenue_eur"] == pytest.approx(1000 * 1.05**3)
    assert row["fx_fin"] == 1.0


def test_value_company_uses_normalized_terminal_fcff(con):
    from cac40val.valuation import dcf

    v = _value(con)
    base, d = v.projections["base"], v.drivers["base"]

    def tf(g):
        return dcf.normalized_terminal_fcff(
            base["revenue"].iloc[-1], d.ebit_margin[-1], d.tax_rate,
            d.da_pct, d.capex_pct, d.nwc_pct, g,
        )  # fmt: skip

    fcffs = list(base["fcff"])
    tv = tf(v.g) / (v.wacc - v.g)
    ev = dcf.discount(fcffs, v.wacc) + tv / (1 + v.wacc) ** 5
    assert v.ev_base == pytest.approx(ev)
    per_share = dcf.equity_bridge(ev, v.net_debt, v.minorities, v.associates) / v.shares
    assert v.scenarios["base"] == pytest.approx(per_share)
    assert v.sensitivity.iloc[2, 2] == pytest.approx(per_share)
    exit_tv = base["ebitda"].iloc[-1] * comps_median(v)
    assert v.tv_gordon_vs_exit_gap == pytest.approx((tv - exit_tv) / exit_tv)


def comps_median(v):
    from cac40val.valuation import comps

    return comps.peer_stats(v.peers, exclude=[v.ticker]).loc["ev_ebitda", "median"]


def test_year1_delta_nwc_ignores_actual_nwc_level(con):
    # Seeded actual NWC is 10% of revenue; make the latest year an outlier at 30%.
    con.execute(
        "UPDATE fact_financials SET value = value * 3 "
        "WHERE ticker = 'TGT' AND line_item = 'nwc' AND fiscal_year = 2025"
    )
    v = _value(con)
    base, d = v.projections["base"], v.drivers["base"]
    expected = d.nwc_pct * (base["revenue"].iloc[0] - v.last_revenue)
    assert base["delta_nwc"].iloc[0] == pytest.approx(expected)
    assert v.last_nwc != pytest.approx(v.last_revenue * d.nwc_pct)


def test_run_extractions_survives_a_failing_company(con, monkeypatch, caplog):
    import logging

    from cac40val import pipeline

    good = Extraction(
        ticker="P1", fiscal_year=2025, model="m",
        extracted_at=pd.Timestamp("2026-01-01").to_pydatetime(),
        guidance=[], risks=[], segments=[],
    )  # fmt: skip

    def fake(company, fy, *, refresh, client):
        if company.ticker == "TGT":
            raise RuntimeError("API error 529")
        return good

    monkeypatch.setattr(pipeline, "get_extraction", fake)
    targets = [COMPANIES[0], COMPANIES[1]]
    with caplog.at_level(logging.ERROR):
        out = pipeline.run_extractions(con, targets, refresh=False, client=None)
    assert out == {"TGT": None, "P1": good}
    assert "AI extraction failed for TGT" in caplog.text
