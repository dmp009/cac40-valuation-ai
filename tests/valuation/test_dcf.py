import math

import pytest
from pytest import approx

from cac40val.valuation.dcf import (
    discount,
    enterprise_value,
    equity_bridge,
    exit_multiple_terminal_value,
    fcff,
    gordon_terminal_value,
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
