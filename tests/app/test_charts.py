import math

import pandas as pd
import plotly.graph_objects as go

from app.charts import football_chart, sensitivity_heatmap
from cac40val.valuation import comps, dcf


def _football(price=100.0):
    return comps.football_field((80.0, 140.0), (90.0, 130.0), (70.0, 120.0), price)


def test_football_chart_has_price_line():
    fig = football_chart(_football(100.0))
    assert isinstance(fig, go.Figure)
    lines = [s for s in fig.layout.shapes if s.type == "line"]
    assert len(lines) == 1
    assert lines[0].x0 == lines[0].x1 == 100.0


def test_football_chart_one_bar_per_method():
    fig = football_chart(_football())
    assert len(fig.data[0].y) == 3


def test_football_chart_skips_nan_ranges():
    ff = comps.football_field((80.0, 140.0), (math.nan, math.nan), (70.0, 120.0), 100.0)
    fig = football_chart(ff)
    assert len(fig.data[0].y) == 2


def test_heatmap_dims():
    grid = dcf.sensitivity_grid([100.0] * 5, 0.08, 0.02, 500.0, 10.0)
    fig = sensitivity_heatmap(grid)
    assert isinstance(fig, go.Figure)
    z = fig.data[0].z
    assert len(z) == 5 and all(len(r) == 5 for r in z)


def test_heatmap_handles_nan_cells():
    grid = pd.DataFrame([[1.0, math.nan], [2.0, 3.0]], index=[0.08, 0.09], columns=[0.02, 0.03])
    fig = sensitivity_heatmap(grid)
    assert len(fig.data[0].z) == 2
