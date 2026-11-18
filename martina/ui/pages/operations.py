"""Operations: what to release, what is stuck, who waits, and what demand is coming."""
import dash
import dash_mantine_components as dmc
import pandas as pd
from dash import Input, Output, callback, dcc, html

from ... import brand
from ...config import RULES
from ...orderbook import operations as O
from ...orderbook.forecast import FORECASTER
from ...orderbook.pipeline import norm_filters
from ..charts import forecast as forecast_fig
from ..components import card, empty, graph, icon, kpi, kpi_row, table
from ..theme import pct, tonnes
from .analytics import tabs

TABS = [("plan", "Release Planning", "mdi:calendar-check-outline"),
        ("partial", "Partial Releases", "mdi:progress-clock"),
        ("fifo", "FIFO Watch", "mdi:swap-vertical"),
        ("book", "Order Book", "mdi:book-open-page-variant-outline"),
        ("points", "Shipping Points", "mdi:factory"),
        ("forecast", "Demand Forecast", "mdi:chart-timeline-variant")]


def layout():
    return html.Div(className="mc-page", children=[
        html.Div(className="mc-page-head", children=[html.Div([
            html.H1("Operations", className="mc-page-title"),
            html.Div("Release planning for delivered orders, stuck and out-of-turn releases, "
                     "and the demand coming next week.", className="mc-page-sub")])]),
        html.Div(id="ops-summary", style={"marginBottom": "16px"}),
        tabs("ops-tab", TABS, "plan"),
        dcc.Loading(html.Div(id="ops-body"), type="dot", color=brand.COLORS["primary"]),
    ])


@callback(Output("ops-summary", "children"), Input("filters", "data"), Input("data-version", "data"))
def summary(filters, _v):
    s = O.summary(norm_filters(filters))
    return kpi_row([
        kpi("Delivered in the queue", tonnes(s["del_queue_t"]), "Released, waiting to be lifted", "primary"),
        kpi("Delivered on contracts", tonnes(s["del_contract_t"]), "Bought, not yet released", "info"),
        kpi(f"Partials over {RULES.partial_alert_days} days", f"{s['partial_aged_n']} · {tonnes(s['partial_aged_t'])}",
            "Releases part-lifted and stalled", "watch"),
        kpi("Served out of turn", f"{s['fifo_customers']}", "Customers with an older release waiting", "bad"),
    ])


def _seg(id, data, value):
    return dmc.SegmentedControl(id=id, data=data, value=value, size="xs")


def _plan():
    return card("Release planning (Delivered orders)", dcc.Loading(html.Div(id="ops-plan")),
                description="Queue days = delivered tonnage released and waiting / daily target. "
                            "To release = what tops each customer up to the chosen horizon, "
                            "limited by what is still on contract; still short is what no contract covers.",
                right=_seg("ops-horizon", [{"label": f"{h} day{'s' if h > 1 else ''}", "value": str(h)}
                                            for h in RULES.planning_horizons], "3"))


def _partial():
    return card("Partially lifted releases", dcc.Loading(html.Div(id="ops-partial")),
                description=f"Some tonnage lifted, the rest still open. HIGH once a release is "
                            f"{RULES.partial_alert_days} days old: check it before releasing more for the customer.",
                right=_seg("ops-partial-mode", [{"label": f"Over {RULES.partial_alert_days} days", "value": "aged"},
                                                 {"label": "All partials", "value": "all"}], "aged"))


def _fifo():
    return card("FIFO watch", dcc.Loading(html.Div(id="ops-fifo")),
                description="A customer's oldest open release, when it has waited at least the chosen days. "
                            "HIGH means a newer release for the same customer has already been lifted.",
                right=[_seg("ops-fifo-days", [{"label": f"{d}+ days", "value": str(d)} for d in (1, 2, 4, 7)],
                            str(RULES.fifo_wait_days)),
                       _seg("ops-fifo-mode", [{"label": "Flagged", "value": "flag"},
                                              {"label": "All", "value": "all"}], "flag")])


def _book(f):
    df = O.order_book(f)
    return card("Contracts and releases per customer", table("ops-book-grid", df, {
        "customer_name": ("Customer", "text"), "channel": ("Channel", "text"), "region": ("Region", "text"),
        "contracts": ("Contracts", "num"), "contract_open_t": ("On contracts (t)", "t"),
        "releases": ("Releases", "num"), "release_open_t": ("Released, open (t)", "t"),
        "partials": ("Partials", "num"), "total_open_t": ("Total open (t)", "t")},
        export_name="martina_order_book"),
        description="Open tonnage still on contracts (not yet released) and on releases (in the loading queue)")


def _points():
    return card("Open tonnage by works and depot", dcc.Loading(html.Div(id="ops-points")),
                description="Where the open orders will load from, split by delivery terms",
                right=_seg("ops-points-kind", [{"label": "All", "value": "all"},
                                               {"label": "Works", "value": "Works"},
                                               {"label": "Depots", "value": "Depot"}], "all"))


def _forecast():
    r = FORECASTER.get()
    if r is None:
        return card("Demand forecast", empty("The forecast is training on 18 months of orders. "
                                             "It takes a few seconds; this view refreshes when it is ready.",
                                             "mdi:timer-sand"),
                    right=dcc.Interval(id="ops-fc-wait", interval=2500, max_intervals=20))
    regions = ["All regions"] + [r_ for r_ in brand.REGIONS if r_ in r["history"].columns]
    s = r["scores"]["All regions"]
    better = (1 - s["model_wape"] / s["rule_wape"]) if s["rule_wape"] else 0
    method_note = [f"{reg}: {'model' if sc['use_model'] else 'rule'}"
                   for reg, sc in r["scores"].items() if reg != "All regions"]
    return html.Div(className="mc-stack", children=[
        html.Div(className="exc", style={"--sev": brand.COLORS["good"] if s["use_model"] else brand.COLORS["watch"]},
                 children=[
            html.Div(className="exc-head", children=[
                html.Span([icon("mdi:brain", 17), " Learned model ",
                           "in use" if s["use_model"] else "held back: the rule is more accurate"]),
                dmc.Button("Retrain now", id="ops-fc-retrain", size="xs", variant="light")]),
            html.Div(className="exc-body", children=[
                f"Trained {r['trained_at']:%d %b %H:%M} in {r['seconds']}s on {r['history_days']} days "
                f"({r['history_start']:%d %b %Y} to {r['history_end']:%d %b %Y}). "
                f"Tested on the last 28 days it never saw: all regions miss by {pct(s['model_wape'])} of tonnes "
                f"a day, against {pct(s['rule_wape'])} for the rule (same weekday, last four weeks) "
                f"{'(' + pct(better) + ' better)' if better > 0 else ''}. ",
                "Per region, the more accurate one is used: " + ", ".join(method_note) + "."]),
        ]),
        card("Tonnes likely to be ordered, next 7 days", dcc.Loading(html.Div(id="ops-fc-chart")),
             description="Bars are the last 8 weeks of orders; the line is the forecast, the band its range",
             right=dmc.Select(id="ops-fc-region", value="All regions", size="xs", w=180,
                              data=regions, allowDeselect=False)),
        html.Div(className="mc-two", children=[
            card("Day by day", html.Div(id="ops-fc-days")),
            card("Largest customers, next 7 days", table("ops-fc-cust", r["customers"], {
                "customer_name": ("Customer", "text"), "region": ("Region", "text"),
                "last_28d_t": ("Last 28 days (t)", "t"), "next_7d_t": ("Next 7 days (t)", "t")},
                height=360, quick_filter=False),
                description="Each customer's recent daily rate, adjusted by the season the model sees"),
        ]),
    ])


@callback(Output("ops-body", "children"), Input("ops-tab", "value"), Input("filters", "data"),
          Input("data-version", "data"))
def render(tab, filters, _v):
    f = norm_filters(filters)
    if tab == "book":
        return _book(f)
    return {"plan": _plan, "partial": _partial, "fifo": _fifo, "points": _points,
            "forecast": _forecast}.get(tab, _plan)()


@callback(Output("ops-plan", "children"), Input("ops-horizon", "value"), Input("filters", "data"),
          Input("data-version", "data"))
def plan_table(h, filters, _v):
    df = O.release_planning(norm_filters(filters), int(h or 3))
    total = df[["to_release_t", "short_t"]].sum()
    head = html.Div(className="note", style={"marginBottom": "8px"}, children=[
        f"Release {tonnes(total['to_release_t'])} to cover {h} day(s); "
        f"{tonnes(total['short_t'])} has no contract behind it."])
    return html.Div([head, table("ops-plan-grid", df, {
        "status": ("Status", "band", 120), "customer_name": ("Customer", "text"), "channel": ("Channel", "text"),
        "region": ("Region", "text"), "queue_t": ("In queue (t)", "t"), "contract_t": ("On contract (t)", "t"),
        "daily_target_t": ("Daily target (t)", "t"), "queue_days": ("Queue days", "dec"),
        "to_release_t": (f"Release for {h}d (t)", "t"), "short_t": ("Still short (t)", "t"),
        "releases": ("Releases", "num"), "partials": ("Partials", "num"),
        "oldest_days": ("Oldest (days)", "num")}, export_name="martina_release_plan")])


@callback(Output("ops-partial", "children"), Input("ops-partial-mode", "value"), Input("filters", "data"),
          Input("data-version", "data"))
def partial_table(mode, filters, _v):
    df = O.partial_releases(norm_filters(filters), mode)
    return table("ops-partial-grid", df, {
        "priority": ("Priority", "band", 110), "order_id": ("Release", "text"), "contract_id": ("Contract", "text"),
        "customer_name": ("Customer", "text"), "region": ("Region", "text"), "terms": ("Terms", "text"),
        "product": ("Product", "text"), "point_name": ("Point", "text"), "age_days": ("Age (days)", "t1"),
        "qty_t": ("Released (t)", "t"), "done_t": ("Lifted (t)", "t"), "open_t": ("Open (t)", "t"),
        "lifted_pct": ("Lifted %", "num")}, export_name="martina_partials")


@callback(Output("ops-fifo", "children"), Input("ops-fifo-days", "value"), Input("ops-fifo-mode", "value"),
          Input("filters", "data"), Input("data-version", "data"))
def fifo_table(days, mode, filters, _v):
    df = O.fifo_watch(norm_filters(filters), int(days or 2), mode or "flag")
    return table("ops-fifo-grid", df, {
        "priority": ("Priority", "band", 110), "customer_name": ("Customer", "text"), "region": ("Region", "text"),
        "order_id": ("Oldest release", "text"), "product": ("Product", "text"), "point_name": ("Point", "text"),
        "age_days": ("Waiting (days)", "t1"), "open_t": ("Open (t)", "t"), "newer_n": ("Newer releases", "num"),
        "newer_lifted_t": ("Newer lifted (t)", "t"), "action": ("Suggested action", "text")},
        export_name="martina_fifo")


@callback(Output("ops-points", "children"), Input("ops-points-kind", "value"), Input("filters", "data"),
          Input("data-version", "data"))
def points_table(kind, filters, _v):
    df = O.shipping_points(norm_filters(filters), kind)
    return table("ops-points-grid", df, {
        "point_name": ("Point", "text"), "point_type": ("Type", "text"), "open_t": ("Open (t)", "t"),
        "delivered_t": ("Delivered (t)", "t"), "collect_t": ("Collect (t)", "t"),
        "customers": ("Customers", "num"), "orders": ("Orders", "num"), "share_pct": ("Share %", "t1")},
        height=420, quick_filter=False)


@callback(Output("ops-fc-chart", "children"), Output("ops-fc-days", "children"),
          Input("ops-fc-region", "value"), Input("data-version", "data"))
def fc_chart(region, _v):
    r = FORECASTER.get()
    if r is None:
        return dash.no_update, dash.no_update
    region = region or "All regions"
    hist = r["history"][region].iloc[-56:]
    fc = r["forecast"][r["forecast"]["region"] == region]
    days = fc.assign(day=fc["date"].dt.strftime("%a %d %b"))[["day", "likely", "low", "high", "method"]]
    tot = pd.DataFrame([{"day": "Next 7 days", "likely": days["likely"].sum(), "low": days["low"].sum(),
                         "high": days["high"].sum(), "method": ""}])
    return (graph(forecast_fig(hist, fc), 360),
            table("ops-fc-days-grid", pd.concat([days, tot], ignore_index=True), {
                "day": ("Day", "text"), "likely": ("Likely (t)", "t"), "low": ("Low (t)", "t"),
                "high": ("High (t)", "t"), "method": ("Method", "text")}, height=360, page_size=10,
                quick_filter=False))


@callback(Output("ops-body", "children", allow_duplicate=True), Input("ops-fc-retrain", "n_clicks"),
          prevent_initial_call=True)
def fc_retrain(clicks):
    if not clicks:
        return dash.no_update
    FORECASTER.train()
    return _forecast()


@callback(Output("ops-body", "children", allow_duplicate=True), Input("ops-fc-wait", "n_intervals"),
          prevent_initial_call=True)
def fc_wait(_n):
    if FORECASTER.get() is None:
        return dash.no_update
    return _forecast()
