"""Cost of capital: beta, cost of equity, cost of debt and WACC."""

import pandas as pd

MIN_BETA_OBSERVATIONS = 24


def regress_beta(stock_returns: pd.Series, index_returns: pd.Series) -> float:
    """OLS slope of stock returns on index returns over aligned, non-null pairs."""
    pairs = pd.concat([stock_returns, index_returns], axis=1, join="inner").dropna()
    if len(pairs) < MIN_BETA_OBSERVATIONS:
        raise ValueError(
            f"Need at least {MIN_BETA_OBSERVATIONS} return pairs, got {len(pairs)}"
        )
    stock, index = pairs.iloc[:, 0], pairs.iloc[:, 1]
    var = index.var()
    if var == 0:
        raise ValueError("Index returns have zero variance")
    return float(stock.cov(index) / var)


def blume_adjust(raw_beta: float) -> float:
    """Blume adjustment toward 1: 0.67 * raw + 0.33."""
    return 0.67 * raw_beta + 0.33


def cost_of_equity(rf: float, beta: float, erp: float) -> float:
    """CAPM cost of equity."""
    return rf + beta * erp


def cost_of_debt(interest_expense: float, avg_gross_debt: float, rf: float) -> float:
    """Pre-tax cost of debt, floored at the risk-free rate."""
    if avg_gross_debt <= 0:
        return rf
    return max(interest_expense / avg_gross_debt, rf)


def wacc(
    equity_value: float, debt_value: float, ke: float, kd_pre_tax: float, tax_rate: float
) -> float:
    """Weighted average cost of capital using market-value weights."""
    total = equity_value + debt_value
    return equity_value / total * ke + debt_value / total * kd_pre_tax * (1 - tax_rate)
