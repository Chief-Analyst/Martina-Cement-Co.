"""Logistics: the live control tower, in eleven sub-tabs.

Each sub-tab carries its own Interval, so only the tab on screen refreshes,
and its callbacks never fire for controls that are not there.
"""
import dash
import dash_mantine_components as dmc
import pandas as pd
from dash import ALL, Input, Output, State, callback, clientside_callback, ctx, dcc, html, no_update

from ... import brand
from ...config import RULES
from ...geo import STATE_REGION
from ...logistics import rules as R
from ...logistics.feed import FEED
from ...logistics.learn import MODELS
from .. import maps
from ..components import band, card, empty, graph, icon, kpi, kpi_row, table
from ..theme import hours, pct, tonnes
from . import lg_views as V
from .analytics import tabs

TABS = [("track", "Tracking", "mdi:map-marker-path"), ("tower", "Control Tower", "mdi:radar"),
        ("map", "Live Map", "mdi:map-outline"), ("points", "Plants & Depots", "mdi:factory"),
        ("ready", "Readiness", "mdi:check-decagram-outline"), ("reroute", "Rerouting", "mdi:directions-fork"),
        ("pre", "Pre-Dispatch Risk", "mdi:shield-alert-outline"), ("trans", "Transporters", "mdi:truck-outline"),
        ("log", "Shift Reports", "mdi:clipboard-text-clock-outline"), ("ml", "Predictions", "mdi:brain"),
        ("mh", "Model Health", "mdi:stethoscope")]
STAGES = ["Loading", "In transit", "At site", "Returning", "Idle", "No GPS"]
COL = brand.COLORS


def seg(id, data, value, **kw):
    data = [d if isinstance(d, dict) else {"label": str(d), "value": str(d)} for d in data]
    return dmc.SegmentedControl(id=id, data=data, value=value, size="xs", **kw)


def tick(name, ms=3000):
    return dcc.Interval(id=f"lg-tick-{name}", interval=ms)


def layout():
    return html.Div(className="mc-page", children=[
        html.Div(className="lg-bar", children=[
            html.Div([html.H3("Martina Control Tower"),
                      html.Small("Every truck from loading to return. A simulated fleet runs on its own clock.")]),
            html.Div(style={"display": "flex", "gap": "12px", "alignItems": "center", "flexWrap": "wrap"}, children=[
                dmc.MultiSelect(id="lg-states", placeholder="All states", data=sorted(STATE_REGION), size="xs",
                                w=230, clearable=True, searchable=True, comboboxProps={"withinPortal": True}),
                html.Span(className="lg-live", children=[html.I(), html.Span(id="lg-clock", children="Starting")]),
            ]),
        ]),
        tabs("lg-tab", TABS, "track"),
        dcc.Store(id="lg-sel"), dcc.Store(id="lg-cust"), dcc.Store(id="lg-rr"),
        dcc.Interval(id="lg-clock-tick", interval=2000),
        dcc.Interval(id="lg-wait", interval=1500), dcc.Store(id="lg-shown", data=False),
        dmc.Drawer(id="lg-drawer", title="Delivery record", position="right", size="lg", padding="md",
                   children=html.Div(id="lg-drawer-body")),
        html.Div(id="lg-body"),
    ])


def waiting():
    msg = {"warming up": "Starting the control tower: building 60 days of fleet history and training the models. "
                         "This takes about ten seconds the first time.",
           "failed": f"The control tower could not start: {FEED.error}"}.get(FEED.state, "Starting the control tower...")
    return html.Div(className="lg-wait", children=[icon("mdi:truck-fast-outline", 40, COL["primary"]),
                                                   html.Div(msg)])


@callback(Output("lg-clock", "children"), Input("lg-clock-tick", "n_intervals"))
def clock(_n):
    return "Live " + FEED.now_label() if FEED.ready() else "Starting"


@callback(Output("lg-body", "children"), Output("lg-shown", "data"), Output("lg-wait", "disabled"),
          Input("lg-tab", "value"), Input("lg-wait", "n_intervals"), State("lg-shown", "data"))
def render(tab, _wait, shown):
    if not FEED.ready():
        return (waiting() if not _wait or FEED.state == "failed" else no_update), False, False
    if ctx.triggered_id == "lg-wait" and shown:
        return no_update, no_update, True
    return _tab(tab), True, True


def _tab(tab):
    return {"track": _track, "tower": _tower, "map": _map, "points": _points, "ready": _ready,
            "reroute": _reroute, "pre": _pre, "trans": _trans, "log": _log, "ml": _ml, "mh": _mh}[tab or "track"]()


def snap(states=None):
    return V.filt_state(FEED.snapshot(), states)


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------
def _track():
    trans = [t["name"] for t in brand.TRANSPORTERS]
    return html.Div(className="mc-split-rev", children=[
        tick("track"), dcc.Store(id="lg-trk-box"),
        card("Fleet", html.Div([
            dmc.ChipGroup(id="lg-trk-trans", multiple=True, value=[], children=html.Div(className="chips", children=[
                dmc.Chip(t, value=t, size="xs", variant="outline") for t in trans])),
            html.Div(style={"display": "flex", "gap": "8px", "margin": "10px 0", "flexWrap": "wrap"}, children=[
                seg("lg-trk-stage", ["All"] + STAGES, "All"),
                dcc.Input(id="lg-trk-q", placeholder="Truck, customer or town", className="grid-search",
                          debounce=True)]),
            html.Div(id="lg-trk-count", className="note", style={"marginBottom": "6px"}),
            html.Div(id="lg-trk-list", className="truck-list")]),
            description="Tap a truck to follow it"),
        card("Selected truck", html.Div(id="lg-trk-panel", className="mc-fill-body"), className="mc-fill-card",
             right=seg("lg-trk-pane", [{"label": "Delivery", "value": "delivery"},
                                       {"label": "Vehicle and predictions", "value": "vehicle"},
                                       {"label": "Customer", "value": "customer"},
                                       {"label": "Decisions", "value": "decisions"}], "delivery")),
    ])


@callback(Output("lg-trk-list", "children"), Output("lg-trk-count", "children"),
          Input("lg-tick-track", "n_intervals"), Input("lg-trk-trans", "value"), Input("lg-trk-stage", "value"),
          Input("lg-trk-q", "value"), Input("lg-states", "value"), Input("lg-sel", "data"))
def track_list(_n, trans, stage, q, states, sel):
    df = snap(states)
    if trans:
        df = df[df["transporter"].isin(trans)]
    if stage and stage != "All":
        df = df[df["stage_view"] == stage]
    if q:
        s = q.strip().upper()
        df = df[df["truck_id"].str.upper().str.contains(s, regex=False) |
                df["customer_name"].str.upper().str.contains(s, regex=False) |
                df["town"].str.upper().str.contains(s, regex=False)]
    order = {"No GPS": 0, "At site": 1, "In transit": 2, "Loading": 3, "Returning": 4, "Idle": 5}
    df = df.assign(_o=df["stage_view"].map(order), _h=-df["cico_h"].fillna(0)).sort_values(["_o", "_h", "truck_id"])
    counts = FEED.snapshot()["stage_view"].value_counts()
    cap = 48                                  # a short list keeps the page light; search finds the rest
    if len(df) > cap and (not stage or stage == "All"):
        shown = df.groupby("stage_view", sort=False).head(cap // len(STAGES) + 2).head(cap)
    else:
        shown = df.head(cap)
    if sel and sel in set(df["truck_id"]) and sel not in set(shown["truck_id"]):
        shown = pd.concat([df[df["truck_id"] == sel], shown.head(cap - 1)])
    more = f" ({len(shown)} shown: pick a stage or search for the rest)" if len(df) > cap else ""
    label = f"{len(df)} trucks match{more} · " + " · ".join(f"{counts.get(s, 0)} {s.lower()}" for s in STAGES)
    return V.truck_cards(shown, sel), label


@callback(Output("lg-sel", "data"), Input({"type": "lg-truck", "id": ALL}, "n_clicks"), prevent_initial_call=True)
def pick_truck(clicks):
    t = ctx.triggered_id
    if not t or not any(c for c in clicks if c):
        return no_update
    hit = [x for x in ctx.triggered if x.get("value")]
    return t["id"] if hit else no_update


# Measures the route map on the Tracking tab, so the server can zoom it to fit the trip.
clientside_callback(
    """
    function (_n, _p, prev) {
        const el = document.getElementById("lg-trk-map");
        if (!el) { return window.dash_clientside.no_update; }
        const box = {w: Math.round(el.clientWidth / 10) * 10, h: Math.round(el.clientHeight / 10) * 10};
        if (box.w < 50 || box.h < 50 || (prev && prev.w === box.w && prev.h === box.h)) {
            return window.dash_clientside.no_update;
        }
        return box;
    }
    """,
    Output("lg-trk-box", "data"), Input("lg-tick-track", "n_intervals"), Input("lg-trk-panel", "children"),
    State("lg-trk-box", "data"))


@callback(Output("lg-trk-panel", "children"), Input("lg-tick-track", "n_intervals"), Input("lg-sel", "data"),
          Input("lg-trk-pane", "value"), Input("lg-trk-box", "data"))
def track_panel(_n, sel, pane, box):
    if not sel:
        df = FEED.snapshot()
        moving = df[df["stage"] == "In transit"]
        sel = (moving if len(moving) else df)["truck_id"].iloc[0]
    if pane == "delivery" and ctx.triggered_id == "lg-tick-track" and _n and _n % 3:
        return no_update                     # the route map only needs a refresh every few ticks
    return V.truck_panel(FEED, sel, pane or "delivery", box=box or {"w": 620, "h": 360})


# ---------------------------------------------------------------------------
# Control tower
# ---------------------------------------------------------------------------
def _tower():
    owners = ["All"] + list(dict.fromkeys(brand.TEAMS.values()))
    return html.Div(className="mc-stack", children=[
        tick("tower", 5000),
        html.Div(id="lg-ct-kpis"),
        html.Div(className="mc-split", children=[
            card("Time on site", html.Div(id="lg-ct-ruler"),
                 description=f"Trucks on customer sites, longest first. Watch from {RULES.site_watch_hours:g}h, "
                             f"reroute at {RULES.site_reroute_hours:g}h, escalate at {RULES.site_escalate_hours:g}h "
                             "(hours counted inside each site's receiving window)."),
            card("Exceptions to act on", html.Div(id="lg-ct-exc"),
                 description="Each has an owner and a next step",
                 right=dmc.Select(id="lg-ct-owner", data=owners, value="All", size="xs", w=170,
                                  allowDeselect=False)),
        ]),
        card("Alert outbox", html.Div(id="lg-ct-out"),
             description="Emails raised by the triggers and who they go to. Without SMTP settings they wait here "
                         "and in data/outbox.jsonl."),
    ])


@callback(Output("lg-ct-kpis", "children"), Output("lg-ct-ruler", "children"), Output("lg-ct-exc", "children"),
          Output("lg-ct-out", "children"), Input("lg-tick-tower", "n_intervals"), Input("lg-states", "value"),
          Input("lg-ct-owner", "value"))
def tower(_n, states, owner):
    from ...alerts.notify import NOTIFIER
    df = snap(states)
    ex = R.exceptions(df, FEED)
    if owner and owner != "All":
        ex = ex[ex["owner"] == owner]
    return V.ct_kpis(df), V.site_ruler(df), V.exception_list(ex), V.outbox(NOTIFIER.recent(40))


@callback(Output("lg-drawer", "opened"), Output("lg-drawer-body", "children"), Output("lg-sel", "data", allow_duplicate=True),
          Input({"type": "lg-open", "id": ALL}, "n_clicks"), prevent_initial_call=True)
def open_record(clicks):
    hit = [x for x in ctx.triggered if x.get("value")]
    if not hit:
        return no_update, no_update, no_update
    tid = ctx.triggered_id["id"]
    return True, V.truck_panel(FEED, tid, "delivery"), tid


@callback(Output("lg-ct-exc", "children", allow_duplicate=True), Input({"type": "lg-act", "key": ALL}, "n_clicks"),
          State("lg-states", "value"), State("lg-ct-owner", "value"), prevent_initial_call=True)
def actioned(clicks, states, owner):
    hit = [x for x in ctx.triggered if x.get("value")]
    if not hit:
        return no_update
    key = ctx.triggered_id["key"]
    FEED.mark_actioned(key, f"Exception {key.split(':')[0]} marked actioned in the control tower")
    ex = R.exceptions(snap(states), FEED)
    if owner and owner != "All":
        ex = ex[ex["owner"] == owner]
    return V.exception_list(ex)


# ---------------------------------------------------------------------------
# Live map
# ---------------------------------------------------------------------------
def _map():
    return html.Div(className="mc-split", children=[
        tick("map", 4000), dcc.Store(id="lg-map-view"),
        card("Live map", dcc.Graph(id="lg-map-graph", config={"displaylogo": False, "scrollZoom": True},
                                   responsive=True, className="mc-map-graph"),
             className="mc-map-card",
             description="Trucks by stage, customers by readiness, works and depots. Scroll to zoom; tap a truck.",
             right=[dmc.MultiSelect(id="lg-map-stages", data=STAGES, value=[], placeholder="All stages", size="xs",
                                    w=210, clearable=True, comboboxProps={"withinPortal": True}),
                    seg("lg-map-style", [{"label": "Light", "value": "light"}, {"label": "Outline", "value": "outline"}],
                        maps.DEFAULT_STYLE),
                    dmc.Switch(id="lg-map-cust", label="Customers", checked=True, size="xs")]),
        card("Selected truck", html.Div(id="lg-map-panel")),
    ])


# Measures the map box in the browser and works out the centre and zoom that fit all
# of Nigeria into it (Web Mercator, 512 px tiles), so the country fills the map on any
# screen. It only changes when the box changes size, and a pan or zoom by the user is
# kept, because the figure keeps the same uirevision.
clientside_callback(
    """
    function (_n, prev) {
        const el = document.getElementById("lg-map-graph");
        if (!el) { return window.dash_clientside.no_update; }
        const w = el.clientWidth, h = el.clientHeight;
        if (w < 50 || h < 50) { return window.dash_clientside.no_update; }
        const W = 2.67, E = 14.68, S = 4.27, N = 13.89, pad = 16, legend = 48;
        const y = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
        const zx = Math.log2((w - 2 * pad) * 360 / (512 * (E - W)));
        const zy = Math.log2((h - 2 * pad - legend) * 2 * Math.PI / (512 * (y(N) - y(S))));
        const zoom = Math.round(Math.min(zx, zy) * 100) / 100;
        // centre the country in the space above the legend
        const ym = (y(N) + y(S)) / 2 - (legend / 2) * 2 * Math.PI / (512 * Math.pow(2, zoom));
        const lat = Math.atan(Math.sinh(ym)) * 180 / Math.PI;
        const view = {zoom: zoom, lat: Math.round(lat * 1000) / 1000, lon: (W + E) / 2};
        if (prev && prev.zoom === view.zoom && prev.lat === view.lat) { return window.dash_clientside.no_update; }
        return view;
    }
    """,
    Output("lg-map-view", "data"), Input("lg-tick-map", "n_intervals"), State("lg-map-view", "data"))


@callback(Output("lg-map-graph", "figure"), Input("lg-tick-map", "n_intervals"), Input("lg-map-stages", "value"),
          Input("lg-map-style", "value"), Input("lg-map-cust", "checked"), Input("lg-states", "value"),
          Input("lg-map-view", "data"))
def live_map(_n, stages, style, cust, states, view):
    return V.live_map(FEED, snap(states), stages, style, cust, view)


@callback(Output("lg-map-panel", "children"), Output("lg-sel", "data", allow_duplicate=True),
          Input("lg-map-graph", "clickData"), Input("lg-tick-map", "n_intervals"), State("lg-sel", "data"),
          prevent_initial_call="initial_duplicate")
def map_pick(click, _n, sel):
    tid = sel
    if ctx.triggered_id == "lg-map-graph" and click:
        cd = click["points"][0].get("customdata")
        if isinstance(cd, str) and cd in FEED.sim.truck:
            tid = cd
    if not tid:
        return empty("Tap a truck on the map.", "mdi:cursor-default-click-outline"), no_update
    return V.truck_panel(FEED, tid, "vehicle"), (tid if tid != sel else no_update)


# ---------------------------------------------------------------------------
# Plants and depots
# ---------------------------------------------------------------------------
def _points():
    return html.Div(className="mc-stack", children=[
        tick("points", 4000),
        card("Works and depots: trucks against orders", html.Div(id="lg-pt-body"),
             description="Idle trucks wait at the point; arriving trucks are on their way back empty and due "
                         "inside the horizon. Usual pace is what the point loaded in the last 24 hours, scaled to "
                         "the horizon. Each card compares trucks on hand and the released queue with that pace.",
             right=seg("lg-pt-h", [{"label": f"Next {h}h", "value": str(h)} for h in (2, 4, 8)], "4")),
    ])


@callback(Output("lg-pt-body", "children"), Input("lg-tick-points", "n_intervals"), Input("lg-pt-h", "value"))
def points(_n, h):
    pts = R.points(FEED, float(h or 4))
    tot = pts[["loading", "queued", "idle", "arriving", "truck_t", "open_t", "held_t"]].sum()
    return html.Div(className="mc-stack", children=[
        kpi_row([kpi("Idle trucks", f"{int(tot['idle'])}", "Empty and waiting at a point", "watch"),
                 kpi("Loading or queued", f"{int(tot['loading'] + tot['queued'])}", "At the bays now", "info"),
                 kpi(f"Arriving in {h}h", f"{int(tot['arriving'])}", "Empty, on the way back", "good"),
                 kpi("Truck capacity", tonnes(tot["truck_t"]), "Idle plus arriving", "primary"),
                 kpi("Delivered orders released", tonnes(tot["open_t"]), f"{tonnes(tot['held_t'])} for customers on hold", "accent")],
                cols=5),
        V.point_cards(pts),
    ])


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------
def _ready():
    return html.Div(className="mc-split", children=[
        tick("ready", 8000),
        card("Customer readiness: should this site receive a truck now?", html.Div(id="lg-rd-table"),
             description="Checks credit hold, funds against one load, free bays, receiving hours, the area rep's "
                         "call and the learned risk of a long stay. Select a row to see why.",
             right=seg("lg-rd-status", ["All", "Ready", "Caution", "Hold"], "All")),
        card("Why this status", html.Div(id="lg-rd-detail")),
    ])


@callback(Output("lg-rd-table", "children"), Input("lg-tick-ready", "n_intervals"), Input("lg-rd-status", "value"),
          Input("lg-states", "value"))
def ready_table(_n, status, states):
    rd = R.readiness(FEED)
    if states:
        rd = rd[rd["state"].isin(states)]
    counts = rd["status"].value_counts()
    if status and status != "All":
        rd = rd[rd["status"] == status]
    head = kpi_row([kpi("Ready", f"{counts.get('Ready', 0)}", "Send trucks as planned", "good"),
                    kpi("Caution", f"{counts.get('Caution', 0)}", "Call ahead first", "watch"),
                    kpi("Hold", f"{counts.get('Hold', 0)}", "No new loads", "bad")], cols=3)
    return html.Div([head, html.Div(style={"height": "12px"}), table("lg-rd-grid", rd, {
        "status": ("Status", "band", 105), "customer_name": ("Customer", "text"), "state": ("State", "text"),
        "risk": ("Risk if sent now", "pct"), "at_site": ("On site", "num"), "bays": ("Bays", "num"),
        "hours": ("Receives", "text"), "tsm": ("Area rep", "text"), "reasons": ("Why", "text", 2.5)},
        height=520, selectable=True, export_name="martina_readiness")])


@callback(Output("lg-cust", "data"), Input({"type": "grid", "grid": "lg-rd-grid"}, "selectedRows"),
          prevent_initial_call=True)
def ready_pick(rows):
    if not rows:
        return no_update
    name = rows[0]["customer_name"]
    rd = R.readiness(FEED)
    hit = rd[rd["customer_name"] == name]
    return hit["customer_id"].iloc[0] if len(hit) else no_update


@callback(Output("lg-rd-detail", "children"), Input("lg-cust", "data"), Input("lg-tick-ready", "n_intervals"))
def ready_detail(cid, _n):
    if not cid:
        rd = R.readiness(FEED)
        caution = rd[rd["status"] == "Caution"]
        cid = (caution if len(caution) else rd)["customer_id"].iloc[0]
    return V.readiness_detail(FEED, cid)


# ---------------------------------------------------------------------------
# Rerouting
# ---------------------------------------------------------------------------
def _reroute():
    radii = [{"label": f"{r} km", "value": str(r)} for r in RULES.reroute_radii_km] + [{"label": "Whole state", "value": "state"}]
    return html.Div(className="mc-stack", children=[
        tick("reroute", 4000),
        html.Div(id="lg-rr-kpis"),
        html.Div(className="mc-split-rev", children=[
            card(f"Watch list: {RULES.site_watch_hours:g}h or more on site", html.Div(id="lg-rr-watch", className="scroll"),
                 description="Pick a truck to see ready customers near it"),
            card("Ready customers near the truck", html.Div(id="lg-rr-opts"),
                 description="Ranked ready first, then nearest. The area rep confirms before the truck moves.",
                 right=seg("lg-rr-radius", radii, str(RULES.reroute_radii_km[1]))),
        ]),
    ])


@callback(Output("lg-rr-kpis", "children"), Output("lg-rr-watch", "children"),
          Input("lg-tick-reroute", "n_intervals"), Input("lg-states", "value"), Input("lg-rr", "data"))
def reroute_watch(_n, states, sel):
    df = snap(states)
    w = R.reroute_watch(df)
    rerouted_today = sum(1 for e in FEED.journal if e["kind"] == "Rerouted" and e["t"] >= FEED.now() - 1440)
    k = kpi_row([kpi("On the watch list", f"{len(w)}", f"{RULES.site_watch_hours:g}h or more on site", "watch"),
                 kpi("Due within 1h", f"{int(((w['to_trigger_h'] > 0) & (w['to_trigger_h'] <= 1)).sum())}",
                     "About to reach the trigger", "accent"),
                 kpi("Past the trigger", f"{int((w['to_trigger_h'] == 0).sum())}", "Decision due now", "bad"),
                 kpi("Rerouted, last 24h", f"{rerouted_today}", "On the control tower clock", "good")])
    if w.empty:
        return k, empty("No truck has been on site long enough to need a plan B.")
    items = []
    for r in w.itertuples():
        col = COL["bad"] if r.to_trigger_h == 0 else COL["watch"]
        items.append(html.Div(id={"type": "lg-rrpick", "id": r.truck_id}, n_clicks=0,
                              className="truck" + (" sel" if r.truck_id == sel else ""), style={"marginBottom": "8px"},
                              children=[html.Div(className="truck-head", children=[
                                  html.Span(r.truck_id), html.Span(hours(r.cico_h), style={"color": col})]),
                                  html.Div(className="truck-meta", children=[
                                      html.Div(r.customer_name, style={"color": COL["ink"]}),
                                      html.Div(f"{r.town}, {r.state} · {r.transporter}"),
                                      html.Div("Past the trigger" if r.to_trigger_h == 0 else
                                               f"Trigger in {hours(r.to_trigger_h)}")])]))
    return k, items


@callback(Output("lg-rr", "data"), Input({"type": "lg-rrpick", "id": ALL}, "n_clicks"), prevent_initial_call=True)
def reroute_pick(clicks):
    hit = [x for x in ctx.triggered if x.get("value")]
    return ctx.triggered_id["id"] if hit else no_update


@callback(Output("lg-rr-opts", "children"), Input("lg-rr", "data"), Input("lg-rr-radius", "value"),
          Input("lg-tick-reroute", "n_intervals"), State("lg-states", "value"))
def reroute_opts(sel, radius, n, states):
    if ctx.triggered_id == "lg-tick-reroute" and n and n % 4:
        return no_update
    w = R.reroute_watch(snap(states))
    if not sel or sel not in set(w["truck_id"]):
        if w.empty:
            return empty("Nothing to reroute right now.")
        sel = w["truck_id"].iloc[0]
    opts, row = R.reroute_options(FEED, sel, radius or "30")
    if row is None:
        return empty("Pick a truck from the watch list.")
    head = html.Div(f"{sel} at {row['customer_name']} for {hours(row['cico_h'])}. "
                    f"{(opts['status'] == 'Ready').sum() if len(opts) else 0} ready customers in range.",
                    className="note", style={"marginBottom": "8px"})
    if opts.empty:
        return html.Div([head, empty("No customers in this radius. Widen it, or send the truck back to base.")])
    return html.Div([head, graph(V.reroute_map(FEED, opts, row), 380), html.Div(style={"height": "10px"}),
                     table("lg-rr-grid", opts, {
                         "status": ("Status", "band", 105), "customer_name": ("Customer", "text"),
                         "town": ("Town", "text"), "km": ("Road km", "t"), "drive_min": ("Drive (min)", "t"),
                         "risk": ("Risk", "pct"), "at_site": ("On site", "num"), "bays": ("Bays", "num"),
                         "tsm": ("Area rep", "text"), "open_released_t": ("Released (t)", "t"),
                         "reasons": ("Why", "text")}, height=360, quick_filter=False)])


# ---------------------------------------------------------------------------
# Pre-dispatch, transporters
# ---------------------------------------------------------------------------
def _pre():
    return html.Div(className="mc-stack", children=[
        tick("pre", 5000),
        card("Loading now: risk before the truck leaves", html.Div(id="lg-pre-body"),
             description="Every truck at a bay, scored for its destination at the arrival time the model expects. "
                         "A call before dispatch costs minutes; a truck stuck on site costs a day."),
    ])


@callback(Output("lg-pre-body", "children"), Input("lg-tick-pre", "n_intervals"), Input("lg-states", "value"))
def pre(_n, states):
    df = R.pre_dispatch(FEED)
    if states and len(df):
        df = df[df["state"].isin(states)]
    if df.empty:
        return empty("No truck is loading right now.")
    return table("lg-pre-grid", df, {
        "level": ("Priority", "band", 105), "truck_id": ("Truck", "text"), "release": ("Order", "text"),
        "customer_name": ("Customer", "text"), "state": ("State", "text"), "point": ("Loading at", "text"),
        "status": ("At the bay", "text"), "risk": ("Risk", "pct"), "avg_site_h": ("Usual stay", "h"),
        "eta": ("Expected arrival", "text"), "window": ("Receives", "text"), "action": ("Action", "text")},
        export_name="martina_pre_dispatch")


def _trans():
    return html.Div(className="mc-stack", children=[
        tick("trans", 6000),
        card("Transporter scorecard", html.Div(id="lg-tr-body"),
             description="On-time arrival against the promised time, share of trip time with a GPS position, "
                         "and time spent on customer sites.",
             right=seg("lg-tr-days", [{"label": "Today", "value": "1"}, {"label": "7 days", "value": "7"},
                                      {"label": "30 days", "value": "30"}], "7")),
    ])


@callback(Output("lg-tr-body", "children"), Input("lg-tick-trans", "n_intervals"), Input("lg-tr-days", "value"))
def trans(_n, days):
    import plotly.graph_objects as go
    df = R.transporters(FEED, int(days or 7))
    fig = go.Figure()
    fig.add_bar(x=df["transporter"], y=df["on_time"], name="On time", marker_color=COL["primary"],
                hovertemplate="%{x}: %{y:.0%} on time<extra></extra>")
    fig.add_bar(x=df["transporter"], y=df["tracking"], name="Tracked", marker_color=COL["accent"],
                hovertemplate="%{x}: %{y:.0%} of trip time tracked<extra></extra>")
    fig.update_layout(barmode="group", yaxis={"tickformat": ".0%", "range": [0.5, 1.02]})
    return html.Div(className="mc-stack", children=[graph(fig, 300), table("lg-tr-grid", df, {
        "transporter": ("Transporter", "text"), "fleet": ("Fleet", "num"), "active_today": ("Active today", "num"),
        "trips": ("Trips", "num"), "tonnes": ("Tonnes", "t"), "on_time": ("On time", "pct"),
        "tracking": ("Tracked", "pct1"), "avg_site_h": ("Avg on site", "h"), "past_trigger": ("Past trigger", "num"),
        "gps_lost_now": ("GPS lost now", "num"), "idle_long_now": ("Idle 4h+ now", "num")},
        height=280, quick_filter=False)])


# ---------------------------------------------------------------------------
# Shift reports
# ---------------------------------------------------------------------------
def _log():
    kinds = ["Dispatched", "Arrived", "Offloaded", "Back at base", "Watch: 5h on site", "Past reroute trigger",
             "Rerouted", "Escalated", "GPS lost", "GPS lost 30 min", "GPS restored", "Idle 4h+", "Load assigned",
             "Dispatched to hold", "Actioned", "Models retrained"]
    return html.Div(className="mc-split-rev", children=[
        tick("log", 5000),
        card("Shift reports", html.Div(id="lg-rep-list", className="scroll"),
             description=f"Written at {RULES.shift_hours[0]:02d}:00 and {RULES.shift_hours[1]:02d}:00 on the control "
                         "tower clock from the journal; by Groq when a key is set, otherwise by a template.",
             right=dmc.Button("Write report now", id="lg-rep-now", size="xs", variant="light",
                              leftSection=icon("mdi:file-document-edit-outline", 15))),
        card("Control tower journal", html.Div(id="lg-jr-body"),
             description="Every dispatch, arrival, trigger, reroute, tracking change and decision, newest first",
             right=dmc.MultiSelect(id="lg-jr-kinds", data=kinds, value=[], placeholder="All events", size="xs",
                                   w=240, clearable=True, comboboxProps={"withinPortal": True})),
    ])


def _reports():
    reps = list(FEED.reports)
    if not reps:
        return empty("The first report is written at the next shift change. Press Write report now for the shift so far.")
    out = []
    for r in reps[:12]:
        f = r["figures"]
        out.append(html.Div(className="mc-card", style={"marginBottom": "10px"}, children=[html.Div(className="card-body", children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between"}, children=[
                html.B(r["title"]), html.Span(f"Written by {r['writer']}", className="mc-pill")]),
            html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(5, 1fr)", "gap": "6px", "margin": "10px 0",
                            "textAlign": "center"}, children=[
                html.Div([html.Div(str(v), style={"fontWeight": 750, "fontSize": "17px"}), html.Div(l, className="note")])
                for v, l in ((f["dispatched"], "dispatched"), (f["offloaded"], "offloaded"),
                             (f"{f['on_time_pct']}%" if f["on_time_pct"] is not None else "-", "on time"),
                             (f["past_trigger"], "past trigger"), (f["gps_lost"], "GPS lost"))]),
            dcc.Markdown(r["text"], style={"fontSize": "13px"})])]))
    return out


@callback(Output("lg-rep-list", "children"), Output("lg-jr-body", "children"), Input("lg-tick-log", "n_intervals"),
          Input("lg-rep-now", "n_clicks"), Input("lg-jr-kinds", "value"), Input("lg-states", "value"))
def logbook(_n, now_clicks, kinds, states):
    if ctx.triggered_id == "lg-rep-now" and now_clicks:
        FEED.write_report_now()
    jr = pd.DataFrame(list(FEED.journal)[:1500])
    if len(jr):
        if kinds:
            jr = jr[jr["kind"].isin(kinds)]
        if states:
            jr = jr[jr["state"].isin(states) | (jr["state"] == "")]
    body = table("lg-jr-grid", jr, {"when": ("When", "text", 140), "kind": ("Event", "text"),
                                    "severity": ("Severity", "text", 100), "truck": ("Truck", "text", 100),
                                    "customer": ("Customer", "text"), "state": ("State", "text", 110),
                                    "text": ("What happened", "text", 3.0)}, height=620, export_name="martina_journal")
    return _reports(), body


# ---------------------------------------------------------------------------
# Predictions and model health
# ---------------------------------------------------------------------------
def _ml():
    L = FEED.learner
    rep = L.report or {}
    clk = FEED.clock
    when = clk.fmt(L.trained_sim_t, True) if L.trained_sim_t else "-"
    return html.Div(className="mc-stack", children=[
        tick("ml", 6000),
        card("What the models learned", html.Div(id="lg-ml-cards"),
             description=f"Trained on {rep.get('rows', 0):,} finished visits ({rep.get('train_rows', 0):,} to learn, "
                         f"the newest {rep.get('test_rows', 0):,} held back to test) at {when} on the control tower "
                         f"clock, in {rep.get('seconds', 0)}s. They retrain every morning at 05:30.",
             right=dmc.Button("Retrain now", id="lg-ml-retrain", size="xs", variant="light",
                              leftSection=icon("mdi:refresh", 15))),
        html.Div(className="mc-two", children=[
            card("What each model leans on", html.Div(id="lg-ml-imp"),
                 right=dmc.Select(id="lg-ml-model", data=[{"label": v["title"], "value": k} for k, v in MODELS.items()],
                                  value="risk", size="xs", w=210, allowDeselect=False)),
            card("Can the delay risk be trusted?", graph(V.calibration_fig(FEED), 300) if rep else empty("Not trained yet."),
                 description="Test trips grouped into tenths by predicted risk: the closer the line to the diagonal, "
                             "the more the percentage can be taken at face value"),
        ]),
        card("Fleet outlook: when each truck arrives, offloads and is free again", html.Div(id="lg-ml-outlook"),
             description="Predicted at dispatch by whichever is in charge for each step, the model or the rule. "
                         "The late case is a time 9 in 10 trucks beat."),
    ])


@callback(Output("lg-ml-cards", "children"), Output("lg-ml-outlook", "children"), Input("lg-tick-ml", "n_intervals"),
          Input("lg-ml-retrain", "n_clicks"))
def ml(_n, retrain):
    if ctx.triggered_id == "lg-ml-retrain" and retrain:
        FEED.retrain()
    out = V.outlook(FEED, FEED.snapshot())
    return V.model_cards(FEED), table("lg-ml-out-grid", out, {
        "truck_id": ("Truck", "text", 100), "stage": ("Stage", "text", 110), "customer_name": ("Customer", "text"),
        "expected_at_customer": ("Expected at customer", "text"), "likely_offloaded_by": ("Likely offloaded by", "text"),
        "back_and_free": ("Back at base and free", "text"), "late_case": ("Late case", "text"),
        "transporter": ("Transporter", "text")}, height=460, export_name="martina_fleet_outlook")


@callback(Output("lg-ml-imp", "children"), Input("lg-ml-model", "value"))
def ml_importance(key):
    if not FEED.learner.report:
        return empty("Not trained yet.")
    return graph(V.importance_fig(FEED, key or "risk"), 300)


def _mh():
    return html.Div(className="mc-stack", children=[
        tick("mh", 8000),
        card("Model health", html.Div(id="lg-mh-cards"),
             description="Every prediction is written down at dispatch and scored when the truck arrives, offloads "
                         "and gets back. Before live scores exist, the training test fills the history.",
             right=[seg("lg-mh-days", [{"label": f"{d} days", "value": str(d)} for d in (7, 30, 90)], "30"),
                    dmc.Select(id="lg-mh-model", data=[{"label": v["title"], "value": k} for k, v in MODELS.items()],
                               value="risk", size="xs", w=210, allowDeselect=False)]),
        card("Daily error: learned model against the rule", html.Div(id="lg-mh-chart"),
             description="Lower is better. If the model's line sits above the rule's for days, it is time to look at "
                         "what changed."),
    ])


@callback(Output("lg-mh-cards", "children"), Output("lg-mh-chart", "children"), Input("lg-tick-mh", "n_intervals"),
          Input("lg-mh-days", "value"), Input("lg-mh-model", "value"))
def mh(_n, days, key):
    daily, summary = FEED.learner.health(FEED.now(), int(days or 30))
    if not summary:
        return empty("No scored predictions yet."), html.Div()
    tone = {"Healthy": "good", "Watch": "watch", "Act now": "bad"}
    cards = []
    for k, spec in MODELS.items():
        s = summary.get(k)
        if not s:
            continue
        fmt = (lambda v: f"{v:.3f}") if k == "risk" else ((lambda v: f"{v:.2f}h") if k == "site" else (lambda v: f"{v:.0f} min"))
        cards.append(kpi(spec["title"], s["state"],
                         f"Model {fmt(s['model_err'])} against rule {fmt(s['rule_err'])} · {s['n']:,} scored "
                         f"({s['live_n']:,} live)", tone[s["state"]]))
    return kpi_row(cards, cols=4), graph(V.health_fig(daily, key or "risk", FEED), 340)
