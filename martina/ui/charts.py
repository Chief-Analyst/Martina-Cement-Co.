"""Chart builders shared by the pages. Each returns a Plotly figure."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ..brand import COLORS, REGION_COLORS, SERIES


def bars(df, x, y, color=None, horizontal=False, colors=None, text_fmt=",.0f", unit=" t",
         hover_name=None):
    fig = go.Figure()
    cols = colors or ([REGION_COLORS.get(v, COLORS["primary"]) for v in df[x]] if color == "region"
                      else COLORS["primary"])
    vals = df[y]
    text = [f"{v:{text_fmt}}" for v in vals]
    if horizontal:
        fig.add_bar(y=df[x], x=vals, orientation="h", marker_color=cols, text=text,
                    textposition="auto", hovertemplate="%{y}<br>%{x:,.0f}" + unit + "<extra></extra>")
        fig.update_yaxes(autorange="reversed")
    else:
        fig.add_bar(x=df[x], y=vals, marker_color=cols, text=text, textposition="outside",
                    cliponaxis=False,
                    hovertemplate="%{x}<br>%{y:,.0f}" + unit + "<extra></extra>")
    fig.update_layout(showlegend=False, uniformtext={"minsize": 9, "mode": "hide"})
    return fig


def pareto(df):
    fig = go.Figure()
    names = [n if len(n) <= 18 else n[:17] + "…" for n in df["customer_name"]]
    fig.add_bar(x=names, y=df["open_t"], marker_color=COLORS["primary"], name="Open tonnage",
                customdata=df["customer_name"],
                hovertemplate="%{customdata}<br>%{y:,.0f} t<extra></extra>")
    fig.add_scatter(x=names, y=df["cum_share"], yaxis="y2", mode="lines+markers",
                    line={"color": COLORS["accent"], "width": 2.5}, name="Cumulative share",
                    hovertemplate="%{y:.0%} of all open tonnage<extra></extra>")
    fig.update_layout(yaxis={"title": "Open tonnage (t)"},
                      yaxis2={"overlaying": "y", "side": "right", "tickformat": ".0%",
                              "range": [0, 1.05], "showgrid": False},
                      xaxis={"tickangle": -40, "tickfont": {"size": 10.5}},
                      legend={"orientation": "h", "y": 1.1, "x": 0}, margin={"t": 40, "b": 20})
    return fig


def trend(df, x, y, group):
    fig = go.Figure()
    total = df.groupby(x)[y].sum().reset_index()
    for i, (g, d) in enumerate(df.groupby(group)):
        fig.add_scatter(x=d[x], y=d[y], name=g, mode="lines", stackgroup="one",
                        line={"width": 0.6, "color": REGION_COLORS.get(g, SERIES[i % len(SERIES)])},
                        hovertemplate=f"{g}: " + "%{y:,.0f} t<extra></extra>")
    fig.add_scatter(x=total[x], y=total[y].rolling(7, min_periods=1).mean(), name="7-day average",
                    mode="lines", line={"color": COLORS["primary_dark"], "width": 2, "dash": "dot"},
                    hovertemplate="7-day average %{y:,.0f} t<extra></extra>")
    fig.update_layout(hovermode="x unified", yaxis={"title": "Tonnes lifted per day"})
    return fig


def forecast(hist: pd.Series, fc: pd.DataFrame, title_unit="t"):
    fig = go.Figure()
    fig.add_bar(x=hist.index, y=hist.values, name="Ordered", marker_color="#C9D9DE",
                hovertemplate="%{x|%a %d %b}: %{y:,.0f} t<extra></extra>")
    fig.add_scatter(x=list(fc["date"]) + list(fc["date"][::-1]),
                    y=list(fc["high"]) + list(fc["low"][::-1]), fill="toself",
                    fillcolor="rgba(242,165,65,.22)", line={"width": 0}, mode="lines",
                    name="Range (1 in 10 to 9 in 10)",
                    hoverinfo="skip")
    fig.add_scatter(x=fc["date"], y=fc["likely"], mode="lines+markers", name="Likely",
                    line={"color": COLORS["accent"], "width": 3}, marker={"size": 7},
                    customdata=fc[["low", "high"]],
                    hovertemplate="%{x|%a %d %b}: %{y:,.0f} t<br>range %{customdata[0]:,.0f} to %{customdata[1]:,.0f}<extra></extra>")
    fig.update_layout(hovermode="x unified", yaxis={"title": "Tonnes ordered per day"})
    return fig
