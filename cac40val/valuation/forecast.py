"""Historical drivers, scenario construction and 5-year projection (no I/O)."""

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from cac40val.valuation.dcf import fcff, normalized_terminal_fcff

logger = logging.getLogger(__name__)

CANONICAL_ITEMS = [
    "revenue",
    "ebit",
    "ebitda",
    "da",
    "capex",
    "nwc",
    "tax_expense",
    "pretax_income",
    "interest_expense",
    "gross_debt",
    "cash",
    "minorities",
    "associates",
    "shares_outstanding",
    "total_assets",
    "total_liabilities",
    "total_equity",
]
HORIZON = 5
GROWTH_SPREAD = 0.03
MARGIN_SPREAD = 0.02
_SCALAR_DRIVERS = ("da_pct", "capex_pct", "nwc_pct")
_PATH_DRIVERS = ("revenue_growth", "ebit_margin")
SCENARIOS = ("bear", "base", "bull")


@dataclass
class Drivers:
    revenue_growth: list[float]
    ebit_margin: list[float]
    da_pct: float
    capex_pct: float
    nwc_pct: float
    tax_rate: float
    sources: dict[str, str]


def _mean_ratio(wide: pd.DataFrame, num: str, den: str) -> float:
    if num not in wide or den not in wide:
        return math.nan
    ratio = (wide[num] / wide[den]).dropna()
    return float(ratio.mean()) if len(ratio) else math.nan


def historical_drivers(fin: pd.DataFrame) -> dict:
    """Average historical drivers from a long frame (fiscal_year, line_item, value)."""
    wide = fin.pivot_table(index="fiscal_year", columns="line_item", values="value").sort_index()
    growth = math.nan
    if "revenue" in wide:
        g = wide["revenue"].pct_change().dropna()
        growth = float(g.mean()) if len(g) else math.nan
    return {
        "revenue_growth": growth,
        "ebit_margin": _mean_ratio(wide, "ebit", "revenue"),
        "da_pct": _mean_ratio(wide, "da", "revenue"),
        "capex_pct": _mean_ratio(wide, "capex", "revenue"),
        "nwc_pct": _mean_ratio(wide, "nwc", "revenue"),
        "effective_tax_rate": _mean_ratio(wide, "tax_expense", "pretax_income"),
        "missing": sorted(set(CANONICAL_ITEMS) - set(wide.columns)),
    }


def _expand(value: float | list[float], name: str) -> list[float]:
    if isinstance(value, (list, tuple)):
        if len(value) != HORIZON:
            raise ValueError(f"Override '{name}' must have {HORIZON} values, got {len(value)}")
        return [float(v) for v in value]
    return [float(value)] * HORIZON


def _scalar(value, name: str) -> float:
    if isinstance(value, (list, tuple)):
        raise TypeError(f"Override '{name}' must be a single value, got a list")
    return float(value)


def _warn_unknown_overrides(overrides: dict) -> None:
    for scenario, ov in overrides.items():
        if scenario not in SCENARIOS:
            logger.warning("Ignoring override for unknown scenario '%s'", scenario)
            continue
        for key in set(ov or {}) - {*_PATH_DRIVERS, *_SCALAR_DRIVERS}:
            logger.warning("Ignoring unknown override '%s' in scenario '%s'", key, scenario)


def _require(hist: dict, key: str) -> float:
    v = hist.get(key)
    if v is None or (isinstance(v, float) and math.isnan(v)):
        raise ValueError(f"Historical driver '{key}' is missing")
    return float(v)


def build_scenarios(
    hist: dict,
    guidance_growth: float | None,
    guidance_margin: float | None,
    overrides: dict,
    tax_rate: float,
) -> dict[str, Drivers]:
    """Bear/base/bull drivers; base = guidance else history, spreads +/-3pp growth, +/-2pp margin.

    ``overrides`` maps scenario -> {driver: value}. ``revenue_growth`` and ``ebit_margin`` take
    one value or five yearly values; ``da_pct``, ``capex_pct`` and ``nwc_pct`` take one value.
    Unknown scenarios or drivers are logged and ignored.
    """
    scalars = {k: _require(hist, k) for k in _SCALAR_DRIVERS}
    if guidance_growth is not None:
        base_g, g_src = guidance_growth, "guidance"
    else:
        base_g, g_src = _require(hist, "revenue_growth"), "historical"
    if guidance_margin is not None:
        base_m, m_src = guidance_margin, "guidance"
    else:
        base_m, m_src = _require(hist, "ebit_margin"), "historical"

    overrides = overrides or {}
    _warn_unknown_overrides(overrides)
    shifts = {"bear": -1, "base": 0, "bull": 1}
    out: dict[str, Drivers] = {}
    for name, sign in shifts.items():
        growth = [base_g + sign * GROWTH_SPREAD] * HORIZON
        margin = [base_m + sign * MARGIN_SPREAD] * HORIZON
        sources = {"revenue_growth": g_src, "ebit_margin": m_src}
        sources.update({k: "historical" for k in _SCALAR_DRIVERS})
        values = dict(scalars)
        ov = overrides.get(name) or {}
        if "revenue_growth" in ov:
            growth, sources["revenue_growth"] = (
                _expand(ov["revenue_growth"], "revenue_growth"),
                "override",
            )
        if "ebit_margin" in ov:
            margin, sources["ebit_margin"] = _expand(ov["ebit_margin"], "ebit_margin"), "override"
        for key in _SCALAR_DRIVERS:
            if key in ov:
                values[key], sources[key] = _scalar(ov[key], key), "override"
        out[name] = Drivers(
            revenue_growth=growth, ebit_margin=margin, tax_rate=tax_rate, sources=sources, **values
        )
    return out


def project(last_revenue: float, d: Drivers) -> pd.DataFrame:
    """Project years 1..5: revenue, EBIT, D&A, capex, NWC, change in NWC, FCFF, EBITDA.

    NWC is modelled as ``nwc_pct`` of revenue in every year, including the opening (year 0)
    balance, so year-1 change in NWC is ``nwc_pct * (revenue_1 - last_revenue)``. Starting from
    the actual NWC level instead would book the whole gap between the latest ratio and the
    historical average as a one-off year-1 cash flow.
    """
    rows = []
    revenue, prev_nwc = last_revenue, last_revenue * d.nwc_pct
    for g, m in zip(d.revenue_growth, d.ebit_margin, strict=True):
        revenue = revenue * (1 + g)
        ebit = revenue * m
        da = revenue * d.da_pct
        capex = revenue * d.capex_pct
        nwc = revenue * d.nwc_pct
        delta = nwc - prev_nwc
        rows.append(
            {
                "revenue": revenue,
                "ebit": ebit,
                "da": da,
                "capex": capex,
                "nwc": nwc,
                "delta_nwc": delta,
                "fcff": fcff(ebit, d.tax_rate, da, capex, delta),
                "ebitda": ebit + da,
            }
        )
        prev_nwc = nwc
    return pd.DataFrame(rows, index=range(1, len(rows) + 1))


def terminal_fcff_fn(proj: pd.DataFrame, d: Drivers) -> Callable[[float], float]:
    """Year-6 FCFF as a function of terminal growth g, from year-5 revenue and drivers."""
    revenue_n = float(proj["revenue"].iloc[-1])
    margin_n = float(d.ebit_margin[-1])

    def terminal_fcff(g: float) -> float:
        return normalized_terminal_fcff(
            revenue_n, margin_n, d.tax_rate, d.da_pct, d.capex_pct, d.nwc_pct, g
        )

    return terminal_fcff
