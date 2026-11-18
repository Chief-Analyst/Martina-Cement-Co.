"""Control tower views: exceptions, readiness, rerouting options, risk before
dispatch, transporter scorecards and the state of each works and depot.

All of them read the feed's snapshot and the simulation, never the clock
directly, so a page shows one consistent moment.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from .. import brand
from ..config import RULES
from ..data.store import STORE
from . import clock as C
from .learn import FEATURES

TEAM = brand.TEAMS


def kpis(df):
    loop = df[df["stage"] != "Idle"]
    site = df[df["stage"] == "At site"]
    transit = df[df["stage"] == "In transit"]
    on_time = 1 - (transit["late_h"].fillna(0) > 0).mean() if len(transit) else 1.0
    return {"in_loop": len(loop), "at_site": len(site), "avg_site_h": float(site["cico_h"].mean() or 0),
            "past_reroute": int((site["cico_h"] >= RULES.site_reroute_hours).sum()),
            "gps_lost": int((~df["gps_ok"]).sum()), "on_time": float(on_time),
            "idle_long": int((df["idle_h"] >= RULES.idle_alert_hours).sum()), "fleet": len(df)}


def exceptions(df, feed):
    """Everything someone should act on, most urgent first, each with an owner."""
    out = []
    for r in df.itertuples():
        key = None
        if r.stage == "At site" and r.cico_h >= RULES.site_watch_hours:
            h = r.cico_h
            if h >= RULES.site_escalate_hours:
                sev, kind, owner = 0, f"{h:.1f}h on site: escalate", TEAM["sales"]
                act = "Escalate to area sales; reroute or recover the load"
            elif h >= RULES.site_reroute_hours:
                sev, kind, owner = 1, f"{h:.1f}h on site: past the {RULES.site_reroute_hours:g}h trigger", TEAM["dispatch"]
                act = "Reroute to a ready customer nearby (Rerouting tab)"
            else:
                sev, kind, owner = 3, f"{h:.1f}h on site: line up alternatives", TEAM["dispatch"]
                act = f"Reaches {RULES.site_reroute_hours:g}h soon: ask the area rep to confirm nearby sites"
            key = f"{r.trip_id}:site"
            out.append((sev, -h, key, r.truck_id, kind, f"{r.customer_name} · {r.town}, {r.state}", owner, act))
        if not r.gps_ok and (r.gps_lost_min or 0) >= RULES.gps_lost_minutes:
            key = f"{r.trip_id}:gps"
            out.append((1, -(r.gps_lost_min or 0), key, r.truck_id, f"Tracking lost {r.gps_lost_min:.0f} min",
                        f"{r.transporter} · last seen {r.stage.lower()}", TEAM["fleet"],
                        "Call the transporter: no tracking, no next load"))
        if r.stage == "Idle" and (r.idle_h or 0) >= RULES.idle_alert_hours:
            key = f"{r.truck_id}:idle:{int(feed.now() // 240)}"
            out.append((3, -(r.idle_h or 0), key, r.truck_id, f"Idle {r.idle_h:.1f}h", f"At {r.base_name}",
                        TEAM["dispatch"], "Assign a released order at this base or release the truck"))
        if r.stage == "In transit" and (r.late_h or 0) > 0.5:
            key = f"{r.trip_id}:late"
            out.append((2, -(r.late_h or 0), key, r.truck_id, f"{r.late_h:.1f}h past the promised time",
                        f"To {r.customer_name}", TEAM["customer"], "Give the customer the new arrival time"))
        if r.stage in ("Loading", "In transit") and getattr(r, "on_hold", False):
            key = f"{r.trip_id}:hold"
            out.append((1, 0, key, r.truck_id, "Heading to a customer on credit hold", r.customer_name,
                        TEAM["credit"], "Confirm payment or hold the load at the gate"))
    cols = ["sev", "order", "key", "truck_id", "what", "where", "owner", "action"]
    ex = pd.DataFrame(out, columns=cols).sort_values(["sev", "order"]) if out else pd.DataFrame(columns=cols)
    ex["actioned"] = ex["key"].isin(feed.actioned.keys()) if len(ex) else []
    return ex.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------
def _risk_batch(feed, cis, t, arrive_hour=None):
    """Delay risk for a truck sent now (or arriving at a given hour) to each customer."""
    L = feed.learner
    w = feed.world
    if not L.models:
        return np.array([L.stats.long_rate(ci) for ci in cis])
    from .sim import Trip
    feats = []
    for ci in cis:
        c = w.customers.iloc[ci]
        origin = c.serving_point if c.serving_point in w.point_index else w.points["code"].iloc[0]
        km = float(w.dist_cp[ci, w.point_index[origin]]) * RULES.road_factor
        plan = km / RULES.truck_speed_kmh * 60
        gate = t if arrive_hour is None else C.day_start(t) + arrive_hour * 60 - plan
        tr = Trip(id="probe", truck_id="", transporter="Kestrel Haulage", origin=origin, cust=ci,
                  release_id="", product="", qty_t=30, t_assign=gate, t_load_start=gate, t_gate_out=gate,
                  t_promised=gate, t_arrive=gate, t_offloaded=gate, t_depart=gate, t_back=gate,
                  base=origin, dist_km=km, return_km=km, plan_travel_min=plan, travel_min=0, return_min=0,
                  site_hours=0, queue_on_arrival=0, queue_at_load=0)
        f = L.features(tr, L.stats, feed.site_counts.get(ci, 0), feed.heading_counts.get(ci, 0))
        feats.append([f[k] for k in FEATURES])
    X = np.array(feats, float)
    with L.lock:
        model = L.models["risk"].predict_proba(X)[:, 1]
        use = L.in_charge.get("risk")
    return model if use else np.array([L.stats.long_rate(ci) for ci in cis])


def tsm_check(customer_id, day):
    """The area rep's call for today, simulated: the same answer all day."""
    h = zlib.crc32(f"{customer_id}:{day}".encode()) % 100
    return "Declined" if h < 6 else ("Confirmed" if h < 55 else "Not called")


def readiness(feed):
    def build():
        w = feed.world
        t = feed.now()
        c = w.customers
        mod = C.minute_of_day(t) / 60
        risk = _risk_batch(feed, range(len(c)), t)
        b = STORE.ensure().book
        open_rel = b.open[b.open["level"] == "release"].groupby("customer_id", observed=True)["open_t"].sum()
        price = 175000.0
        rows = []
        day = int(t // C.DAY)
        for i, r in enumerate(c.itertuples()):
            reasons, status = [], "Ready"
            at = feed.site_counts.get(i, 0)
            if r.on_hold:
                status = "Hold"
                reasons.append(f"Credit hold: {r.hold_reason.lower()}")
            if r.balance_ngn < 30 * price:
                reasons.append("Funds below one load")
                status = "Caution" if status == "Ready" else status
            if at >= r.bays:
                reasons.append(f"All {r.bays} bay(s) taken")
                status = "Caution" if status == "Ready" else status
            if not (r.receive_open <= mod < r.receive_close):
                reasons.append(f"Closed now (receives {r.receive_open:02d}:00 to {r.receive_close:02d}:00)")
            tsm = tsm_check(r.customer_id, day)
            if tsm == "Declined":
                reasons.append("Area rep says the site is not ready today")
                status = "Hold" if status == "Hold" else "Caution"
            if risk[i] >= 0.35:
                reasons.append(f"High chance of a long stay ({risk[i]:.0%})")
                status = "Caution" if status == "Ready" else status
            rows.append({"customer_id": r.customer_id, "customer_name": r.customer_name, "region": r.region,
                         "state": r.state, "town": r.town, "channel": r.channel, "status": status,
                         "risk": float(risk[i]), "at_site": at, "heading": feed.heading_counts.get(i, 0),
                         "bays": int(r.bays), "hours": f"{r.receive_open:02d}:00 to {r.receive_close:02d}:00",
                         "tsm": tsm, "sales_rep": r.sales_rep, "open_released_t": float(open_rel.get(r.customer_id, 0.0)),
                         "balance_ngn": float(r.balance_ngn), "reasons": "; ".join(reasons) or "All checks clear",
                         "lat": r.lat, "lon": r.lon, "idx": i})
        df = pd.DataFrame(rows)
        order = {"Hold": 0, "Caution": 1, "Ready": 2}
        return df.sort_values(["status", "risk"], key=lambda s: s.map(order) if s.name == "status" else -s).reset_index(drop=True)
    return feed.readiness_cached(build)


def best_window(feed, ci):
    """Risk of a long stay by arrival hour, for one customer, today."""
    c = feed.world.customers.iloc[ci]
    hours = list(range(int(c.receive_open), int(c.receive_close)))
    vals = [float(_risk_batch(feed, [ci], feed.now(), h)[0]) for h in hours]
    return pd.DataFrame({"hour": hours, "risk": vals})


# ---------------------------------------------------------------------------
# Rerouting
# ---------------------------------------------------------------------------
def reroute_watch(df):
    s = df[(df["stage"] == "At site") & (df["cico_h"] >= RULES.site_watch_hours)].copy()
    s["to_trigger_h"] = (RULES.site_reroute_hours - s["cico_h"]).clip(lower=0)
    return s.sort_values("cico_h", ascending=False)


def reroute_options(feed, truck_id, radius):
    df = feed.snapshot()
    row = df[df["truck_id"] == truck_id]
    if row.empty:
        return pd.DataFrame(), None
    row = row.iloc[0]
    w = feed.world
    site = row.get("site_cust") or row.get("customer_id")
    if site not in w.cust_index:
        return pd.DataFrame(), row
    ci = w.cust_index[site]
    d = w.dist_cc[ci]
    ready = readiness(feed).set_index("idx")
    if radius == "state":
        m = (w.customers["state"] == w.customers.iloc[ci].state).to_numpy()
    else:
        m = d <= float(radius)
    m[ci] = False
    idx = np.where(m)[0]
    if len(idx) == 0:
        return pd.DataFrame(), row
    out = ready.loc[idx, ["customer_name", "town", "status", "risk", "at_site", "bays", "tsm",
                          "open_released_t", "reasons"]].copy()
    out["km"] = d[idx] * RULES.road_factor
    out["drive_min"] = out["km"] / RULES.truck_speed_kmh * 60
    rank = {"Ready": 0, "Caution": 1, "Hold": 2}
    out["_r"] = out["status"].map(rank)
    out = out.sort_values(["_r", "km"]).drop(columns="_r").head(12)
    out["lat"] = w.customers.iloc[out.index]["lat"].to_numpy()
    out["lon"] = w.customers.iloc[out.index]["lon"].to_numpy()
    return out.reset_index(drop=True), row


# ---------------------------------------------------------------------------
# Before dispatch, transporters, points
# ---------------------------------------------------------------------------
def pre_dispatch(feed):
    df = feed.snapshot()
    load = df[df["stage"] == "Loading"].copy()
    if load.empty:
        return load
    w = feed.world
    rows = []
    for r in load.itertuples():
        tr = feed.sim.by_id.get(r.trip_id)
        if tr is None:
            continue
        c = w.customers.iloc[tr.cust]
        risk = tr.pred["value"]["risk"] if tr.pred else np.nan
        eta = C.drive(tr.t_gate_out, tr.pred["value"]["eta"]) if tr.pred else tr.t_promised
        h = C.minute_of_day(eta) / 60
        opens = c.receive_open <= h < c.receive_close
        if c.on_hold:
            act, level = "Hold the load: customer on credit hold", "HIGH"
        elif risk >= 0.35:
            act, level = "Call the site before the truck leaves", "HIGH"
        elif not opens:
            act, level = "Arrives outside receiving hours: time the departure", "MEDIUM"
        elif risk >= 0.18:
            act, level = "Confirm with the area rep", "MEDIUM"
        else:
            act, level = "Standard flow", "LOW"
        rows.append({"level": level, "truck_id": r.truck_id, "release": tr.release_id,
                     "customer_name": c.customer_name, "state": c.state, "point": w.point(tr.origin)["name"],
                     "status": r.sub, "risk": risk, "avg_site_h": feed.learner.stats.mean_h(tr.cust),
                     "eta": feed.clock.fmt(eta), "window": f"{c.receive_open:02d}:00 to {c.receive_close:02d}:00",
                     "action": act})
    out = pd.DataFrame(rows)
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return out.sort_values(["level", "risk"], key=lambda s: s.map(order) if s.name == "level" else -s).reset_index(drop=True)


def transporters(feed, days=7):
    t = feed.now()
    sim = feed.sim
    df = feed.snapshot()
    rows = []
    for name, spec in feed.world.transporters.items():
        trips = [tr for tid, ts in sim.trips.items() for tr in ts
                 if tr.transporter == name and t - days * C.DAY <= tr.t_gate_out <= t]
        arrived = [tr for tr in trips if tr.t_arrive <= t]
        visits = [tr for tr in trips if tr.t_offloaded <= t]
        span = sum(min(tr.t_back, t) - tr.t_gate_out for tr in trips) or 1
        lost = sum(max(0, min(g1, t) - g0) for tr in trips for g0, g1 in tr.gps_gaps if g0 <= t)
        fleet = df[df["transporter"] == name]
        today = [tr for tr in trips if tr.t_gate_out >= C.day_start(t)]
        rows.append({"transporter": name, "fleet": len(fleet),
                     "active_today": len({tr.truck_id for tr in today}),
                     "trips": len(trips), "tonnes": sum(tr.qty_t for tr in trips),
                     "on_time": np.mean([tr.t_arrive <= tr.t_promised for tr in arrived]) if arrived else np.nan,
                     "tracking": 1 - lost / span,
                     "avg_site_h": np.mean([tr.site_hours for tr in visits]) if visits else np.nan,
                     "past_trigger": sum(tr.site_hours >= RULES.site_reroute_hours for tr in visits),
                     "gps_lost_now": int((~fleet["gps_ok"]).sum()),
                     "idle_long_now": int((fleet["idle_h"] >= RULES.idle_alert_hours).sum())})
    return pd.DataFrame(rows).sort_values("on_time", ascending=False).reset_index(drop=True)


def points(feed, horizon_h=4):
    """Each works and depot: trucks on hand against its usual loading pace and its queue."""
    df = feed.snapshot()
    t = feed.now()
    b = STORE.ensure().book
    rel = b.open[(b.open["level"] == "release") & (b.open["terms"] == "DEL")]
    open_rel = rel.groupby("point_code", observed=True)["open_t"].sum()
    hold_ids = set(feed.world.customers.loc[feed.world.customers["on_hold"], "customer_id"])
    held = rel[rel["customer_id"].isin(hold_ids)].groupby("point_code", observed=True)["open_t"].sum()
    pace = {}
    for ts in feed.sim.trips.values():
        for tr in ts:
            if t - C.DAY <= tr.t_gate_out <= t:
                pace[tr.origin] = pace.get(tr.origin, 0.0) + tr.qty_t
    rows = []
    for p in brand.POINTS:
        code = p["code"]
        here = df[df["at_point"] == code]
        loading = here[here["stage"] == "Loading"]
        idle = here[here["stage"] == "Idle"]
        ret = df[(df["stage"] == "Returning") & (df["base"] == code)]
        arriving = ret[ret["back_t"].fillna(1e12) <= t + horizon_h * 60]
        cap_t = float(idle["capacity_t"].sum() + arriving["capacity_t"].sum())
        orders = float(open_rel.get(code, 0.0))
        usable = max(0.0, orders - float(held.get(code, 0.0)))
        due = pace.get(code, 0.0) * horizon_h / 24.0          # what the point usually loads in the horizon
        if usable < due:
            note = "Queue running low: release more orders here"
        elif due and cap_t < due * 0.5:
            note = "Fewer trucks than its usual pace: request trucks"
        elif cap_t > max(due, 30) * 1.5:
            note = "More trucks than its usual pace: release orders or move trucks"
        else:
            note = "Balanced"
        rows.append({"code": code, "name": p["name"], "type": p["type"], "state": p["state"],
                     "bays": p["bays"], "loading": int((loading["sub"] == "Loading").sum()),
                     "queued": int((loading["sub"] == "Queued").sum()), "idle": len(idle),
                     "arriving": len(arriving), "truck_t": cap_t, "open_t": orders, "due_t": due,
                     "held_t": float(held.get(code, 0.0)), "cap_tpd": p["cap_tpd"], "note": note,
                     "lat": p["lat"], "lon": p["lon"]})
    return pd.DataFrame(rows)
