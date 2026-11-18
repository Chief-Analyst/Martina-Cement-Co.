"""Executive Summary: the day at a glance across the order book and the fleet."""
from dash import Input, Output, callback, dcc, html

from ... import brand
from ...orderbook import analytics as A
from ...orderbook import operations as O
from ...orderbook.pipeline import norm_filters
from ..charts import bars
from ..components import card, graph, icon, kpi, kpi_row
from ..theme import naira, pct, tonnes


def layout():
    return html.Div(className="mc-page", children=[
        html.Div(className="mc-hero", children=[
            html.Div([
                html.H2(id="hero-greet", children="Welcome"),
                html.P(f"Welcome to the {brand.COMPANY['short']} {brand.COMPANY['product']} dashboard. "
                       "Orders, releases, lifts and the live fleet in one place."),
            ]),
            html.Div(className="mc-hero-clock", children=[
                html.Div(id="hero-time", className="t"), html.Div(id="hero-date", className="d")]),
        ]),
        dcc.Loading(html.Div(id="exec-body"), type="dot", color=brand.COLORS["primary"]),
    ])


def _attention(f):
    cov = A.cover_risk(f)
    beh = A.behaviour(f)
    ops = O.summary(f)
    items = [
        ("mdi:alert-octagon-outline", "Customers with critical cover",
         f"{(cov['band'] == 'CRITICAL').sum()}", "Analytics, Action List", "bad"),
        ("mdi:account-cancel-outline", "Customers lifting poorly",
         f"{(beh['band'] == 'POOR').sum()}", "Analytics, Action List", "watch"),
        ("mdi:progress-clock", "Partial releases past alert age",
         f"{ops['partial_aged_n']} · {tonnes(ops['partial_aged_t'])}", "Operations, Partial Releases", "watch"),
        ("mdi:swap-vertical", "Customers served out of turn",
         f"{ops['fifo_customers']}", "Operations, FIFO Watch", "info"),
    ]
    try:
        from ...logistics.feed import FEED
        s = FEED.headline()
        if s:
            items += [
                ("mdi:truck-alert-outline", "Trucks past the reroute trigger",
                 f"{s['past_reroute']}", "Logistics, Rerouting", "bad"),
                ("mdi:crosshairs-off", "Trucks with GPS lost", f"{s['gps_lost']}",
                 "Logistics, Control Tower", "watch"),
            ]
    except Exception:                                  # noqa: BLE001
        pass
    tone = {"bad": brand.COLORS["bad"], "watch": brand.COLORS["watch"], "info": brand.COLORS["info"]}
    return html.Div(className="mc-three", children=[
        html.Div(className="exc", style={"--sev": tone[t]}, children=[
            html.Div(className="exc-head", children=[
                html.Span([icon(ic, 17, tone[t]), " ", label]), html.Span(v)]),
            html.Div(f"Open {where}", className="exc-body")])
        for ic, label, v, where, t in items])


def _shift_teaser():
    try:
        from ...logistics.feed import FEED
        rep = FEED.latest_report()
    except Exception:                                  # noqa: BLE001
        rep = None
    if not rep:
        return html.Div("The control tower writes a shift report at 07:00 and 19:00 on its own clock. "
                        "Open Logistics to start it; the latest report will show here.", className="note")
    return html.Div([
        html.Div(rep["title"], style={"fontWeight": 700, "marginBottom": "6px"}),
        dcc.Markdown(rep["text"], className="note", style={"color": brand.COLORS["ink"]}),
    ])


@callback(Output("exec-body", "children"), Input("filters", "data"), Input("data-version", "data"))
def render(filters, _v):
    f = norm_filters(filters)
    k = A.kpis(f)
    start, end = k["period_start"], k["period_end"]
    period = f"{start:%d %b} to {end:%d %b}"
    reg = A.backlog_by(f, "region")
    prod = A.backlog_by(f, "product")
    return html.Div(className="mc-stack", children=[
        kpi_row([
            kpi("Ordered", tonnes(k["ordered_t"]), f"New contracts, {period}", "primary", "mdi:file-document-outline"),
            kpi("Lifted", tonnes(k["lifted_t"]), f"Loaded out, {period}", "good", "mdi:truck-check-outline"),
            kpi("Fill rate", pct(k["fill_rate"]), "Lifted as a share of ordered", "info", "mdi:percent-outline"),
            kpi("Backlog", tonnes(k["open_t"]),
                f"{tonnes(k['open_contract_t'])} on contracts · {tonnes(k['open_release_t'])} released",
                "accent", "mdi:package-variant-closed"),
        ], cols=4),
        kpi_row([
            kpi("Open value", naira(k["open_value_ngn"]), "Open tonnage at contract price", "primary", "mdi:cash-multiple"),
            kpi("Mortar backlog", tonnes(k["open_mortar_t"]), "TileBond and Render lines", "muted", "mdi:texture-box"),
            kpi("Customers with open orders", f"{k['customers_open']:,}", f"{k['products_open']} products open",
                "info", "mdi:account-group-outline"),
        ], cols=3),
        html.Div(className="mc-two", children=[
            card("Backlog by region", graph(bars(reg, "region", "open_t", color="region"), 320),
                 description="Open tonnage on contracts and releases"),
            card("Backlog by product", graph(bars(prod, "product", "open_t", horizontal=True), 320),
                 description="Open tonnage per product line"),
        ]),
        card("Where attention is needed", _attention(f),
             description="Counts update with the filters; each points to the page that explains it"),
        card("Logistics: latest shift report", _shift_teaser(),
             right=html.Span("Simulated fleet", className="mc-pill")),
    ])
