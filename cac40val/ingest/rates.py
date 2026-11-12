"""Risk-free rate (ECB French 10y OAT yield) and Damodaran equity risk premium."""

from io import StringIO
from pathlib import Path

import pandas as pd

from cac40val.ingest import save_raw

ECB_URL = (
    "https://data-api.ecb.europa.eu/service/data/IRS/M.FR.L.L40.CI.0000.EUR.N.Z?format=csvdata"
)


def parse_ecb_csv(text: str) -> pd.DataFrame:
    """ECB SDMX CSV -> columns date, rf_oat10y (percent converted to decimal)."""
    raw = pd.read_csv(StringIO(text))
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["TIME_PERIOD"]).dt.date,
            "rf_oat10y": pd.to_numeric(raw["OBS_VALUE"], errors="coerce") / 100.0,
        }
    )
    return out.dropna(subset=["rf_oat10y"]).reset_index(drop=True)


def fetch_oat10y() -> pd.DataFrame:
    import requests

    resp = requests.get(ECB_URL, timeout=30)
    resp.raise_for_status()
    save_raw("ecb", resp.text, "csv")
    return parse_ecb_csv(resp.text)


def load_erp(
    path: Path = Path("data/reference/damodaran_erp.csv"), country: str = "France"
) -> float:
    df = pd.read_csv(path)
    row = df[df["country"] == country]
    if row.empty:
        raise ValueError(f"No ERP row for {country} in {path}")
    value = row.iloc[0]["erp"]
    if pd.isna(value):
        raise ValueError(f"ERP for {country} is empty in {path}; fill it from Damodaran's file")
    return float(value)
