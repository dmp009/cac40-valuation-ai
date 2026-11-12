from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py")
TICKERS = ["MC.PA", "RMS.PA", "KER.PA", "OR.PA", "EL.PA"]


@pytest.mark.parametrize("ticker", TICKERS)
def test_app_runs_for_each_company(ticker):
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    at.sidebar.selectbox[0].select(ticker).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 4
    assert any("not investment advice" in c.value for c in at.caption)


def test_app_scenario_and_comps_toggle():
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.sidebar.radio[0].set_value("bull").run()
    at.toggle[0].set_value(True).run()
    assert not at.exception


def _live_metric(at, scenario):
    return next(m for m in at.metric if m.label == f"DCF value ({scenario}, live)").value


@pytest.mark.parametrize("ticker", ["KER.PA", "MC.PA"])
def test_live_value_matches_scenario_table_in_bear_case(ticker):
    """Default sliders must reproduce the table exactly (no silent clamping of the drivers)."""
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.sidebar.selectbox[0].select(ticker).run()
    at.sidebar.radio[0].set_value("bear").run()
    assert not at.exception
    table = at.dataframe[0].value
    expected = float(table.loc["bear", "Value per share (EUR)"])
    assert _live_metric(at, "bear") == f"{expected:,.2f} EUR"
    growth = next(s for s in at.slider if s.label.startswith("Base revenue growth"))
    assert growth.min <= growth.value <= growth.max


def test_app_source_has_no_deprecated_width_arg():
    src = Path(APP).read_text(encoding="utf-8")
    assert "use_container_width" not in src
    assert 'page_icon=""' not in src
