"""Live recomputation with slider overrides, delegating to the valuation engine."""

from dataclasses import dataclass, replace

import pandas as pd

from cac40val.pipeline import CompanyValuation
from cac40val.valuation import dcf
from cac40val.valuation.forecast import HORIZON, project


@dataclass
class LiveResult:
    value_per_share: float
    ev: float
    projection: pd.DataFrame
    sensitivity: pd.DataFrame


def recompute(v: CompanyValuation, scenario: str, growth: float, margin: float) -> LiveResult:
    """Re-run projection + DCF for ``scenario`` with flat growth/margin overrides."""
    drivers = replace(
        v.drivers[scenario],
        revenue_growth=[growth] * HORIZON,
        ebit_margin=[margin] * HORIZON,
    )
    proj = project(v.last_revenue, v.last_nwc, drivers)
    fcffs = list(proj["fcff"])
    ev = dcf.enterprise_value(fcffs, v.wacc, v.g)
    per_share = dcf.equity_bridge(ev, v.net_debt, v.minorities, v.associates) / v.shares
    sens = dcf.sensitivity_grid(
        fcffs, v.wacc, v.g, v.net_debt, v.shares, v.minorities, v.associates
    )
    return LiveResult(per_share, float(ev), proj, sens)
