import numpy as np
import pandas as pd
import pytest
from pytest import approx

from cac40val.valuation.wacc import (
    blume_adjust,
    cost_of_debt,
    cost_of_equity,
    regress_beta,
    wacc,
)


def test_blume_adjust():
    assert blume_adjust(1.3) == approx(1.201)


def test_cost_of_equity():
    assert cost_of_equity(0.03, 1.1, 0.055) == approx(0.0905)


def test_cost_of_debt_and_floor():
    assert cost_of_debt(8, 200, 0.03) == approx(0.04)
    assert cost_of_debt(2, 200, 0.03) == approx(0.03)
    assert cost_of_debt(5, 0, 0.03) == approx(0.03)


def test_wacc():
    assert wacc(800, 200, 0.0905, 0.04, 0.258) == approx(0.078336)


def test_regress_beta_recovers_slope():
    rng = np.random.default_rng(0)
    idx = pd.Series(rng.normal(0, 0.02, 60))
    stock = 1.5 * idx + rng.normal(0, 0.001, 60)
    assert regress_beta(stock, idx) == approx(1.5, abs=0.05)
    with pytest.raises(ValueError):
        regress_beta(stock.iloc[:10], idx.iloc[:10])
