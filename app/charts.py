"""Pure plotly figure builders for the Streamlit app (no Streamlit imports)."""

import pandas as pd
import plotly.graph_objects as go

NAVY = "#1f3a5f"
ACCENT = "#c0392b"


def football_chart(ff: pd.DataFrame) -> go.Figure:
    """Horizontal floating bars per method with a vertical line at the current price."""
    df = ff.dropna(subset=["low", "high"])
    price = ff.attrs.get("price")
    fig = go.Figure(
        go.Bar(
            y=list(df.index),
            x=list(df["high"] - df["low"]),
            base=list(df["low"]),
            orientation="h",
            marker_color=NAVY,
            customdata=df[["low", "high"]].to_numpy(),
            hovertemplate="%{y}<br>%{customdata[0]:.2f} to %{customdata[1]:.2f} EUR<extra></extra>",
        )
    )
    if price is not None:
        fig.add_shape(
            type="line", x0=price, x1=price, y0=0, y1=1, xref="x", yref="paper",
            line={"color": ACCENT, "width": 2, "dash": "dash"},
        )  # fmt: skip
        fig.add_annotation(
            x=price, y=1, yref="paper", text=f"Price {price:.2f}", showarrow=False,
            yanchor="bottom", font={"color": ACCENT},
        )  # fmt: skip
    fig.update_layout(
        xaxis_title="EUR per share",
        yaxis={"autorange": "reversed"},
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        height=320,
        showlegend=False,
    )
    return fig


def sensitivity_heatmap(grid: pd.DataFrame) -> go.Figure:
    """Per-share value across discount rate (rows) and terminal growth (columns)."""
    fig = go.Figure(
        go.Heatmap(
            z=grid.to_numpy(),
            x=[f"{c:.1%}" for c in grid.columns],
            y=[f"{r:.1%}" for r in grid.index],
            text=grid.round(1).to_numpy(),
            texttemplate="%{text}",
            colorscale="RdYlGn",
            colorbar={"title": "EUR"},
            hovertemplate="WACC %{y}, g %{x}: %{z:.2f} EUR<extra></extra>",
        )
    )
    fig.update_layout(
        xaxis_title="Terminal growth",
        yaxis_title="WACC",
        yaxis={"autorange": "reversed"},
        margin={"l": 10, "r": 10, "t": 30, "b": 10},
        height=360,
    )
    return fig
