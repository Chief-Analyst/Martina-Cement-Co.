"""Analytics: backlog health, dispatch, ageing, the action list and a data explorer."""
import dash_mantine_components as dmc
from dash import Input, Output, callback, dcc, html

from ... import brand
from ...config import RULES
from ...orderbook import analytics as A
from ...orderbook.pipeline import norm_filters
from ..charts import bars, pareto, trend
from ..components import card, graph, kpi, kpi_row, table
from ..theme import pct, tonnes

TABS = [("backlog", "Backlog Health", "mdi:heart-pulse"), ("dispatch", "Dispatch", "mdi:truck-fast-outline"),
        ("ageing", "Order Ageing", "mdi:clock-outline"), ("actions", "Action List", "mdi:alert-circle-outline"),
        ("explorer", "Data Explorer", "mdi:table-search")]


def tabs(id, items, value):
    from ..components import icon
    return dmc.Tabs(id=id, value=value, className="mc-tabs", variant="pills", radius="md", children=[
        dmc.TabsList([dmc.TabsTab(label, value=v, leftSection=icon(ic, 16)) for v, label, ic in items])])


def layout():
    return html.Div(className="mc-page", children=[
        html.Div(className="mc-page-head", children=[html.Div([
            html.H1("Analytics", className="mc-page-title"),
            html.Div("Where the backlog sits, how fast it moves and which customers need a call.",
                     className="mc-page-sub")])]),
        tabs("an-tab", TABS, "backlog"),
        dcc.Loading(html.Div(id="an-body"), type="dot", color=brand.COLORS["primary"]),
    ])


def _backlog(f):
    c = A.concentration(f)
    k = A.kpis(f)
    tone = {"Concentrated": "bad", "Moderate": "watch", "Spread": "good"}.get(c["label"], "muted")
    return html.Div(className="mc-stack", children=[
        kpi_row([
            kpi("Backlog", tonnes(k["open_t"]), f"{tonnes(k['open_cement_t'])} cement", "primary"),
            kpi("Customers holding it", f"{c['customers']:,}", "With any open tonnage", "info"),
            kpi("Average per customer", tonnes(c.get("avg_per_customer", 0)), "Open tonnage", "muted"),
            kpi("Concentration", c["label"],
                f"Top 10 hold {pct(c['top10_share'])} · top 20% hold {pct(c['top20pct_share'])}", tone),
        ]),
        card("Largest 20 customers and their cumulative share", graph(pareto(c["pareto"]), 380),
             description="Bars are open tonnage; the line is the running share of all open tonnage. "
                         f"Concentration index (HHI) {c['hhi']:,.0f}: above 1,500 counts as concentrated."),
    ])


def _dispatch(f):
    fr = A.fill_by_region(f)
    tr = A.lift_trend(f, 60)
    fig = bars(fr.assign(fill=fr["fill_rate"] * 100), "region", "fill", color="region",
               text_fmt=".0f", unit="%")
    fig.update_yaxes(title="Lifted as % of ordered", ticksuffix="%")
    return html.Div(className="mc-stack", children=[
        html.Div(className="mc-split-rev", children=[
            card("Fill rate by region", graph(fig, 340),
                 description="Tonnes lifted in the period as a share of tonnes ordered in it"),
            card("Tonnes lifted per day, last 60 days", graph(trend(tr, "day", "qty_t", "region"), 340),
                 description="Stacked by region, with the 7-day average"),
        ]),
        card("By region", table("an-fill", fr, {
            "region": ("Region", "text"), "ordered_t": ("Ordered (t)", "t"),
            "lifted_t": ("Lifted (t)", "t"), "fill_rate": ("Fill rate", "pct")}, height=300,
            quick_filter=False)),
    ])


def _ageing(f):
    buckets, oldest = A.ageing(f)
    fig = bars(buckets, "age_bucket", "open_t", colors=["#9FC9D1", "#5FA5B4", "#2D8496", "#F2A541", "#E07B39", "#D1495B"])
    fig.update_xaxes(title="Days since the order was created")
    return html.Div(className="mc-stack", children=[
        card("Open tonnage by age", graph(fig, 330),
             description="Older buckets are orders customers paid for and are still waiting on"),
        card("Oldest open orders", table("an-oldest", oldest, {
            "order_id": ("Order", "text"), "level": ("Level", "text"), "customer_name": ("Customer", "text"),
            "region": ("Region", "text"), "product": ("Product", "text"), "point_name": ("Point", "text"),
            "open_t": ("Open (t)", "t"), "age_days": ("Age (days)", "t1"), "status": ("Status", "text")}),
             description="Contracts not yet released and releases not yet lifted, oldest first"),
    ])


def _actions(f):
    seg = lambda id, data, value: dmc.SegmentedControl(id=id, data=data, value=value, size="xs")  # noqa: E731
    return html.Div(className="mc-stack", children=[
        card("Order cover", dcc.Loading(html.Div(id="an-cover")),
             description=f"Days of work booked = open tonnage / daily target. Critical under "
                         f"{RULES.cover_critical_days:g} days, watch under {RULES.cover_watch_days:g}. "
                         "Project accounts are planned by contract and carry no run rate.",
             right=seg("an-cover-band", [{"label": "Needs action", "value": "action"},
                                          {"label": "Critical", "value": "CRITICAL"},
                                          {"label": "Watch", "value": "WATCH"},
                                          {"label": "All", "value": "all"}], "action")),
        card("Lifting behaviour, last 30 days", dcc.Loading(html.Div(id="an-beh")),
             description=f"Lifted as a share of ordered. Poor under {RULES.behaviour_poor:.0%}, "
                         f"fair under {RULES.behaviour_fair:.0%}.",
             right=seg("an-beh-band", [{"label": "Needs action", "value": "action"},
                                        {"label": "Poor", "value": "POOR"},
                                        {"label": "Good", "value": "GOOD"},
                                        {"label": "All", "value": "all"}], "action")),
    ])


def _explorer(f):
    return html.Div(className="mc-stack", children=[
        card("Order lines", html.Div(id="an-explorer"),
             description="Every contract and release, with customer details joined. "
                         "The sidebar period filters by creation date here.",
             right=[dmc.Select(id="an-exp-status", size="xs", w=150, value="open",
                               data=[{"label": "Open only", "value": "open"},
                                     {"label": "Partial", "value": "PARTIAL"},
                                     {"label": "Closed", "value": "CLOSED"},
                                     {"label": "Everything", "value": ""}]),
                    dcc.Input(id="an-exp-search", placeholder="Order or customer...",
                              className="grid-search", debounce=True)]),
    ])


@callback(Output("an-body", "children"), Input("an-tab", "value"), Input("filters", "data"),
          Input("data-version", "data"))
def render(tab, filters, _v):
    f = norm_filters(filters)
    return {"backlog": _backlog, "dispatch": _dispatch, "ageing": _ageing,
            "actions": _actions, "explorer": _explorer}.get(tab, _backlog)(f)


@callback(Output("an-cover", "children"), Input("an-cover-band", "value"), Input("filters", "data"),
          Input("data-version", "data"))
def cover_table(band, filters, _v):
    df = A.cover_risk(norm_filters(filters))
    if band == "action":
        df = df[df["band"].isin(["CRITICAL", "WATCH"])]
    elif band != "all":
        df = df[df["band"] == band]
    return table("an-cover-grid", df, {
        "band": ("Status", "band", 120), "customer_name": ("Customer", "text"), "channel": ("Channel", "text"),
        "region": ("Region", "text"), "open_t": ("Open (t)", "t"), "daily_target_t": ("Daily target (t)", "t"),
        "cover_days": ("Cover (days)", "dec"), "sales_rep": ("Sales rep", "text"),
        "action": ("Suggested action", "text")}, height=420)


@callback(Output("an-beh", "children"), Input("an-beh-band", "value"), Input("filters", "data"),
          Input("data-version", "data"))
def behaviour_table(band, filters, _v):
    df = A.behaviour(norm_filters(filters))
    if band == "action":
        df = df[df["band"].isin(["POOR", "FAIR"])]
    elif band != "all":
        df = df[df["band"] == band]
    return table("an-beh-grid", df, {
        "band": ("Behaviour", "band", 120), "customer_name": ("Customer", "text"),
        "ordered_t": ("Ordered (t)", "t"), "lifted_t": ("Lifted (t)", "t"),
        "ratio": ("Lifted / ordered", "pct"), "action": ("Suggested action", "text")}, height=420)


@callback(Output("an-explorer", "children"), Input("an-exp-status", "value"),
          Input("an-exp-search", "value"), Input("filters", "data"), Input("data-version", "data"))
def explorer_table(status, search, filters, _v):
    df = A.explorer(norm_filters(filters), status or "", (search or "").strip())
    note = None
    if len(df) > 5000:
        note = html.Div(f"Showing the newest 5,000 of {len(df):,} lines. Narrow the filters to see the rest.",
                        className="note", style={"marginBottom": "6px"})
        df = df.head(5000)
    return html.Div([note, table("an-exp-grid", df, {
        "order_id": ("Order", "text"), "level": ("Level", "text"), "contract_id": ("Contract", "text"),
        "customer_name": ("Customer", "text"), "channel": ("Channel", "text"), "region": ("Region", "text"),
        "state": ("State", "text"), "product": ("Product", "text"), "terms": ("Terms", "text"),
        "point_name": ("Point", "text"), "qty_t": ("Qty (t)", "t"), "done_t": ("Done (t)", "t"),
        "open_t": ("Open (t)", "t"), "price_ngn_t": ("Price/t", "ngn"), "open_value_ngn": ("Open value", "ngn"),
        "created_at": ("Created", "text"), "age_days": ("Age (d)", "t1"), "status": ("Status", "text")},
        height=560, page_size=25, export_name="martina_order_lines")])
