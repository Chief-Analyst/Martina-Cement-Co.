"""Reusable UI pieces: cards, KPI tiles, tables and empty states."""
from __future__ import annotations

import dash_ag_grid as dag
import dash_mantine_components as dmc
import pandas as pd
from dash import dcc, html
from dash_iconify import DashIconify

from ..brand import COLORS
from .theme import BAND_COLORS, GRAPH_CONFIG


def icon(name, size=18, color=None):
    return DashIconify(icon=name, width=size, color=color)


def kpi(label, value, sub=None, tone="primary", icon_name=None, id=None):
    color = {"primary": COLORS["primary"], "accent": COLORS["accent"], "good": COLORS["good"],
             "watch": COLORS["watch"], "bad": COLORS["bad"], "info": COLORS["info"],
             "muted": COLORS["muted"]}.get(tone, tone)
    return html.Div(className="kpi", style={"--kpi": color}, id=id or "", children=[
        html.Div(className="kpi-top", children=[
            html.Span(label, className="kpi-label"),
            icon(icon_name, 18, color) if icon_name else None,
        ]),
        html.Div(value, className="kpi-value"),
        html.Div(sub, className="kpi-sub") if sub else None,
    ])


def kpi_row(items, cols=4):
    return dmc.SimpleGrid(cols={"base": 1, "xs": 2, "md": cols}, spacing="md", children=items)


def card(title=None, children=None, right=None, description=None, className="", pad=True):
    head = None
    if title is not None or right is not None:
        head = html.Div(className="card-head", children=[
            html.Div([html.Div(title, className="card-title"),
                      html.Div(description, className="card-desc") if description is not None else None]),
            html.Div(right, className="card-right") if right is not None else None,
        ])
    return html.Div(className=f"mc-card {className}", children=[
        head, html.Div(children, className="card-body" if pad else "")])


def empty(message, icon_name="mdi:check-circle-outline"):
    return html.Div(className="empty", children=[
        icon(icon_name, 34, COLORS["muted"]), html.Div(message)])


def graph(fig, height=320, id=None):
    fig.update_layout(height=height)
    kw = {"id": id} if id else {}
    return dcc.Graph(figure=fig, config=GRAPH_CONFIG, className="mc-graph", **kw)


def band(value):
    c = BAND_COLORS.get(str(value), COLORS["muted"])
    return html.Span(str(value), className="band", style={"color": c, "borderColor": c})


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
_FMT = {
    "t": "d3.format(',.0f')(params.value)",
    "t1": "d3.format(',.1f')(params.value)",
    "num": "d3.format(',.0f')(params.value)",
    "dec": "d3.format(',.2f')(params.value)",
    "pct": "d3.format('.0%')(params.value)",
    "pct1": "d3.format('.1%')(params.value)",
    "ngn": "'₦' + d3.format(',.0f')(params.value)",
    "h": "params.value == null ? '' : d3.format('.1f')(params.value) + ' h'",
}


def _band_style(values):
    conds = [{"condition": f"params.value == {v!r}",
              "style": {"color": BAND_COLORS[v], "fontWeight": 700}}
             for v in values if v in BAND_COLORS]
    return {"styleConditions": conds}


def columns(spec: dict, df: pd.DataFrame | None = None):
    """spec: {col: (header, kind[, width])}. kind: text, t, num, dec, pct, ngn, h, band."""
    out = []
    for col, s in spec.items():
        header, kind = s[0], s[1]
        d = {"field": col, "headerName": header}
        if len(s) > 2 and s[2]:
            if isinstance(s[2], int):          # a fixed width in pixels
                d["width"], d["flex"] = s[2], 0
            else:                              # a float is a relative share of the free width
                d["flex"] = float(s[2])
        if kind in _FMT:
            d["valueFormatter"] = {"function": f"params.value == null || params.value !== params.value ? '' : {_FMT[kind]}"}
            d["type"] = "rightAligned"
            d["filter"] = "agNumberColumnFilter"
        elif kind == "band":
            vals = sorted(set(map(str, df[col].unique()))) if df is not None and col in df else list(BAND_COLORS)
            d["cellStyle"] = _band_style(vals)
        if kind == "text" and col in ("customer_name",):
            d["minWidth"] = 200
        out.append(d)
    return out


def table(id, df: pd.DataFrame, spec: dict, height=460, page_size=20, export_name=None,
          row_id=None, selectable=False, quick_filter=True):
    """An AG Grid table with paging, sorting, per-column filters and CSV export."""
    if df is None or df.empty:
        return empty("Nothing to show for these filters.")
    cols = [c for c in spec if c in df.columns]
    data = df[cols].copy()
    for c in data.columns:
        if str(data[c].dtype).startswith("datetime"):
            data[c] = data[c].dt.strftime("%Y-%m-%d %H:%M")
        elif str(data[c].dtype) == "category":
            data[c] = data[c].astype(str)
        elif str(data[c].dtype) == "float32":
            data[c] = data[c].astype("float64")
    opts_extra = {"rowSelection": {"mode": "singleRow", "checkboxes": False,
                                   "enableClickSelection": True}} if selectable else {}
    grid = dag.AgGrid(
        id={"type": "grid", "grid": id},
        rowData=data.to_dict("records"),
        columnDefs=columns({k: spec[k] for k in cols}, data),
        defaultColDef={"sortable": True, "resizable": True, "filter": True,
                       "minWidth": 90, "flex": 1, "wrapHeaderText": True, "autoHeaderHeight": True},
        dashGridOptions={"pagination": True, "paginationPageSize": page_size,
                         "paginationPageSizeSelector": [10, 20, 50, 100],
                         "animateRows": False, "rowHeight": 36,
                         "suppressCellFocus": True, "enableCellTextSelection": True,
                         "tooltipShowDelay": 400, **opts_extra},
        csvExportParams={"fileName": f"{export_name or id}.csv"},
        getRowId=f"params.data.{row_id}" if row_id else None,
        style={"height": height, "width": "100%"},
        className="ag-theme-quartz mc-grid",
    )
    tools = html.Div(className="grid-tools", children=[
        dcc.Input(id={"type": "grid-search", "grid": id}, placeholder="Search this table...",
                  className="grid-search", debounce=False) if quick_filter else html.Span(),
        html.Span(f"{len(data):,} rows", className="grid-count"),
        dmc.Button("Export CSV", id={"type": "grid-export", "grid": id}, size="xs",
                   variant="light", leftSection=icon("mdi:download", 14)),
    ])
    return html.Div([tools, grid])
