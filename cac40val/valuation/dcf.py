"""Discounted cash flow engine (end-of-year convention, no I/O)."""

from collections.abc import Sequence

import numpy as np
import pandas as pd

RATE_OFFSETS = [-0.01, -0.005, 0.0, 0.005, 0.01]
G_OFFSETS = [-0.005, -0.0025, 0.0, 0.0025, 0.005]


def fcff(ebit: float, tax_rate: float, da: float, capex: float, delta_nwc: float) -> float:
    """Free cash flow to the firm: EBIT(1-t) + D&A - capex - change in NWC."""
    return ebit * (1 - tax_rate) + da - capex - delta_nwc


def discount(cash_flows: Sequence[float], rate: float) -> float:
    """Present value of cash flows received at the end of years 1..n."""
    return float(sum(cf / (1 + rate) ** t for t, cf in enumerate(cash_flows, start=1)))


def gordon_terminal_value(last_fcff: float, rate: float, g: float) -> float:
    """Terminal value at year n by the Gordon growth model."""
    if rate <= g:
        raise ValueError(f"Discount rate ({rate}) must exceed terminal growth ({g})")
    return last_fcff * (1 + g) / (rate - g)


def exit_multiple_terminal_value(last_ebitda: float, multiple: float) -> float:
    """Terminal value at year n from an EV/EBITDA exit multiple."""
    return last_ebitda * multiple


def enterprise_value(fcffs: Sequence[float], rate: float, g: float) -> float:
    """PV of explicit FCFFs plus the Gordon terminal value discounted n years."""
    n = len(fcffs)
    tv = gordon_terminal_value(fcffs[-1], rate, g)
    return discount(fcffs, rate) + tv / (1 + rate) ** n


def equity_bridge(
    ev: float, net_debt: float, minorities: float = 0.0, associates: float = 0.0
) -> float:
    """Equity value = EV - net debt - minorities + associates (net_debt < 0 is net cash)."""
    return ev - net_debt - minorities + associates


def sensitivity_grid(
    fcffs: Sequence[float],
    base_rate: float,
    base_g: float,
    net_debt: float,
    shares: float,
    minorities: float = 0.0,
    associates: float = 0.0,
) -> pd.DataFrame:
    """Per-share value across rate (rows) and terminal growth (columns) offsets."""
    rates = [base_rate + d for d in RATE_OFFSETS]
    gs = [base_g + d for d in G_OFFSETS]
    values = np.full((len(rates), len(gs)), np.nan)
    for i, r in enumerate(rates):
        for j, g in enumerate(gs):
            if r <= g:
                continue
            ev = enterprise_value(fcffs, r, g)
            values[i, j] = equity_bridge(ev, net_debt, minorities, associates) / shares
    return pd.DataFrame(values, index=rates, columns=gs)
