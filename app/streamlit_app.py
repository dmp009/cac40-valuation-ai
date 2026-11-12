"""Streamlit valuation explorer. Reads only the committed snapshot, AI cache and quality report."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # engine config paths are relative to the repo root

import pandas as pd
import streamlit as st

from app.charts import football_chart, sensitivity_heatmap
from app.live import recompute
from cac40val.ai_extraction.extract import get_extraction
from cac40val.config import load_companies, load_settings
from cac40val.pipeline import (
    build_multiples,
    load_snapshot,
    valuation_date,
    value_company,
)
from cac40val.valuation import comps

st.set_page_config(page_title="CAC 40 luxury valuation", page_icon="", layout="wide")

SCENARIOS = ["bear", "base", "bull"]
LOREAL_ESSILOR = ["OR.PA", "EL.PA"]
SOURCES = (
    "Yahoo Finance (prices, financial statements), ECB (OAT 10Y yield), "
    "company Universal Registration Documents (AI extraction), Damodaran (equity risk premium)."
)


@st.cache_resource(show_spinner="Loading data snapshot...")
def get_con():
    return load_snapshot(ROOT / "data" / "snapshot")


@st.cache_data
def get_companies():
    return load_companies(ROOT / "config" / "sources.yaml")


@st.cache_data
def get_settings():
    return load_settings(ROOT / "config" / "settings.yaml")


@st.cache_data
def get_valuation_date() -> pd.Timestamp:
    return valuation_date(get_con(), get_settings())


@st.cache_resource(show_spinner="Valuing company...")
def get_valuation(ticker: str):
    con, settings = get_con(), get_settings()
    companies = get_companies()
    company = next(c for c in companies if c.ticker == ticker)
    multiples = build_multiples(con, companies, get_valuation_date())
    row = con.execute(
        "SELECT max(fiscal_year) FROM fact_financials WHERE ticker = ?", [ticker]
    ).fetchone()
    extraction = None
    if row and row[0] is not None:
        extraction = get_extraction(
            company, int(row[0]), refresh=False, client=None, cache_dir=ROOT / "data" / "ai_cache"
        )
    return value_company(con, company, settings, multiples, extraction)


def fmt_eur(x: float) -> str:
    return "n/a" if pd.isna(x) else f"{x:,.2f} EUR"


def valuation_tab(v, scenario: str) -> None:
    d = v.drivers[scenario]
    st.caption(
        f"Drivers ({scenario}): growth from {d.sources['revenue_growth']}, "
        f"EBIT margin from {d.sources['ebit_margin']}. Adjust them to recompute live."
    )
    c1, c2 = st.columns(2)
    key = f"{v.ticker}-{scenario}"
    growth = c1.slider(
        "Base revenue growth (% per year)", -10.0, 25.0,
        float(min(max(d.revenue_growth[0] * 100, -10.0), 25.0)), 0.1, key=f"g-{key}",
    )  # fmt: skip
    margin = c2.slider(
        "EBIT margin (%)", 0.0, 50.0,
        float(min(max(d.ebit_margin[0] * 100, 0.0), 50.0)), 0.1, key=f"m-{key}",
    )  # fmt: skip
    live = recompute(v, scenario, growth / 100, margin / 100)
    upside = live.value_per_share / v.price - 1
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Current price", fmt_eur(v.price))
    m2.metric(f"DCF value ({scenario}, live)", fmt_eur(live.value_per_share), f"{upside:+.1%}")
    m3.metric("WACC", f"{v.wacc:.2%}")
    m4.metric("Terminal growth", f"{v.g:.2%}")

    left, right = st.columns(2)
    with left:
        st.subheader("Football field")
        st.plotly_chart(football_chart(v.football), use_container_width=True)
    with right:
        st.subheader("Sensitivity (live)")
        st.plotly_chart(sensitivity_heatmap(live.sensitivity), use_container_width=True)

    st.subheader("Scenario table")
    table = pd.DataFrame(
        {
            "Value per share (EUR)": v.scenarios,
            "vs price": {k: s / v.price - 1 for k, s in v.scenarios.items()},
            "Revenue growth": {k: d_.revenue_growth[0] for k, d_ in v.drivers.items()},
            "EBIT margin": {k: d_.ebit_margin[0] for k, d_ in v.drivers.items()},
        }
    )
    st.dataframe(
        table.style.format(
            {
                "Value per share (EUR)": "{:,.2f}",
                "vs price": "{:+.1%}",
                "Revenue growth": "{:.1%}",
                "EBIT margin": "{:.1%}",
            }
        ),
        use_container_width=True,
    )
    with st.expander("Projected free cash flow (live scenario, EUR m)"):
        st.dataframe((live.projection / 1e6).round(0), use_container_width=True)


def ai_tab(v) -> None:
    ex = v.extraction
    if ex is None:
        st.info("No AI extraction available for this company.")
        return
    st.caption(f"Extracted from the FY{ex.fiscal_year} registration document by `{ex.model}`.")
    c1, c2 = st.columns(2)
    if ex.management_tone is not None:
        c1.metric("Management tone", ex.management_tone.label.title())
        c1.write(ex.management_tone.rationale)
    else:
        c1.metric("Management tone", "n/a")
    c2.metric("Items rejected by validation", ex.rejected_count)
    st.subheader("Guidance")
    st.dataframe(
        pd.DataFrame([g.model_dump() for g in ex.guidance]).rename(columns={"page": "Page"}),
        use_container_width=True, hide_index=True,
    )  # fmt: skip
    st.subheader("Risks")
    st.dataframe(
        pd.DataFrame([r.model_dump() for r in ex.risks]).rename(columns={"page": "Page"}),
        use_container_width=True, hide_index=True,
    )  # fmt: skip


def comps_tab(v) -> None:
    exclude_lux = st.toggle("Exclude L'Oréal & EssilorLuxottica", key=f"excl-{v.ticker}")
    exclude = [v.ticker, *(LOREAL_ESSILOR if exclude_lux else [])]
    stats = comps.peer_stats(v.peers, exclude=exclude)
    peers = v.peers[~v.peers["ticker"].isin(exclude)]
    cols = ["ticker", "market_cap_eur", "ev_sales", "ev_ebitda", "pe"]
    st.subheader("Peer multiples")
    st.dataframe(
        peers[cols].set_index("ticker").style.format(
            {"market_cap_eur": "{:,.0f}", "ev_sales": "{:.2f}", "ev_ebitda": "{:.1f}", "pe": "{:.1f}"},
            na_rep="n/a",
        ),
        use_container_width=True,
    )  # fmt: skip
    st.subheader("Peer statistics")
    st.dataframe(
        stats.style.format({"q1": "{:.2f}", "median": "{:.2f}", "q3": "{:.2f}"}, na_rep="n/a")
    )
    row = v.peers[v.peers["ticker"] == v.ticker].iloc[0]
    implied = comps.implied_values(row, stats, v.shares)
    st.subheader("Implied value per share (EUR)")
    st.dataframe(implied.style.format("{:,.2f}", na_rep="n/a"), use_container_width=True)


def quality_tab() -> None:
    path = ROOT / "data_quality_report.md"
    st.markdown(path.read_text(encoding="utf-8") if path.exists() else "No report available.")


def main() -> None:
    companies = [c for c in get_companies() if c.is_target]
    names = {c.ticker: c.name for c in companies}
    st.title("CAC 40 luxury valuation explorer")
    with st.sidebar:
        ticker = st.selectbox("Company", list(names), format_func=lambda t: f"{names[t]} ({t})")
        scenario = st.radio("Scenario", SCENARIOS, index=1, horizontal=True)
        st.caption(f"Valuation date: {get_valuation_date().date()}")
    try:
        v = get_valuation(ticker)
    except ValueError as exc:
        st.error(f"Could not value {names[ticker]}: {exc}")
        return
    t1, t2, t3, t4 = st.tabs(["Valuation", "AI insights", "Comps", "Data quality"])
    with t1:
        valuation_tab(v, scenario)
    with t2:
        ai_tab(v)
    with t3:
        comps_tab(v)
    with t4:
        quality_tab()
    st.divider()
    st.caption(
        f"Educational project, not investment advice. Valuation date: "
        f"{get_valuation_date().date()}. Data sources: {SOURCES}"
    )


main()
