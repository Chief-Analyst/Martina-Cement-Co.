"""The Dash application: shell, navigation, sidebar filters and routing."""
from __future__ import annotations

from datetime import datetime

import dash
import dash_mantine_components as dmc
from dash import ALL, MATCH, Input, Output, State, callback, clientside_callback, dcc, html, no_update

from .. import brand
from ..config import ROOT, SETTINGS
from ..data.store import STORE
from .components import icon
from .theme import MANTINE_THEME

PAGES = [
    ("/", "Executive Summary", "mdi:view-dashboard-outline"),
    ("/analytics", "Analytics", "mdi:chart-box-outline"),
    ("/operations", "Operations", "mdi:clipboard-flow-outline"),
    ("/logistics", "Logistics", "mdi:truck-fast-outline"),
    ("/assistant", "AI Assistant", "mdi:robot-happy-outline"),
]
ORDER_BOOK_PAGES = {"/", "/analytics", "/operations"}


def header():
    return html.Div(className="mc-header", children=[
        html.Div(style={"display": "flex", "alignItems": "center", "gap": "10px"}, children=[
            dmc.Burger(id="burger", size="sm", className="mc-burger", opened=False),
            dcc.Link(className="mc-brand", href="/", children=[
                html.Img(src="/assets/logo.svg", alt=brand.COMPANY["name"]),
                html.Div(className="mc-brand-divider"),
                html.Div(className="mc-product", children=[
                    brand.COMPANY["product"],
                    html.Small("Order to delivery, in one view"),
                ]),
            ]),
        ]),
        html.Div(className="mc-header-right", children=[
            html.Span("Demo data", className="mc-demo-pill",
                      title="Every customer, order and truck is generated. Nothing is real."),
            html.Span(id="clock", className="mc-clock"),
        ]),
    ])


def _select(id, label, placeholder, data=None, searchable=False):
    return dmc.MultiSelect(id=id, label=label, placeholder=placeholder, data=data or [],
                           searchable=searchable, clearable=True, size="xs",
                           maxDropdownHeight=280, limit=60 if searchable else None,
                           comboboxProps={"withinPortal": True})


def navbar():
    from ..brand import CHANNELS, PRODUCT_NAMES, REGIONS
    return html.Div(className="mc-nav", children=[
        html.Div("Navigation", className="mc-nav-label"),
        *[dcc.Link(id={"type": "nav", "path": path}, href=path, className="mc-navlink",
                   children=[icon(ic, 19, brand.COLORS["primary"]), label])
          for path, label, ic in PAGES],
        html.Div(id="filters-panel", children=[
            html.Div("Filters", className="mc-nav-label"),
            html.Div(className="mc-filters", children=[
                _select("f-region", "Region", "All regions", REGIONS),
                _select("f-channel", "Channel", "All channels", CHANNELS),
                _select("f-product", "Product", "All products", PRODUCT_NAMES),
                _select("f-customer", "Customer", "All customers", searchable=True),
                dmc.DatePickerInput(id="f-dates", label="Period (ordered and lifted)",
                                    type="range", placeholder="Last 30 days", size="xs",
                                    clearable=True, valueFormat="DD MMM YYYY",
                                    popoverProps={"withinPortal": True}),
                dmc.Button("Clear filters", id="f-clear", variant="subtle", size="xs",
                           leftSection=icon("mdi:filter-remove-outline", 15)),
                dmc.Button("Download Excel report", id="f-excel", variant="light", size="xs",
                           leftSection=icon("mdi:microsoft-excel", 15)),
                dcc.Download(id="f-excel-dl"),
            ]),
        ]),
        html.Div(className="mc-status", children=[
            html.Div(id="data-status"),
            dmc.Button("Regenerate data now", id="data-refresh", size="xs", variant="light",
                       mt=8, fullWidth=True, leftSection=icon("mdi:refresh", 15)),
        ]),
    ])


def shell():
    return dmc.MantineProvider(theme=MANTINE_THEME, children=[
        dcc.Location(id="url"),
        dcc.Store(id="filters", storage_type="session", data={}),
        dcc.Store(id="data-version", data=0),
        dcc.Interval(id="tick-slow", interval=30_000),
        dcc.Interval(id="tick-clock", interval=1_000),
        dmc.AppShell(
            id="appshell",
            header={"height": 66},
            navbar={"width": 268, "breakpoint": "sm", "collapsed": {"mobile": True}},
            padding=0,
            children=[
                dmc.AppShellHeader(header()),
                dmc.AppShellNavbar(navbar()),
                dmc.AppShellMain(html.Div(id="page")),
            ],
        ),
    ])


def _page_modules():
    from .pages import analytics, assistant, executive, logistics, operations
    return {"/": executive, "/analytics": analytics, "/operations": operations,
            "/logistics": logistics, "/assistant": assistant}


def create_app():
    from .pages import analytics, assistant, executive, logistics, operations  # noqa: F401  (registers callbacks)
    app = dash.Dash(
        __name__,
        title=f"{brand.COMPANY['short']} | {brand.COMPANY['product']}",
        update_title=None,
        suppress_callback_exceptions=True,
        assets_folder=str(ROOT / "assets"),
        meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    )
    app._favicon = "favicon.svg"
    app.layout = shell
    _slow_callback_log(app)
    return app


def _slow_callback_log(app, threshold_ms=400):
    """Log any callback slower than the threshold, with the output it was building."""
    import logging
    import time

    from flask import g, request
    log = logging.getLogger("martina.perf")

    @app.server.before_request
    def _start():
        g._t0 = time.perf_counter()

    @app.server.after_request
    def _stop(resp):
        ms = (time.perf_counter() - getattr(g, "_t0", time.perf_counter())) * 1000
        resp.headers["Server-Timing"] = f"app;dur={ms:.0f}"
        if ms > threshold_ms and request.path.endswith("_dash-update-component"):
            try:
                out = (request.get_json(silent=True) or {}).get("output", "")[:120]
            except Exception:                                  # noqa: BLE001
                out = ""
            log.warning("slow callback %.0f ms: %s", ms, out)
        return resp


# ---------------------------------------------------------------------------
# Shell callbacks
# ---------------------------------------------------------------------------
@callback(Output("page", "children"), Input("url", "pathname"))
def route(path):
    mod = _page_modules().get(path or "/")
    if mod is None:
        return html.Div(className="mc-page", children=[
            html.H2("Page not found", className="mc-page-title"),
            dcc.Link("Back to the Executive Summary", href="/")])
    return mod.layout()


@callback(Output({"type": "nav", "path": ALL}, "className"),
          Output("filters-panel", "style"),
          Input("url", "pathname"),
          State({"type": "nav", "path": ALL}, "id"))
def highlight(path, ids):
    path = path or "/"
    cls = ["mc-navlink active" if i["path"] == path else "mc-navlink" for i in ids]
    return cls, ({} if path in ORDER_BOOK_PAGES else {"display": "none"})


@callback(Output("appshell", "navbar"), Input("burger", "opened"), State("appshell", "navbar"))
def burger(opened, nav):
    nav = dict(nav or {})
    nav["collapsed"] = {"mobile": not opened}
    return nav


@callback(Output("burger", "opened"), Input("url", "pathname"), prevent_initial_call=True)
def close_burger(_):
    return False


@callback(Output("f-customer", "data"), Input("data-version", "data"))
def customer_options(_v):
    c = STORE.ensure().book.customers
    return [{"value": r.customer_id, "label": r.customer_name}
            for r in c.sort_values("customer_name").itertuples()]


@callback(Output("filters", "data"),
          Input("f-region", "value"), Input("f-channel", "value"), Input("f-product", "value"),
          Input("f-customer", "value"), Input("f-dates", "value"))
def collect_filters(region, channel, product, customer, dates):
    dates = dates or [None, None]
    return {"region": region or [], "channel": channel or [], "product": product or [],
            "customer": customer or [], "start": dates[0] if len(dates) > 0 else None,
            "end": dates[1] if len(dates) > 1 else None}


@callback(Output("f-region", "value"), Output("f-channel", "value"), Output("f-product", "value"),
          Output("f-customer", "value"), Output("f-dates", "value"),
          Input("f-clear", "n_clicks"), prevent_initial_call=True)
def clear_filters(_):
    return [], [], [], [], None


@callback(Output("data-status", "children"), Output("data-version", "data"),
          Input("tick-slow", "n_intervals"), Input("data-refresh", "n_clicks"),
          State("data-version", "data"))
def data_status(_n, clicked, current):
    if dash.ctx.triggered_id == "data-refresh":
        STORE.refresh()
    STORE.ensure()
    st = STORE.status
    when = STORE.loaded_at.strftime("%H:%M") if STORE.loaded_at else "-"
    src = "Synthetic generator" if SETTINGS.data_source == "synthetic" else f"CSV in {SETTINGS.data_dir.name}/"
    body = [html.Div([html.Span(className="mc-dot", style={} if st.get("ok") else
                                {"background": brand.COLORS["bad"]}),
                      html.B("Data " + ("loaded" if st.get("ok") else "problem"))]),
            html.Div(f"{src} · refreshed {when}"),
            html.Div(f"{st.get('rows', 0):,} order lines · built in {st.get('seconds', 0)}s")]
    if not st.get("ok"):
        body.append(html.Div(st.get("message", ""), style={"color": brand.COLORS["bad"]}))
    version = STORE.version
    return body, (version if version != current else no_update)


clientside_callback(
    """function(n) {
        const d = new Date();
        const t = d.toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
        const day = d.toLocaleDateString('en-GB', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
        const h = d.getHours();
        const greet = h < 12 ? 'Good morning' : (h < 17 ? 'Good afternoon' : 'Good evening');
        const set = (id, v) => { const e = document.getElementById(id); if (e && e.textContent !== v) e.textContent = v; };
        set('hero-time', t.slice(0, 5)); set('hero-date', day); set('hero-greet', greet);
        return t.slice(0, 5) + ' · ' + d.toLocaleDateString('en-GB', {day: 'numeric', month: 'short'});
    }""",
    Output("clock", "children"), Input("tick-clock", "n_intervals"))

@callback(Output({"type": "grid", "grid": MATCH}, "dashGridOptions", allow_duplicate=True),
          Input({"type": "grid-search", "grid": MATCH}, "value"), prevent_initial_call=True)
def grid_search(value):
    p = dash.Patch()
    p["quickFilterText"] = value or ""
    return p

clientside_callback(
    """function(n) { return !!n; }""",
    Output({"type": "grid", "grid": MATCH}, "exportDataAsCsv"),
    Input({"type": "grid-export", "grid": MATCH}, "n_clicks"), prevent_initial_call=True)


@callback(Output("f-excel-dl", "data"), Input("f-excel", "n_clicks"), State("filters", "data"),
          prevent_initial_call=True)
def excel(_n, filters):
    from ..export import workbook
    name = f"martina_fulfilmentiq_report_{datetime.now():%Y%m%d_%H%M}.xlsx"
    return dcc.send_bytes(workbook(filters), name)
