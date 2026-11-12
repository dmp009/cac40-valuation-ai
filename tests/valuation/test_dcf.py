import math

import numpy as np
import pytest
from pytest import approx

from cac40val.valuation.dcf import (
    discount,
    enterprise_value,
    equity_bridge,
    exit_multiple_terminal_value,
    fcff,
    gordon_terminal_value,
    normalized_terminal_fcff,
    sensitivity_grid,
)


def test_reference_values():
    assert fcff(100, 0.25, 20, 30, 5) == approx(60)
    assert discount([100, 110], 0.10) == approx(181.818182)
    assert gordon_terminal_value(110, 0.10, 0.02) == approx(1402.5)
    assert exit_multiple_terminal_value(150, 12) == approx(1800)
    assert enterprise_value([100, 110], 0.10, 0.02) == approx(1340.909091)
    assert equity_bridge(1340.909091, 200, 40, 10) == approx(1110.909091)
    assert equity_bridge(1000, -300) == approx(1300)


def test_gordon_raises_when_rate_le_g():
    with pytest.raises(ValueError):
        gordon_terminal_value(110, 0.02, 0.02)


def test_sensitivity_grid_shape_center_and_nan():
    grid = sensitivity_grid([100, 110], 0.10, 0.02, 200, 100, 40, 10)
    assert grid.shape == (5, 5)
    assert grid.iloc[2, 2] == approx(1110.909091 / 100)
    grid2 = sensitivity_grid([100, 110], 0.025, 0.02, 200, 100)
    assert math.isnan(grid2.iloc[1, 2])


def test_sensitivity_grid_nan_on_float_tie_rate_equals_g():
    # 0.07 - 0.005 and 0.06 + 0.005 differ only by float rounding.
    grid = sensitivity_grid([100, 110], 0.07, 0.06, 0, 1)
    assert math.isnan(grid.iloc[1, 4])
    finite = grid.to_numpy()[~np.isnan(grid.to_numpy())]
    assert finite.max() < 1e6


def test_sensitivity_grid_nan_on_float_tie_second_case():
    grid = sensitivity_grid([100, 110], 0.035, 0.0275, 0, 1)
    assert math.isnan(grid.iloc[0, 1])  # 0.025 vs 0.025
    assert math.isnan(grid.iloc[1, 3])  # 0.030 vs 0.030
    finite = grid.to_numpy()[~np.isnan(grid.to_numpy())]
    assert finite.max() < 1e6


def test_gordon_raises_on_near_tie():
    with pytest.raises(ValueError):
        gordon_terminal_value(110, 0.065 + 1e-12, 0.065)


def test_normalized_terminal_fcff_value():
    # rev6 = 1020; NOPAT 1020*0.2*0.75 = 153; D&A - capex = 1020*(0.04-0.05) = -10.2;
    # dNWC = 0.1*(1020-1000) = 2  ->  153 - 10.2 - 2 = 140.8
    assert normalized_terminal_fcff(1000, 0.2, 0.25, 0.04, 0.05, 0.10, 0.02) == approx(140.8)


def test_normalized_terminal_fcff_equals_grown_fcff_without_nwc():
    rev5, m, t, da, capex, g = 1000.0, 0.2, 0.25, 0.04, 0.05, 0.02
    fcff5 = fcff(rev5 * m, t, rev5 * da, rev5 * capex, 0.0)
    assert normalized_terminal_fcff(rev5, m, t, da, capex, 0.0, g) == approx(fcff5 * (1 + g))


def test_enterprise_value_with_terminal_fcff_callable():
    def tf(g):
        return 140.8 if g == 0.02 else 0.0

    ev = enterprise_value([100, 110], 0.10, 0.02, terminal_fcff=tf)
    assert ev == approx(discount([100, 110], 0.10) + 140.8 / 0.08 / 1.1**2)
    # None keeps the plain Gordon-on-last-FCFF behaviour
    assert enterprise_value([100, 110], 0.10, 0.02, terminal_fcff=None) == approx(1340.909091)
    with pytest.raises(ValueError):
        enterprise_value([100, 110], 0.02, 0.02, terminal_fcff=tf)


def test_sensitivity_grid_uses_terminal_fcff_per_g():
    def tf(g):
        return normalized_terminal_fcff(1000, 0.2, 0.25, 0.04, 0.05, 0.10, g)

    grid = sensitivity_grid([100, 110], 0.10, 0.02, 200, 100, 40, 10, terminal_fcff=tf)
    for j, g in enumerate(grid.columns):
        ev = enterprise_value([100, 110], 0.10, g, terminal_fcff=tf)
        assert grid.iloc[2, j] == approx(equity_bridge(ev, 200, 40, 10) / 100)
    tie = sensitivity_grid([100, 110], 0.07, 0.06, 0, 1, terminal_fcff=tf)
    assert math.isnan(tie.iloc[1, 4])
