import math

import pandas as pd
import pytest

from cac40val.valuation.comps import (
    compute_multiples,
    football_field,
    implied_values,
    peer_stats,
)


def _peers(**over):
    rows = [
        {
            "ticker": "A.PA",
            "market_cap_eur": 1000,
            "net_debt_eur": 100,
            "minorities_eur": 0,
            "revenue_eur": 500,
            "ebitda_eur": 110,
            "net_income_eur": 50,
        },
        {
            "ticker": "B.PA",
            "market_cap_eur": 2000,
            "net_debt_eur": 0,
            "minorities_eur": 0,
            "revenue_eur": 800,
            "ebitda_eur": 200,
            "net_income_eur": 100,
        },
        {
            "ticker": "OR.PA",
            "market_cap_eur": 3000,
            "net_debt_eur": 0,
            "minorities_eur": 0,
            "revenue_eur": 1000,
            "ebitda_eur": 300,
            "net_income_eur": 150,
        },
        {
            "ticker": "EL.PA",
            "market_cap_eur": 900,
            "net_debt_eur": 0,
            "minorities_eur": 0,
            "revenue_eur": 300,
            "ebitda_eur": 90,
            "net_income_eur": 30,
        },
    ]
    return pd.DataFrame(rows)


def test_multiples_basic():
    m = compute_multiples(_peers()).iloc[0]
    assert m["ev_sales"] == pytest.approx(2.2)
    assert m["ev_ebitda"] == pytest.approx(10.0)
    assert m["pe"] == pytest.approx(20.0)


def test_negative_ebitda_excluded():
    p = _peers()
    p.loc[1, "ebitda_eur"] = -10
    m = compute_multiples(p)
    assert math.isnan(m.loc[1, "ev_ebitda"])
    assert peer_stats(m).loc["ev_ebitda", "n"] == 3


def test_peer_stats_exclude():
    m = compute_multiples(_peers())
    full = peer_stats(m)
    sub = peer_stats(m, exclude=["OR.PA", "EL.PA"])
    assert full.loc["pe", "n"] - sub.loc["pe", "n"] == 2
    assert full.loc["pe", "median"] == pytest.approx(m["pe"].median())


def test_implied_values_ev_bridge():
    stats = pd.DataFrame(
        {
            "q1": [1.0, 8.0, 10.0],
            "median": [2.0, 10.0, 15.0],
            "q3": [3.0, 12.0, 20.0],
            "n": [3, 3, 3],
        },
        index=["ev_sales", "ev_ebitda", "pe"],
    )
    target = pd.Series(
        {
            "revenue_eur": 500,
            "ebitda_eur": 100,
            "net_income_eur": 40,
            "net_debt_eur": 200,
            "minorities_eur": 0,
        }
    )
    out = implied_values(target, stats, shares=80)
    assert out.loc["ev_ebitda", "mid"] == pytest.approx(10.0)
    assert out.loc["ev_ebitda", "low"] == pytest.approx(7.5)
    assert out.loc["pe", "high"] == pytest.approx(10.0)
    target["ebitda_eur"] = -1
    assert math.isnan(implied_values(target, stats, 80).loc["ev_ebitda", "mid"])


def test_football_field_rows():
    ff = football_field((80, 120), (90, 110), (70, 130), price=100)
    assert list(ff.index) == ["DCF (bear–bull)", "Trading comps (IQR)", "52-week range"]
    assert list(ff.columns) == ["low", "high"]
    assert ff.attrs["price"] == 100
