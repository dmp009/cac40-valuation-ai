"""Trading comparables and football-field data (EUR inputs, no I/O)."""

from collections.abc import Sequence

import numpy as np
import pandas as pd

MULTIPLES = ["ev_sales", "ev_ebitda", "pe"]


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    """Ratio that is NaN wherever the denominator is <= 0 or missing."""
    den = den.where(den > 0)
    return num / den


def compute_multiples(peers: pd.DataFrame) -> pd.DataFrame:
    """Add ev_sales, ev_ebitda and pe columns; NaN when the denominator <= 0."""
    out = peers.copy()
    ev = out["market_cap_eur"] + out["net_debt_eur"] + out["minorities_eur"]
    out["ev_sales"] = _safe_div(ev, out["revenue_eur"])
    out["ev_ebitda"] = _safe_div(ev, out["ebitda_eur"])
    out["pe"] = _safe_div(out["market_cap_eur"], out["net_income_eur"])
    return out


def peer_stats(multiples: pd.DataFrame, exclude: Sequence[str] = ()) -> pd.DataFrame:
    """Quartiles, median and count of valid peers per multiple."""
    df = multiples[~multiples["ticker"].isin(list(exclude))]
    rows = {}
    for m in MULTIPLES:
        s = df[m].dropna()
        rows[m] = {
            "q1": s.quantile(0.25),
            "median": s.median(),
            "q3": s.quantile(0.75),
            "n": int(s.count()),
        }
    return pd.DataFrame.from_dict(rows, orient="index")[["q1", "median", "q3", "n"]]


def implied_values(target: pd.Series, stats: pd.DataFrame, shares: float) -> pd.DataFrame:
    """Per-share low/mid/high from peer quartiles; NaN when the target metric <= 0."""
    metric = {
        "ev_sales": target["revenue_eur"],
        "ev_ebitda": target["ebitda_eur"],
        "pe": target["net_income_eur"],
    }
    bridge = target["net_debt_eur"] + target["minorities_eur"]
    cols = {"low": "q1", "mid": "median", "high": "q3"}
    out = pd.DataFrame(index=MULTIPLES, columns=list(cols), dtype=float)
    for m in MULTIPLES:
        for col, stat in cols.items():
            if not metric[m] > 0:
                out.loc[m, col] = np.nan
                continue
            value = stats.loc[m, stat] * metric[m]
            if m != "pe":
                value -= bridge
            out.loc[m, col] = value / shares
    return out


def football_field(
    dcf_range: tuple[float, float],
    comps_range: tuple[float, float],
    week52: tuple[float, float],
    price: float,
) -> pd.DataFrame:
    """Valuation ranges per method; current price stored in ``attrs['price']``."""
    df = pd.DataFrame(
        [dcf_range, comps_range, week52],
        index=["DCF (bear–bull)", "Trading comps (IQR)", "52-week range"],
        columns=["low", "high"],
        dtype=float,
    )
    df.attrs["price"] = price
    return df
