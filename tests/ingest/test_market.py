import pandas as pd

from cac40val.config import Company
from cac40val.ingest.market import LINE_ITEM_MAP, normalize_statements
from cac40val.valuation.forecast import CANONICAL_ITEMS


def _raw():
    return pd.read_csv("tests/fixtures/yf_income.csv", index_col=0)


def test_normalize_statements_maps_and_drops():
    df = normalize_statements(_raw(), "MC.PA", "EUR")
    assert set(df["line_item"]) <= set(CANONICAL_ITEMS)
    assert set(df["line_item"]) == {"revenue", "ebit", "capex", "interest_expense", "tax_expense"}
    assert df["fiscal_year"].dtype.kind == "i"
    assert set(df["fiscal_year"]) == {2023, 2024}
    assert (df["source"] == "yfinance").all() and (df["currency"] == "EUR").all()
    assert (df["ticker"] == "MC.PA").all()


def test_normalize_statements_capex_stored_positive():
    df = normalize_statements(_raw(), "MC.PA", "EUR")
    row = df[(df.line_item == "capex") & (df.fiscal_year == 2024)].iloc[0]
    assert row["value"] == 5_000_000_000


def test_line_item_map_values_canonical():
    assert set(LINE_ITEM_MAP.values()) <= set(CANONICAL_ITEMS)


def test_normalize_drops_nan():
    raw = _raw()
    raw.loc["EBIT", "2023-12-31"] = float("nan")
    df = normalize_statements(raw, "MC.PA", "EUR")
    assert len(df[df.line_item == "ebit"]) == 1


def test_download_deu_none_when_no_url(tmp_path):
    from cac40val.ingest.deu import download_deu

    c = Company("MC.PA", "LVMH", "EUR", True, deu_url=None)
    assert download_deu(c, tmp_path) is None


def test_download_deu_skips_existing(tmp_path):
    from cac40val.ingest.deu import download_deu

    c = Company("MC.PA", "LVMH", "EUR", True, deu_url="http://invalid.test/x.pdf")
    (tmp_path / "MC.PA.pdf").write_bytes(b"x")
    assert download_deu(c, tmp_path) == tmp_path / "MC.PA.pdf"


def test_nwc_operating_from_components():
    raw = pd.DataFrame(
        {pd.Timestamp("2024-12-31"): [100.0, 50.0, 30.0, 900.0, 700.0]},
        index=[
            "Receivables",
            "Inventory",
            "Payables",
            "Working Capital",
            "Cash And Cash Equivalents",
        ],
    )
    df = normalize_statements(raw, "X", "EUR")
    assert df.loc[df.line_item == "nwc", "value"].iloc[0] == 120.0


def test_nwc_fallback_excludes_cash():
    raw = pd.DataFrame(
        {pd.Timestamp("2024-12-31"): [900.0, 700.0]},
        index=["Working Capital", "Cash And Cash Equivalents"],
    )
    df = normalize_statements(raw, "X", "EUR")
    assert df.loc[df.line_item == "nwc", "value"].iloc[0] == 200.0


class _FakeTicker:
    """Minimal stand-in for yfinance.Ticker: EUR financials, HKD-listed."""

    def __init__(self, info=None, info_error=False):
        self._info, self._info_error = info, info_error
        period = pd.Timestamp("2024-12-31")
        self.financials = pd.DataFrame({period: [1000.0, 200.0]}, index=["Total Revenue", "EBIT"])
        self.balance_sheet = pd.DataFrame()
        self.cashflow = pd.DataFrame()

    @property
    def info(self):
        if self._info_error:
            raise RuntimeError("info endpoint down")
        return self._info

    def history(self, **kw):
        idx = pd.DatetimeIndex(["2026-11-09", "2026-11-10"])
        return pd.DataFrame({"Close": [50.0, 51.0], "Adj Close": [50.0, 51.0]}, index=idx)


def _patch_yf(monkeypatch, ticker):
    import yfinance

    from cac40val.ingest import market

    monkeypatch.setattr(yfinance, "Ticker", lambda symbol: ticker)
    monkeypatch.setattr(market, "save_raw", lambda *a, **k: None)


def test_fetch_company_uses_yfinance_financial_currency(monkeypatch):
    from cac40val.ingest.market import fetch_company

    _patch_yf(monkeypatch, _FakeTicker(info={"financialCurrency": "EUR", "currency": "HKD"}))
    fin, prices = fetch_company(Company("1913.HK", "Prada", "HKD", False))
    assert set(fin["currency"]) == {"EUR"}
    assert prices["close"].iloc[-1] == 51.0


def test_fetch_company_falls_back_to_configured_reporting_currency(monkeypatch):
    from cac40val.ingest.market import fetch_company

    _patch_yf(monkeypatch, _FakeTicker(info_error=True))
    co = Company("CFR.SW", "Richemont", "CHF", False, reporting_currency="EUR")
    fin, _ = fetch_company(co)
    assert set(fin["currency"]) == {"EUR"}


def test_fetch_company_falls_back_to_listing_currency(monkeypatch):
    from cac40val.ingest.market import fetch_company

    _patch_yf(monkeypatch, _FakeTicker(info={}))
    fin, _ = fetch_company(Company("X.SW", "X", "CHF", False))
    assert set(fin["currency"]) == {"CHF"}


def test_fetch_company_warns_on_currency_disagreement(monkeypatch, caplog):
    from cac40val.ingest.market import fetch_company

    _patch_yf(monkeypatch, _FakeTicker(info={"financialCurrency": "USD"}))
    co = Company("CFR.SW", "Richemont", "CHF", False, reporting_currency="EUR")
    fin, _ = fetch_company(co)
    assert set(fin["currency"]) == {"USD"}
    assert "disagrees" in caplog.text
