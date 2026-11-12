"""yfinance ingestion: financial statements, prices and FX.

All values are stored positive (capex, interest and tax are abs()'d) in full currency units.
"""

import pandas as pd

from cac40val.config import Company
from cac40val.ingest import save_raw

LINE_ITEM_MAP: dict[str, str] = {
    "Total Revenue": "revenue",
    "Operating Revenue": "revenue",
    "EBIT": "ebit",
    "Operating Income": "ebit",
    "EBITDA": "ebitda",
    "Reconciled Depreciation": "da",
    "Depreciation And Amortization In Income Statement": "da",
    "Capital Expenditure": "capex",
    "Working Capital": "nwc",
    "Tax Provision": "tax_expense",
    "Pretax Income": "pretax_income",
    "Interest Expense": "interest_expense",
    "Total Debt": "gross_debt",
    "Cash And Cash Equivalents": "cash",
    "Minority Interest": "minorities",
    "Investments In Other Ventures Under Equity Method": "associates",
    "Ordinary Shares Number": "shares_outstanding",
    "Total Assets": "total_assets",
    "Total Liabilities Net Minority Interest": "total_liabilities",
    "Stockholders Equity": "total_equity",
    "Common Stock Equity": "total_equity",
}
_ABS_ITEMS = {"capex", "interest_expense", "tax_expense"}
# When several labels map to one item, the first one listed in LINE_ITEM_MAP wins.
_PRIORITY = {label: i for i, label in enumerate(LINE_ITEM_MAP)}
FIN_COLUMNS = ["ticker", "fiscal_year", "line_item", "value", "currency", "source"]


def normalize_statements(raw: pd.DataFrame, ticker: str, currency: str) -> pd.DataFrame:
    """Wide yfinance frame (rows=labels, columns=period ends) -> long fact_financials rows."""
    rows = []
    for label in raw.index:
        item = LINE_ITEM_MAP.get(label)
        if item is None:
            continue
        for period, value in raw.loc[label].items():
            if pd.isna(value):
                continue
            value = float(value)
            if item in _ABS_ITEMS:
                value = abs(value)
            rows.append(
                (
                    ticker,
                    int(pd.Timestamp(period).year),
                    item,
                    value,
                    currency,
                    "yfinance",
                    _PRIORITY[label],
                )
            )
    df = pd.DataFrame(rows, columns=[*FIN_COLUMNS, "_prio"]).sort_values("_prio", kind="stable")
    df = df.drop_duplicates(["ticker", "fiscal_year", "line_item"]).drop(columns="_prio")
    return df.sort_values(["line_item", "fiscal_year"]).reset_index(drop=True)


def fetch_prices(ticker: str, period: str = "5y") -> pd.DataFrame:
    import yfinance as yf

    hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    save_raw("yfinance_prices", hist.to_csv(), "csv")
    out = pd.DataFrame(
        {
            "ticker": ticker,
            "date": pd.to_datetime(hist.index).tz_localize(None).normalize().date,
            "close": hist["Close"].to_numpy(),
            "adj_close": hist["Adj Close"].to_numpy(),
        }
    )
    return out.dropna(subset=["close"]).reset_index(drop=True)


def fetch_company(company: Company) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (financials long, prices) for a company. Missing items are simply absent."""
    import yfinance as yf

    t = yf.Ticker(company.ticker)
    frames = []
    for name, stmt in (
        ("income", t.financials),
        ("balance", t.balance_sheet),
        ("cashflow", t.cashflow),
    ):
        if stmt is None or stmt.empty:
            continue
        save_raw(f"yfinance_{name}", stmt.to_csv(), "csv")
        frames.append(normalize_statements(stmt, company.ticker, company.currency))
    fin = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=FIN_COLUMNS)
    # first statement wins on duplicates (income before balance before cash flow)
    fin = fin.drop_duplicates(["ticker", "fiscal_year", "line_item"]).reset_index(drop=True)
    return fin, fetch_prices(company.ticker)


def fetch_fx(currency: str, date: str) -> float:
    """EUR per 1 unit of `currency`, close on or just before `date`."""
    if currency == "EUR":
        return 1.0
    import yfinance as yf

    end = pd.Timestamp(date) + pd.Timedelta(days=1)
    hist = yf.Ticker(f"{currency}EUR=X").history(
        start=end - pd.Timedelta(days=10), end=end, auto_adjust=False
    )
    save_raw("yfinance_fx", hist.to_csv(), "csv")
    if hist.empty:
        raise ValueError(f"No FX data for {currency} around {date}")
    return float(hist["Close"].iloc[-1])
