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
