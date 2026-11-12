from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cac40val.valuation.forecast import Drivers, build_scenarios, historical_drivers, project

FIXTURE = Path(__file__).parent.parent / "fixtures" / "financials_sample.csv"


@pytest.fixture
def fin():
    return pd.read_csv(FIXTURE)


def _hist(**kw):
    h = {
        "revenue_growth": 0.10,
        "ebit_margin": 0.25,
        "da_pct": 0.05,
        "capex_pct": 0.06,
        "nwc_pct": 0.10,
        "effective_tax_rate": 0.25,
        "missing": [],
    }
    h.update(kw)
    return h


def test_historical_drivers_from_fixture(fin):
    h = historical_drivers(fin)
    assert h["revenue_growth"] == pytest.approx(0.10)
    assert h["ebit_margin"] == pytest.approx(0.25)
    assert h["da_pct"] == pytest.approx(0.05)
    assert h["capex_pct"] == pytest.approx(0.06)
    assert h["nwc_pct"] == pytest.approx(0.10)
    assert h["effective_tax_rate"] == pytest.approx(0.25)
    assert h["missing"] == []


def test_missing_line_item_is_flagged(fin):
    h = historical_drivers(fin[fin["line_item"] != "minorities"])
    assert "minorities" in h["missing"]


def test_missing_driver_item_gives_nan(fin):
    h = historical_drivers(fin[fin["line_item"] != "capex"])
    assert "capex" in h["missing"]
    assert np.isnan(h["capex_pct"])
    with pytest.raises(ValueError, match="capex_pct"):
        build_scenarios(h, None, None, {}, 0.258)


def test_scenarios_spread():
    s = build_scenarios(_hist(), None, None, {}, 0.258)
    assert s["bear"].revenue_growth == pytest.approx([0.07] * 5)
    assert s["bear"].ebit_margin == pytest.approx([0.23] * 5)
    assert s["bull"].revenue_growth == pytest.approx([0.13] * 5)
    assert s["bull"].ebit_margin == pytest.approx([0.27] * 5)
    for d in s.values():
        assert d.sources["revenue_growth"] == "historical"
        assert d.sources["ebit_margin"] == "historical"
        assert d.tax_rate == 0.258
        assert d.da_pct == 0.05


def test_guidance_overrides_base_source():
    s = build_scenarios(_hist(), 0.08, None, {}, 0.258)
    assert s["base"].revenue_growth == pytest.approx([0.08] * 5)
    assert s["base"].sources["revenue_growth"] == "guidance"
    assert s["base"].sources["ebit_margin"] == "historical"
    assert s["bear"].revenue_growth == pytest.approx([0.05] * 5)


def test_yaml_override_wins():
    s = build_scenarios(_hist(), None, None, {"base": {"ebit_margin": 0.30}}, 0.258)
    assert s["base"].ebit_margin == [0.30] * 5
    assert s["base"].sources["ebit_margin"] == "override"
    assert s["bear"].sources["ebit_margin"] == "historical"


def test_override_list_and_bad_length():
    g = [0.1, 0.09, 0.08, 0.07, 0.06]
    s = build_scenarios(_hist(), None, None, {"bull": {"revenue_growth": g}}, 0.258)
    assert s["bull"].revenue_growth == g
    with pytest.raises(ValueError):
        build_scenarios(_hist(), None, None, {"bull": {"revenue_growth": [0.1, 0.1]}}, 0.258)


def test_project_fcff_year1():
    d = Drivers([0.10] * 5, [0.25] * 5, 0.05, 0.06, 0.10, 0.25, {})
    df = project(100, d)
    assert list(df.index) == [1, 2, 3, 4, 5]
    assert list(df.columns) == [
        "revenue",
        "ebit",
        "da",
        "capex",
        "nwc",
        "delta_nwc",
        "fcff",
        "ebitda",
    ]
    r = df.loc[1]
    assert r["revenue"] == pytest.approx(110)
    assert r["ebit"] == pytest.approx(27.5)
    assert r["delta_nwc"] == pytest.approx(1.0)
    assert r["fcff"] == pytest.approx(18.525)
    assert r["ebitda"] == pytest.approx(27.5 + 5.5)
    assert df.loc[2, "delta_nwc"] == pytest.approx(1.1)


def test_year1_delta_nwc_uses_driver_basis_not_actual_level():
    """Year-1 dNWC is measured on the same NWC%-of-revenue basis as later years.

    The latest actual NWC level (e.g. 30, far from 10% of revenue) must not leak into year 1.
    """
    d = Drivers([0.10] * 5, [0.25] * 5, 0.05, 0.06, 0.10, 0.25, {})
    df = project(100, d)
    rev1 = df.loc[1, "revenue"]
    assert df.loc[1, "delta_nwc"] == pytest.approx(rev1 * 0.10 - 100 * 0.10)
    assert df.loc[1, "delta_nwc"] == pytest.approx(0.10 * (rev1 - 100))
