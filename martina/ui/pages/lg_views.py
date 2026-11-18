"""Builders for the Logistics sub-tabs. Pure functions of the feed's state."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from ... import brand
from ...config import RULES
from ...logistics import clock as C
from ...logistics import rules as R
from ...logistics.learn import MODELS
from ...logistics.sim import bezier
from .. import maps
from ..components import band, card, empty, graph, icon, kpi, kpi_row, table
from ..theme import GRAPH_CONFIG, hours, pct, tonnes

STAGE_CLASS = {"Loading": "Loading", "In transit": "InTransit", "At site": "AtSite",
               "Returning": "Returning", "Idle": "Idle", "No GPS": "NoGPS"}
COL = brand.COLORS


def filt_state(df, states):
    if states:
        return df[df["state"].isin(states) | df["at_point"].map(
            lambda c: any(p["state"] in states for p in brand.POINTS if p["code"] == c))]
    return df


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------
def rig(r):
    """A drawn truck in CSS, coloured by stage. The trailer shows the truck's capacity
    and fills with cement as it loads; wheels turn and the road moves while it drives;
    an amber light flashes past the reroute trigger and a red beacon pulses when GPS is lost."""
    moving = r.stage in ("In transit", "Returning")
    full = {"Loading": "loading", "In transit": "full", "At site": "full"}.get(r.stage, "empty")
    cls = (f"rig st-{STAGE_CLASS[r.stage_view]} {'bulk' if r.body == 'Bulk' else 'bag'} cargo-{full}"
           + (" moving" if moving else "") + (" hazard" if r.stage == "At site" and r.tier in ("Reroute", "Escalate") else "")
           + ("" if r.gps_ok else " nogps"))
    return html.Div(className=cls, title=f"{r.capacity_t:.0f} t {r.body.lower()} truck", children=[
        html.Div(className="rig-road"),
        html.Div(className="rig-box", children=[html.Div(className="rig-load"),
                                               html.Span(f"{r.capacity_t:.0f} t", className="rig-cap")]),
        html.Div(className="rig-cab"), html.Div(className="rig-stack"),
        html.Span(className="rig-puff"), html.Span(className="rig-puff p2"),
        html.Span(className="rig-light"), html.Div(className="rig-chassis"),
        html.Span(className="rig-wheel w1"), html.Span(className="rig-wheel w2"), html.Span(className="rig-wheel w3")])


def truck_cards(df, selected):
    cards = []
    for r in df.itertuples():
        sv = r.stage_view
        line2 = ""
        if r.stage == "At site":
            line2 = f"{hours(r.cico_h)} on site · {r.tier}"
        elif r.stage == "In transit":
            line2 = f"{(r.progress or 0) * 100:.0f}% of the way" + (f" · {r.late_h:.1f}h late" if (r.late_h or 0) > 0 else "")
        elif r.stage == "Idle":
            line2 = f"Idle {hours(r.idle_h or 0)} at {r.base_name}"
        elif r.stage == "Loading":
            line2 = f"{r.sub} at {r.origin_name}"
        else:
            line2 = f"Heading back to {r.base_name}"
        cards.append(html.Div(id={"type": "lg-truck", "id": r.truck_id}, n_clicks=0,
                              className="truck" + (" sel" if r.truck_id == selected else ""), children=[
            html.Div(className="truck-head", children=[
                html.Span(r.truck_id), html.Span(sv, className=f"stage stage-{STAGE_CLASS[sv]}")]),
            rig(r),
            html.Div(className="truck-meta", children=[
                html.Div([html.B(f"{r.capacity_t:.0f} t {r.body.lower()}", className="truck-cap"), f" · {r.transporter}"]),
                html.Div(r.customer_name if r.customer_name and r.stage != "Idle" else "No load", style={"color": COL["ink"]}),
                html.Div(line2)])]))
    return cards or [empty("No trucks match these filters.")]


def milestones(feed, tr):
    t = feed.now()
    clk = feed.clock
    steps = [("Assigned", tr.t_assign), ("Gate out", tr.t_gate_out), ("Arrived", tr.t_final_arrive),
             ("Offloaded", tr.t_offloaded), ("Back at base", tr.t_back)]
    out = []
    now_set = False
    for label, when in steps:
        done = when <= t
        cls = "ms done" if done else ("ms now" if not now_set else "ms")
        if not done:
            now_set = True
        out.append(html.Div(className=cls, children=[html.Div(className="dot"), html.B(label),
                                                     clk.fmt(when) if done else "-"]))
    return html.Div(out, className="milestones")


def truck_panel(feed, tid, pane, box=None):
    """box: the measured size of the route map on the Tracking tab ({"w": px, "h": px}).
    When given, the map fills the rest of the card and zooms to fit the trip;
    without it (the drawer), the map keeps a fixed 300 px."""
    df = feed.snapshot()
    row = df[df["truck_id"] == tid]
    if row.empty:
        return empty("Pick a truck on the left to follow its delivery.", "mdi:cursor-default-click-outline")
    r = row.iloc[0]
    sim, w, clk = feed.sim, feed.world, feed.clock
    tr = sim.by_id.get(r["trip_id"]) if r["trip_id"] else sim.current_trip(tid, feed.now())
    head = html.Div(style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"}, children=[
        html.Div([html.Span(tid, style={"fontSize": "20px", "fontWeight": 750}), " ",
                  html.Span(r["stage_view"], className=f"stage stage-{STAGE_CLASS[r['stage_view']]}")]),
        html.Span(f"{r['plate']} · {r['transporter']}", className="note")])
    if tr is None:
        return html.Div([head, empty("No trip yet.")])
    c = w.customers.iloc[tr.cust]
    p = tr.pred or {}
    v = p.get("value", {})
    q = p.get("q90", {})

    def kv(items):
        return html.Dl(className="kv", children=[x for k, val in items for x in (html.Dt(k), html.Dd(val))])

    if pane == "vehicle":
        if not p:
            body = empty("Predictions start with trips dispatched after the models first trained.")
        else:
            eta = C.drive(tr.t_gate_out, v["eta"])
            off = C.advance_window(eta, v["site"] * 60, c.receive_open * 60.0, c.receive_close * 60.0)
            back = C.drive(off + 20, v["back"])
            late_back = C.drive(off + 20, v["back"] + q.get("back", 0))
            src = lambda k: "learned model" if p["use"].get(k) else "rule"  # noqa: E731
            body = kv([
                ("Truck", f"{tid} · {r['plate']} · {r['capacity_t']:.0f} t {r['body'].lower()}"),
                ("Tracking", "Reporting" if r["gps_ok"] else f"Lost {r['gps_lost_min']:.0f} min ago"),
                ("Promised arrival", clk.fmt(tr.t_promised, True)),
                ("Expected at customer", f"{clk.fmt(eta, True)} ({src('eta')}; late case {clk.fmt(C.drive(tr.t_gate_out, v['eta'] + q.get('eta', 0)))})"),
                ("Likely offloaded by", f"{clk.fmt(off, True)} ({v['site']:.1f}h on site, {src('site')})"),
                ("Back at base and free", f"{clk.fmt(back, True)} (late case {clk.fmt(late_back, True)}, {src('back')})"),
                ("Delay risk", f"{v['risk']:.0%} chance of more than {RULES.site_reroute_hours:g}h on site ({src('risk')})"),
            ])
    elif pane == "customer":
        rd = R.readiness(feed)
        x = rd[rd["customer_id"] == c.customer_id]
        x = x.iloc[0] if len(x) else None
        body = kv([
            ("Customer", f"{c.customer_name} ({c.channel})"), ("Site", f"{c.town}, {c.state} · {c.region}"),
            ("Receiving hours", f"{c.receive_open:02d}:00 to {c.receive_close:02d}:00 · {c.bays} bay(s)"),
            ("Usual time on site", f"{feed.learner.stats.mean_h(tr.cust):.1f}h over {feed.learner.stats.n[tr.cust]} visits"),
            ("Readiness now", band(x["status"]) if x is not None else "-"),
            ("Why", x["reasons"] if x is not None else "-"),
            ("Area sales rep", f"{c.sales_rep} ({c.sales_rep_email})"),
        ])
    elif pane == "decisions":
        rows = [e for e in feed.journal if e["truck"] == tid][:30]
        body = html.Div([html.Div(className="exc", style={"--sev": COL["info"] if e["severity"] == "Info" else COL["watch"]},
                                  children=[html.Div(className="exc-head", children=[e["kind"], html.Span(e["when"], className="note")]),
                                            html.Div(e["text"], className="exc-body")]) for e in rows]
                        or [empty("Nothing recorded for this truck since the live clock started.")],
                        className="scroll", style={"maxHeight": "360px"})
    else:
        o = w.point(tr.origin)
        lats, lons = [o["lat"], c.lat, r["lat"]], [o["lon"], c.lon, r["lon"]]
        if tr.reroute:
            lats.append(w.customers.iloc[tr.reroute["to"]].lat)
            lons.append(w.customers.iloc[tr.reroute["to"]].lon)
        bw, bh = (box["w"], box["h"]) if box else (620, 300)
        center, zoom = maps.fit_view(lats, lons, bw, bh)
        fig = maps.base(height=None if box else 300, zoom=zoom, center=center,
                        uirevision=f"trk-{tr.id}-{bw}x{bh}")
        la, lo = bezier((float(o["lat"]), float(o["lon"])), (float(c.lat), float(c.lon)), 40)
        maps.add_line(fig, la, lo, COL["primary"], "Route")
        if tr.reroute:
            a = w.customers.iloc[tr.reroute["to"]]
            la2, lo2 = bezier((float(c.lat), float(c.lon)), (float(a.lat), float(a.lon)), 20)
            maps.add_line(fig, la2, lo2, COL["bad"], "Rerouted leg")
        maps.add_points(fig, pd.DataFrame([{"lat": o["lat"], "lon": o["lon"], "name": o["name"]}]), "Loaded at",
                        COL["primary_dark"], 15)
        maps.add_points(fig, pd.DataFrame([{"lat": c.lat, "lon": c.lon, "name": c.customer_name}]), "Customer",
                        COL["accent"], 15)
        maps.add_points(fig, pd.DataFrame([{"lat": r["lat"], "lon": r["lon"], "name": f"{tid} now"}]), "Truck",
                        maps.STAGE_COLORS[r["stage_view"]], 17)
        late = (tr.t_final_arrive - tr.t_promised) / 60
        body = html.Div([
            kv([("Delivery", f"{tr.release_id} · {tr.qty_t:.0f} t {tr.product}"),
                ("From", f"{w.point(tr.origin)['name']} · gate out {clk.fmt(tr.t_gate_out, True)}"),
                ("To", f"{c.customer_name}, {c.town} ({tr.dist_km:.0f} km)"),
                ("Promised", clk.fmt(tr.t_promised, True) + (f" · arrived {late:+.1f}h" if tr.t_final_arrive <= feed.now() else "")),
                ("On site", f"{hours(r['cico_h'])}, counted inside the site's receiving hours"
                 if r["stage"] == "At site" else "-")]),
            dcc.Graph(id="lg-trk-map", figure=fig, config=GRAPH_CONFIG, responsive=True, className="mc-fill-graph")
            if box is not None else html.Div(graph(fig, 300), style={"marginTop": "10px"})],
            className="mc-fill-body")
    return html.Div([head, milestones(feed, tr), body], className="mc-fill-body",
                    style={"display": "flex", "flexDirection": "column", "gap": "10px"})


# ---------------------------------------------------------------------------
# Control tower
# ---------------------------------------------------------------------------
def ct_kpis(df):
    k = R.kpis(df)
    return kpi_row([
        kpi("Trucks in the loop", f"{k['in_loop']} of {k['fleet']}", "Loading, moving or on site", "primary"),
        kpi("On customer sites", f"{k['at_site']}", f"Average {hours(k['avg_site_h'])} on site", "accent"),
        kpi("Past the trigger", f"{k['past_reroute']}", f"{RULES.site_reroute_hours:g}h on site or more", "bad"),
        kpi("Tracking lost", f"{k['gps_lost']}", "No position right now", "watch"),
        kpi("In transit on time", pct(k["on_time"]), "Against the promised arrival", "good"),
    ], cols=5)


def site_ruler(df):
    s = df[df["stage"] == "At site"].sort_values("cico_h", ascending=False).head(40)
    fig = go.Figure()
    top = max(RULES.site_escalate_hours + 2, float(s["cico_h"].max() or 0) + 1)
    for lo, hi, col, name in ((0, RULES.site_watch_hours, "rgba(47,158,107,.08)", "Normal"),
                              (RULES.site_watch_hours, RULES.site_reroute_hours, "rgba(224,161,38,.12)", "Watch"),
                              (RULES.site_reroute_hours, RULES.site_escalate_hours, "rgba(209,73,91,.10)", "Reroute"),
                              (RULES.site_escalate_hours, top, "rgba(209,73,91,.2)", "Escalate")):
        fig.add_vrect(x0=lo, x1=hi, fillcolor=col, line_width=0, annotation_text=name,
                      annotation_position="top left", annotation_font_size=10.5)
    fig.add_vline(x=RULES.site_reroute_hours, line_dash="dash", line_color=COL["bad"])
    colors = [COL["bad"] if h >= RULES.site_reroute_hours else COL["watch"] if h >= RULES.site_watch_hours
              else COL["good"] for h in s["cico_h"]]
    fig.add_bar(y=s["truck_id"], x=s["cico_h"], orientation="h", marker_color=colors,
                customdata=np.stack([s["customer_name"], s["town"]], axis=-1),
                hovertemplate="%{y} at %{customdata[0]}, %{customdata[1]}<br>%{x:.1f}h on site<extra></extra>")
    fig.update_layout(showlegend=False, xaxis={"title": "Hours on site (receiving window only)", "range": [0, top]},
                      yaxis={"autorange": "reversed", "tickfont": {"size": 10}}, bargap=0.35,
                      margin={"l": 70, "t": 26})
    return graph(fig, max(260, 22 * len(s) + 80))


def exception_list(ex, limit=40):
    if ex.empty:
        return empty("No exceptions right now.")
    sev_col = {0: COL["bad"], 1: COL["bad"], 2: COL["watch"], 3: COL["info"]}
    items = []
    for r in ex.head(limit).itertuples():
        items.append(html.Div(className="exc", style={"--sev": sev_col.get(r.sev, COL["muted"]),
                                                      "opacity": 0.55 if r.actioned else 1}, children=[
            html.Div(className="exc-head", children=[html.Span(f"{r.truck_id}: {r.what}"),
                                                     html.Span(r.owner, className="exc-owner")]),
            html.Div(r.where, className="exc-body"),
            html.Div(className="exc-body", style={"color": COL["ink"]}, children=r.action),
            html.Div(style={"display": "flex", "gap": "8px", "marginTop": "6px"}, children=[
                html.Button("Open record", id={"type": "lg-open", "id": r.truck_id}, n_clicks=0, className="lg-btn"),
                html.Button("Actioned" if r.actioned else "Mark actioned", id={"type": "lg-act", "key": r.key},
                            n_clicks=0, className="lg-btn", disabled=bool(r.actioned))])]))
    return html.Div(items, className="scroll")


def outbox(items):
    if not items:
        return empty("No alerts raised yet. They appear as trucks pass a trigger.", "mdi:email-outline")
    sev = {"Critical": COL["bad"], "High": COL["watch"], "Medium": COL["info"]}
    return html.Div(className="scroll", style={"maxHeight": "420px"}, children=[
        html.Div(className="exc", style={"--sev": sev.get(a["severity"], COL["muted"])}, children=[
            html.Div(className="exc-head", children=[html.Span(a["subject"].split("] ", 1)[-1]),
                                                     html.Span(a["when"], className="note")]),
            html.Div("To: " + (", ".join(x.split(" <")[0] for x in a["to"]) or "no recipient"), className="exc-body"),
            html.Div(a["status"], className="exc-body")]) for a in items])


# ---------------------------------------------------------------------------
# Live map
FULL_VIEW = {"lat": 9.1, "lon": 8.65}     # middle of Nigeria's bounding box, so all 36 states fit
# ---------------------------------------------------------------------------
def live_map(feed, df, stages, style, show_customers, view=None):
    zoom, center = 5.25, FULL_VIEW
    if view:                                   # measured in the browser to fit the map box
        zoom, center = view["zoom"], {"lat": view["lat"], "lon": view["lon"]}
    fig = maps.base(style, height=None, zoom=zoom, center=center, uirevision="live")
    if show_customers:
        rd = R.readiness(feed)
        for st, colr in maps.READY_COLORS.items():
            d = rd[rd["status"] == st]
            fig.add_trace(go.Scattermap(lat=d["lat"], lon=d["lon"], mode="markers", name=f"Customer: {st}",
                                        marker={"size": 6, "color": colr, "opacity": 0.55},
                                        text=d["customer_name"] + "<br>" + d["reasons"],
                                        hovertemplate="%{text}<extra></extra>"))
    pts = pd.DataFrame(brand.POINTS)
    maps.add_points(fig, pts, "Works and depots", COL["primary_dark"], 15, text=pts["name"] + " (" + pts["type"] + ")")
    d = df[df["stage_view"].isin(stages)] if stages else df
    maps.add_trucks(fig, d)
    return fig


# ---------------------------------------------------------------------------
# Plants and depots
# ---------------------------------------------------------------------------
def point_cards(pts):
    cards = []
    for r in pts.itertuples():
        tone = (COL["bad"] if r.note.startswith(("Fewer", "Queue")) else
                COL["watch"] if r.note.startswith("More trucks") else COL["good"])
        # (open_t is the delivered queue at the point; due_t the part due inside the horizon)
        cards.append(html.Div(className="exc", style={"--sev": tone}, children=[
            html.Div(className="exc-head", children=[html.Span(r.name), html.Span(r.type, className="exc-owner")]),
            html.Div(className="exc-body", children=f"{r.state} · {r.bays} bays · {r.cap_tpd:,} t a day"),
            html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(4, 1fr)", "gap": "4px",
                            "margin": "8px 0", "textAlign": "center"}, children=[
                html.Div([html.Div(str(v), style={"fontWeight": 750, "fontSize": "18px"}), html.Div(l, className="note")])
                for v, l in ((r.loading + r.queued, "loading"), (r.idle, "idle"), (r.arriving, "arriving"),
                             (tonnes(r.due_t, False), "t usual pace"))]),
            html.Div(r.note, className="exc-body", style={"color": COL["ink"], "fontWeight": 600})]))
    return html.Div(cards, style={"display": "grid", "gridTemplateColumns": "repeat(auto-fill, minmax(250px, 1fr))",
                                  "gap": "10px"})


# ---------------------------------------------------------------------------
# Readiness and rerouting
# ---------------------------------------------------------------------------
def readiness_detail(feed, cid):
    rd = R.readiness(feed)
    x = rd[rd["customer_id"] == cid]
    if x.empty:
        return empty("Pick a customer in the table to see why.", "mdi:cursor-default-click-outline")
    x = x.iloc[0]
    bw = R.best_window(feed, int(x["idx"]))
    best = bw.sort_values("risk").iloc[0]
    fig = go.Figure(go.Bar(x=[f"{h:02d}:00" for h in bw["hour"]], y=bw["risk"],
                           marker_color=[COL["good"] if h == best["hour"] else COL["primary"] for h in bw["hour"]],
                           hovertemplate="Arriving %{x}: %{y:.0%} risk<extra></extra>"))
    fig.update_layout(yaxis={"tickformat": ".0%", "title": "Risk of a long stay"}, margin={"t": 10})
    checks = [l.strip() for l in x["reasons"].split(";")]
    return html.Div(className="mc-stack", children=[
        html.Div([html.Div(x["customer_name"], style={"fontWeight": 750, "fontSize": "16px"}),
                  html.Div(f"{x['town']}, {x['state']} · {x['channel']} · rep {x['sales_rep']}", className="note")]),
        html.Div([band(x["status"]), html.Span(f"  Risk if a truck is sent now: {x['risk']:.0%}",
                                               style={"fontWeight": 600})]),
        html.Ul([html.Li(cx) for cx in checks], style={"margin": 0, "paddingLeft": "18px", "fontSize": "13px"}),
        html.Div(f"Best arrival today: {int(best['hour']):02d}:00 ({best['risk']:.0%} risk). "
                 f"Receives {x['hours']}, {x['bays']} bay(s), {x['at_site']} truck(s) on site now, "
                 f"{x['heading']} on the way.", className="note"),
        graph(fig, 220),
    ])


def reroute_map(feed, opts, row):
    lat, lon = float(row["lat"]), float(row["lon"])
    fig = maps.base(height=420, zoom=8.6, center={"lat": lat, "lon": lon}, uirevision=f"rr-{row['truck_id']}")
    if len(opts):
        for st, colr in maps.READY_COLORS.items():
            d = opts[opts["status"] == st]
            if len(d):
                maps.add_points(fig, d, f"{st} customers", colr, 13,
                                text=d["customer_name"] + " · " + d["km"].round(0).astype(int).astype(str) + " km")
    maps.add_points(fig, pd.DataFrame([{"lat": lat, "lon": lon}]), f"{row['truck_id']} on site",
                    COL["bad"], 18, text=[f"{row['truck_id']} at {row['customer_name']}"])
    return fig


# ---------------------------------------------------------------------------
# Predictions and model health
# ---------------------------------------------------------------------------
def model_cards(feed):
    L = feed.learner
    rep = L.report
    if not rep:
        return empty(f"Models are waiting for enough finished trips ({L.status}).", "mdi:timer-sand")
    cards = []
    for key, spec in MODELS.items():
        m = rep["metrics"][key]
        use = L.in_charge.get(key)
        if key == "risk":
            better = 1 - m["model_err"] / m["rule_err"] if m["rule_err"] else 0
            head = f"{pct(abs(better))} {'more' if better > 0 else 'less'} accurate than the rule"
            lines = [f"Error score {m['model_err']:.3f} against {m['rule_err']:.3f} for the rule (Brier, lower is better).",
                     f"The riskiest fifth it flags held {pct(m['capture'])} of the long stays (rule {pct(m['capture_rule'])}).",
                     f"{pct(m['base_rate'])} of visits went past {RULES.site_reroute_hours:g}h."]
        else:
            unit = "h" if key == "site" else " min"
            fmt = (lambda v: f"{v:.2f}h") if key == "site" else (lambda v: f"{v:.0f} min")
            head = f"Misses by {fmt(m['model_err'])} on average"
            tol = "30 min" if key != "site" else "30 min"
            lines = [f"The rule misses by {fmt(m['rule_err'])}.",
                     f"Within {tol}: {pct(m['within'])} of trips (rule {pct(m['within_rule'])}).",
                     f"Its late case held for {pct(m['late_case_hold'])} of trips (aim 90%)."]
        cards.append(html.Div(className="mc-card", children=[html.Div(className="card-body", children=[
            html.Div(style={"display": "flex", "justifyContent": "space-between", "gap": "8px"}, children=[
                html.Span(spec["title"], style={"fontWeight": 700}),
                html.Span("Learned model in use" if use else "Rule in charge", className="mc-pill",
                          style={"background": "#E6F4EC" if use else "#FDF1DE",
                                 "color": COL["good"] if use else "#8F5916"})]),
            html.Div(head, style={"fontSize": "19px", "fontWeight": 750, "margin": "8px 0 4px"}),
            html.Ul([html.Li(x) for x in lines], style={"margin": 0, "paddingLeft": "18px", "fontSize": "12.5px",
                                                        "color": COL["muted"]})])]))
    return html.Div(cards, style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(250px, 1fr))",
                                  "gap": "12px"})


def importance_fig(feed, key):
    imp = feed.learner.report["metrics"][key]["importance"]
    imp = imp[imp["weight"] > 0].sort_values("weight")
    fig = go.Figure(go.Bar(y=imp["feature"], x=imp["weight"], orientation="h", marker_color=COL["primary"],
                           hovertemplate="%{y}<extra></extra>"))
    fig.update_layout(xaxis={"title": "How much accuracy drops without it", "showticklabels": False},
                      margin={"l": 10, "t": 10})
    return fig


def calibration_fig(feed):
    cal = feed.learner.report["metrics"]["risk"]["calibration"]
    fig = go.Figure()
    fig.add_scatter(x=[0, cal["pred"].max()], y=[0, cal["pred"].max()], mode="lines", name="Perfect",
                    line={"dash": "dot", "color": COL["muted"]})
    fig.add_scatter(x=cal["pred"], y=cal["actual"], mode="lines+markers", name="Model",
                    line={"color": COL["accent"], "width": 3},
                    hovertemplate="Said %{x:.0%}, happened %{y:.0%}<extra></extra>")
    fig.update_layout(xaxis={"title": "Predicted risk (tenths of the test trips)", "tickformat": ".0%"},
                      yaxis={"title": "Share that went long", "tickformat": ".0%"},
                      legend={"orientation": "h", "y": 1.08, "x": 0})
    return fig


def outlook(feed, df):
    d = df[df["stage"].isin(["Loading", "In transit", "At site", "Returning"]) & df["back_t"].notna()].copy()
    clk = feed.clock
    d["expected_at_customer"] = [clk.fmt(x) if s in ("Loading", "In transit") and x == x else "arrived"
                                 for s, x in zip(d["stage"], d["eta_t"])]
    d["likely_offloaded_by"] = [clk.fmt(x, True) if s != "Returning" and x == x else "done"
                                for s, x in zip(d["stage"], d["offload_t"])]
    d["back_and_free"] = [clk.fmt(x, True) for x in d["back_t"]]
    d["late_case"] = [clk.fmt(x, True) if x == x else "" for x in d["back_late_t"]]
    return d[["truck_id", "stage", "customer_name", "expected_at_customer", "likely_offloaded_by",
              "back_and_free", "late_case", "transporter"]].sort_values("truck_id")


def health_fig(daily, key, feed):
    d = daily[daily["model"] == key].copy()
    if d.empty:
        return go.Figure()
    d = d.groupby("day").apply(lambda g: pd.Series({
        "model_err": np.average(g["model_err"], weights=g["n"]), "rule_err": np.average(g["rule_err"], weights=g["n"]),
        "live": (g["source"] == "live").any()}), include_groups=False).reset_index()
    d["date"] = [feed.clock.dt(x * C.DAY) for x in d["day"]]
    fig = go.Figure()
    fig.add_scatter(x=d["date"], y=d["rule_err"], name="Rule", mode="lines+markers",
                    line={"color": COL["muted"], "dash": "dot"})
    fig.add_scatter(x=d["date"], y=d["model_err"], name="Learned model", mode="lines+markers",
                    line={"color": COL["primary"], "width": 3})
    unit = {"risk": "Error score (Brier)", "site": "Hours missed", "eta": "Minutes missed", "back": "Minutes missed"}[key]
    fig.update_layout(yaxis={"title": unit}, hovermode="x unified")
    return fig
