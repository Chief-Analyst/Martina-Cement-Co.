"""Map figures. State outlines are always drawn from the bundled GeoJSON, so
the map works offline; the Light style adds street tiles when online."""
from __future__ import annotations

import math
import os

import plotly.graph_objects as go

from ..brand import COLORS
from ..geo import NIGERIA_CENTER, states_geojson

STAGE_COLORS = {"Loading": "#7E57C2", "In transit": "#1E88E5", "At site": "#F2A541",
                "Returning": "#2F9E6B", "Idle": "#90A4AE", "No GPS": "#D1495B"}
READY_COLORS = {"Ready": COLORS["good"], "Caution": COLORS["watch"], "Hold": COLORS["bad"]}
DEFAULT_STYLE = os.environ.get("MC_MAP_STYLE", "light")      # light | outline


def base(style=None, height=560, zoom=5.3, center=None, uirevision="map"):
    style = style or DEFAULT_STYLE
    fig = go.Figure()
    layers = [{"source": states_geojson(), "type": "fill", "color": "rgba(14,94,111,0.04)", "below": "traces"},
              {"source": states_geojson(), "type": "line", "color": "rgba(11,46,59,0.35)",
               "line": {"width": 0.8}, "below": "traces"}]
    fig.update_layout(
        map={"style": "carto-positron" if style == "light" else "white-bg",
             "center": center or NIGERIA_CENTER, "zoom": zoom, "layers": layers},
        margin={"l": 0, "r": 0, "t": 0, "b": 0}, uirevision=uirevision,
        showlegend=True, legend={"orientation": "h", "y": 0.01, "x": 0.01, "bgcolor": "rgba(255,255,255,.85)"},
    )
    if height:
        fig.update_layout(height=height)
    else:
        fig.update_layout(autosize=True)        # fills its container (see .mc-map-graph)
    return fig


def add_points(fig, df, name, color, size=13, symbol="circle", text=None, custom=None):
    fig.add_trace(go.Scattermap(
        lat=df["lat"], lon=df["lon"], mode="markers", name=name,
        marker={"size": size, "color": color, "symbol": symbol, "opacity": 0.95},
        text=text if text is not None else df.get("name"), customdata=custom,
        hovertemplate="%{text}<extra></extra>"))
    return fig


def add_trucks(fig, df, size=11):
    for stage, color in STAGE_COLORS.items():
        d = df[df["stage_view"] == stage]
        if d.empty:
            continue
        text = [f"<b>{r.truck_id}</b> · {stage}<br>{r.transporter}"
                + (f"<br>To {r.customer_name}" if r.customer_name else "")
                + (f"<br>{r.cico_h:.1f}h on site" if r.cico_h == r.cico_h and stage == "At site" else "")
                for r in d.itertuples()]
        fig.add_trace(go.Scattermap(lat=d["lat"], lon=d["lon"], mode="markers", name=stage,
                                    marker={"size": size, "color": color, "opacity": 0.95},
                                    text=text, customdata=d["truck_id"],
                                    hovertemplate="%{text}<extra></extra>"))
    return fig


def add_line(fig, lats, lons, color, name, width=3, dash=None):
    fig.add_trace(go.Scattermap(lat=list(lats), lon=list(lons), mode="lines", name=name,
                                line={"width": width, "color": color}, hoverinfo="skip"))
    return fig


def fit_view(lats, lons, width, height, pad=40, legend=36, max_zoom=10.5):
    """Centre and zoom that fit every point into a width x height pixel box
    (Web Mercator, 512 px tiles), leaving room for the legend at the bottom."""
    y = [math.log(math.tan(math.pi / 4 + float(a) * math.pi / 360)) for a in lats]
    lon_span = max(max(lons) - min(lons), 0.05)
    y_span = max(max(y) - min(y), 0.0009)
    zx = math.log2(max(width - 2 * pad, 50) * 360 / (512 * lon_span))
    zy = math.log2(max(height - 2 * pad - legend, 50) * 2 * math.pi / (512 * y_span))
    zoom = min(zx, zy, max_zoom)
    ym = (max(y) + min(y)) / 2 - (legend / 2) * 2 * math.pi / (512 * 2 ** zoom)
    return {"lat": math.degrees(math.atan(math.sinh(ym))), "lon": (max(lons) + min(lons)) / 2}, round(zoom, 2)
