"""Pure plotly figure builders for the Streamlit app (no Streamlit imports)."""

import pandas as pd
import plotly.graph_objects as go

# Sober portfolio palette, shared with .streamlit/config.toml (validated with the dataviz palette checker).
BLUE = "#2558A8"  # main series (deep blue)
ORANGE = "#B7791F"  # muted gold: second series, reference lines
RED = "#C2362B"  # status: below / price
GREY = "#9AA5B4"  # "before" / neutral comparison
INK = "#0B0D10"
GRID = "#E5E7EB"
SEQ = ["#EEF2F8", "#B3C6DF", "#6B8EBF", "#2558A8", "#0B1F3A"]
_LAYOUT = {
    "margin": {"l": 10, "r": 10, "t": 50, "b": 10},
    "template": "plotly_white",
    "colorway": ["#2558A8", "#B7791F", "#1F9D55", "#7C3AED", "#C2362B", "#0E9AA7", "#E8590C", "#DB2777"],
    "font": {"family": "Inter, Arial, sans-serif", "color": INK, "size": 13},
    "title_x": 0,
    "title_xanchor": "left",
    "title_font_size": 16,
    "legend": {"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 1, "xanchor": "right"},
    "xaxis": {"gridcolor": GRID, "zeroline": False},
    "yaxis": {"gridcolor": GRID, "zeroline": False},
    "paper_bgcolor": "rgba(0,0,0,0)",
    "plot_bgcolor": "rgba(0,0,0,0)",
}


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
            marker_color=BLUE,
            marker={"cornerradius": 6},
            customdata=df[["low", "high"]].to_numpy(),
            hovertemplate="%{y}<br>%{customdata[0]:.2f} to %{customdata[1]:.2f} EUR<extra></extra>",
        )
    )
    if price is not None:
        fig.add_shape(
            type="line", x0=price, x1=price, y0=0, y1=1, xref="x", yref="paper",
            line={"color": RED, "width": 2, "dash": "dash"},
        )  # fmt: skip
        fig.add_annotation(
            x=price, y=1, yref="paper", text=f"Price {price:.2f}", showarrow=False,
            yanchor="bottom", font={"color": RED, "size": 13},
        )  # fmt: skip
    fig.update_layout(**_LAYOUT)
    fig.update_layout(
        xaxis_title="EUR per share", yaxis={"autorange": "reversed", "gridcolor": GRID}, height=320,
        showlegend=False, bargap=0.45,
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
            colorscale=[[i / 4, c] for i, c in enumerate(SEQ)],
            xgap=2,
            ygap=2,
            colorbar={"title": "EUR"},
            hovertemplate="WACC %{y}, g %{x}: %{z:.2f} EUR<extra></extra>",
        )
    )
    fig.update_layout(**_LAYOUT)
    fig.update_layout(
        xaxis_title="Terminal growth", yaxis_title="WACC", yaxis={"autorange": "reversed"}, height=360
    )
    return fig
