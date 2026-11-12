import math
from datetime import datetime

import pandas as pd
import pytest

from cac40val.ai_extraction.models import Extraction, GuidanceItem, ManagementTone, RiskItem
from cac40val.pipeline import CompanyValuation
from cac40val.valuation import comps, dcf, wacc
from cac40val.valuation.forecast import Drivers, project

SHARES, NET_DEBT, MINOR, ASSOC = 500e6, 2e9, 1e8, 5e7
LAST_REV, LAST_NWC, PRICE = 80e9, 8e9, 100.0


def make_valuation(extraction=None) -> CompanyValuation:
    d = Drivers(
        revenue_growth=[0.06] * 5,
        ebit_margin=[0.25] * 5,
        da_pct=0.05,
        capex_pct=0.06,
        nwc_pct=0.10,
        tax_rate=0.25,
        sources={"revenue_growth": "historical", "ebit_margin": "guidance"},
    )
    proj = project(LAST_REV, LAST_NWC, d)
    rate = wacc.wacc(50e9, 10e9, 0.08, 0.03, 0.25)
    g = 0.02
    ev = dcf.enterprise_value(list(proj["fcff"]), rate, g)
    base = dcf.equity_bridge(ev, NET_DEBT, MINOR, ASSOC) / SHARES
    sens = dcf.sensitivity_grid(list(proj["fcff"]), rate, g, NET_DEBT, SHARES, MINOR, ASSOC)
    football = comps.football_field((base * 0.8, base * 1.2), (90.0, 130.0), (80.0, 120.0), PRICE)
    implied = pd.DataFrame(
        {"low": [1.0, 2.0, math.nan], "mid": [2.0, 3.0, 4.0], "high": [3.0, 4.0, 5.0]},
        index=comps.MULTIPLES,
    )
    peers = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "price_eur": [10.0, 20.0],
            "market_cap_eur": [1e9, 2e9],
            "ev_sales": [3.0, 4.0],
            "ev_ebitda": [10.0, math.nan],
            "pe": [20.0, 25.0],
        }
    )
    hist = pd.DataFrame(
        {"revenue": [70e9, 75e9, LAST_REV], "ebit": [17e9, 18e9, 20e9]},
        index=pd.Index([2023, 2024, 2025], name="fiscal_year"),
    )
    return CompanyValuation(
        ticker="TST.PA",
        price=PRICE,
        scenarios={"bear": base * 0.8, "base": base, "bull": base * 1.2},
        wacc=rate,
        g=g,
        ev_base=ev,
        sensitivity=sens,
        projections={"base": proj, "bear": proj, "bull": proj},
        drivers={"base": d, "bear": d, "bull": d},
        comps_implied=implied,
        football=football,
        extraction=extraction,
        tv_gordon_vs_exit_gap=0.12,
        last_revenue=LAST_REV,
        last_nwc=LAST_NWC,
        net_debt=NET_DEBT,
        minorities=MINOR,
        associates=ASSOC,
        shares=SHARES,
        rf=0.03,
        erp=0.05,
        beta=1.0,
        kd=0.03,
        tax=0.25,
        market_cap=50e9,
        gross_debt=10e9,
        historicals=hist,
        peers=peers,
    )


def make_extraction(tone=True) -> Extraction:
    return Extraction(
        ticker="TST.PA",
        fiscal_year=2025,
        model="m",
        extracted_at=datetime(2026, 1, 1),
        guidance=[
            GuidanceItem(
                metric="organic_growth",
                statement="growth of 5%",
                direction="up",
                horizon="2026",
                page=3,
            )
        ],
        risks=[
            RiskItem(category="fx", description="Currency headwinds", severity=2, page=10),
            RiskItem(category="demand", description="China slowdown", severity=5, page=12),
            RiskItem(category="supply", description="Supply chain", severity=3, page=14),
            RiskItem(category="legal", description="Litigation", severity=1, page=20),
        ],
        segments=[],
        management_tone=ManagementTone(label="cautious", rationale="Prudent outlook")
        if tone
        else None,
    )


@pytest.fixture
def valuation():
    return make_valuation()
