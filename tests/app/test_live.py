import pytest

from app.live import recompute
from tests.outputs.conftest import make_valuation


def test_recompute_with_unchanged_drivers_matches_engine():
    v = make_valuation()
    d = v.drivers["base"]
    out = recompute(v, "base", d.revenue_growth[0], d.ebit_margin[0])
    assert out.value_per_share == pytest.approx(v.scenarios["base"])
    assert out.sensitivity.shape == (5, 5)


def test_higher_margin_raises_value():
    v = make_valuation()
    d = v.drivers["base"]
    lo = recompute(v, "base", d.revenue_growth[0], d.ebit_margin[0])
    hi = recompute(v, "base", d.revenue_growth[0], d.ebit_margin[0] + 0.05)
    assert hi.value_per_share > lo.value_per_share
