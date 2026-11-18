"""Fleet simulation: every truck's trips as a timeline of timestamps.

A trip is planned in one go when a truck becomes free: queue and load at a
works or depot, drive to a customer, wait and offload inside the customer's
receiving window (or get rerouted once the site time passes the trigger),
drive back. The truck's position and stage at any moment are read off that
timeline, so the simulation can run months of history in a second and then
continue live as the clock moves.

Trucks are planned in time order (a heap keyed by the moment each truck is
free), so a trip knows how many other trucks are already at its customer's
site and at its loading point, which is what makes queues and long site
times emerge rather than being drawn from thin air.
"""
from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .. import brand
from ..config import RULES
from . import clock as C
from .world import World

STAGES = ["Loading", "In transit", "At site", "Returning", "Idle"]


@dataclass
class Trip:
    id: str
    truck_id: str
    transporter: str
    origin: str
    cust: int                    # customer index in world.customers
    release_id: str
    product: str
    qty_t: float
    t_assign: float
    t_load_start: float
    t_gate_out: float
    t_promised: float
    t_arrive: float
    t_offloaded: float
    t_depart: float
    t_back: float
    base: str
    dist_km: float
    return_km: float
    plan_travel_min: float       # what a planner would estimate: distance at nominal speed
    travel_min: float            # actual driving minutes to the first site
    return_min: float
    site_hours: float            # time counted on the first site (window hours)
    queue_on_arrival: int        # trucks already at the site when this one arrived
    queue_at_load: int
    reroute: dict | None = None  # {"to": idx, "t_leave": t, "t_arrive": t, "km": d}
    gps_gaps: list = field(default_factory=list)
    pred: dict | None = None     # predictions made at dispatch

    @property
    def final_cust(self):
        return self.reroute["to"] if self.reroute else self.cust

    @property
    def t_final_arrive(self):
        return self.reroute["t_arrive"] if self.reroute else self.t_arrive


def bezier(a, b, n=24, salt=0):
    """A gently curved path between two points, the same every time."""
    (la, lo), (lb, lob) = a, b
    dx, dy = lob - lo, lb - la
    k = (((hash((round(la, 3), round(lo, 3), round(lb, 3), round(lob, 3))) + salt) % 1000) / 1000.0 - 0.5) * 0.35
    mx, my = (lo + lob) / 2 - dy * k, (la + lb) / 2 + dx * k
    t = np.linspace(0, 1, n)
    lons = (1 - t) ** 2 * lo + 2 * (1 - t) * t * mx + t ** 2 * lob
    lats = (1 - t) ** 2 * la + 2 * (1 - t) * t * my + t ** 2 * lb
    return lats, lons


def along(a, b, frac):
    lats, lons = bezier(a, b)
    f = min(max(frac, 0.0), 1.0) * (len(lats) - 1)
    i = int(f)
    if i >= len(lats) - 1:
        return float(lats[-1]), float(lons[-1])
    r = f - i
    return float(lats[i] + (lats[i + 1] - lats[i]) * r), float(lons[i] + (lons[i + 1] - lons[i]) * r)


class Simulator:
    def __init__(self, world: World, seed=11, open_releases=None):
        self.w = world
        self.rng = np.random.default_rng(seed)
        self.trips: dict[str, list[Trip]] = defaultdict(list)    # truck -> trips in order
        self.by_id: dict[str, Trip] = {}
        self.site_busy = defaultdict(list)       # cust idx -> [(t_in, t_out)]
        self.load_busy = defaultdict(list)       # point code -> [(t_start, t_end)]
        self.heap = []                           # (t_free, truck_id)
        self.events = []                         # heap of (t, seq, kind, trip_id, detail)
        self._seq = 0
        self.n = 0
        self.planned_until = 0.0
        self.predictor = None                    # set by the feed once models exist
        self.open_releases = open_releases or {}
        self.truck = {r.truck_id: r for r in world.trucks.itertuples()}
        self.trans_speed = {name: 0.92 + 0.16 * t["reliability"] for name, t in world.transporters.items()}

    # -- set-up ---------------------------------------------------------
    def start(self, t0):
        for r in self.w.trucks.itertuples():
            heapq.heappush(self.heap, (t0 + float(self.rng.uniform(0, 600)), r.truck_id))

    def run_until(self, t_end, record_events=True):
        """Plan trips for every truck that becomes free before t_end."""
        while self.heap and self.heap[0][0] <= t_end:
            t_free, tid = heapq.heappop(self.heap)
            trip = self._plan(tid, t_free, record_events)
            heapq.heappush(self.heap, (trip.t_back, tid))
        self.planned_until = max(self.planned_until, t_end)

    # -- helpers --------------------------------------------------------
    def _event(self, t, kind, trip, detail=""):
        self._seq += 1
        heapq.heappush(self.events, (t, self._seq, kind, trip.id, detail))

    def _count(self, intervals, t):
        return sum(1 for a, b in intervals if a <= t < b)

    def _travel(self, km, cust_row, transporter, t_depart):
        speed = RULES.truck_speed_kmh * cust_row.speed_factor * self.trans_speed.get(transporter, 1.0)
        m = C.minute_of_day(t_depart) / 60.0
        rush = 1.22 if (6.5 <= m <= 9.5 or 16 <= m <= 19.5) and cust_row.region in ("Lagos", "South West") else 1.0
        minutes = km / speed * 60.0 * rush * float(self.rng.lognormal(0, 0.12))
        return max(12.0, minutes)

    def _pick(self, point_code):
        idx, wgt = self.w.candidates[point_code]
        return int(self.rng.choice(idx, p=wgt))

    def _product(self, cust_row, point_code):
        p = self.w.point(point_code)
        names = brand.PRODUCT_NAMES
        mix = np.array(cust_row.mix, float)
        ok = np.array([n in p["products"] for n in names], float)
        pr = mix * ok
        if pr.sum() <= 0:
            pr = ok
        return names[int(self.rng.choice(len(names), p=pr / pr.sum()))]

    # -- the trip -------------------------------------------------------
    def _plan(self, truck_id, t_free, record):
        rng, w = self.rng, self.w
        tk = self.truck[truck_id]
        trans = w.transporters.get(tk.transporter, {"reliability": 0.85})
        prev = self.trips[truck_id][-1] if self.trips[truck_id] else None
        origin = prev.base if prev else tk.home_point

        # Idle at base, then the next load (dispatch runs 05:00 to 20:00)
        idle = float(rng.exponential(55 / max(trans["reliability"], 0.5)))
        if rng.random() < 0.07:
            idle = float(rng.uniform(4.2, 10)) * 60
        t_assign = t_free + idle
        mod = C.minute_of_day(t_assign)
        if mod < 5 * 60 or mod > 20 * 60:
            t_assign = C.day_start(t_assign) + (C.DAY if mod > 20 * 60 else 0) + 5 * 60 + float(rng.uniform(0, 90))
        # Customer and product first, so the departure can be timed to the site's hours
        ci = self._pick(origin)
        c = w.customers.iloc[ci]
        product = self._product(c, origin)
        km = float(w.dist_cp[ci, w.point_index[origin]]) * RULES.road_factor * float(rng.uniform(0.97, 1.06))
        plan = km / RULES.truck_speed_kmh * 60.0
        open_m, close_m = int(c.receive_open) * 60.0, int(c.receive_close) * 60.0
        est_arr = C.drive(t_assign + 85, plan)
        if (C.minute_of_day(est_arr) > close_m - 60 or C.minute_of_day(est_arr) < open_m - 90) \
                and rng.random() < 0.75:
            # Dispatchers hold the load so the truck reaches the site as it opens
            day = C.day_start(est_arr) + (C.DAY if C.minute_of_day(est_arr) > close_m - 60 else 0)
            target = day + open_m + float(rng.uniform(0, 150))
            t_new = target - plan - 85
            while C.minute_of_day(t_new) < 5 * 60 or C.minute_of_day(t_new) > 20 * 60:
                t_new -= 30
            t_assign = max(t_assign, t_new)

        if prev and C.window_minutes_between(t_free, t_assign, 5 * 60, 20 * 60) >= RULES.idle_alert_hours * 60 and record:
            dummy = Trip(id=f"idle-{truck_id}", truck_id=truck_id, transporter=tk.transporter, origin=origin,
                         cust=prev.final_cust, release_id="", product="", qty_t=0, t_assign=t_free,
                         t_load_start=t_free, t_gate_out=t_free, t_promised=t_free, t_arrive=t_free,
                         t_offloaded=t_free, t_depart=t_free, t_back=t_free, base=origin, dist_km=0,
                         return_km=0, plan_travel_min=0, travel_min=0, return_min=0, site_hours=0,
                         queue_on_arrival=0, queue_at_load=0)
            self._event(C.advance_window(t_free, RULES.idle_alert_hours * 60, 5 * 60, 20 * 60), "Idle 4h+", dummy,
                        f"{truck_id} idle at {w.point(origin)['name']} since {C.minute_of_day(t_free) // 60:02.0f}:00")

        # Queue and load
        pt = w.point(origin)
        busy = self._count(self.load_busy[origin], t_assign)
        wait = max(0, busy - int(pt["bays"]) + 1) * 40.0 + float(rng.exponential(14))
        load = float(np.clip(rng.normal(48 if tk.body == "Bulk" else 66, 12), 30, 115))
        t_load_start = t_assign + wait
        t_gate_out = t_load_start + load
        self.load_busy[origin].append((t_load_start, t_gate_out))

        # Drive
        travel = self._travel(km, c, tk.transporter, t_gate_out)
        t_arrive = C.drive(t_gate_out, travel)
        t_promised = C.drive(t_gate_out, plan + 60.0)

        # Time on site, counted inside the receiving window
        queue = self._count(self.site_busy[ci], t_arrive)
        late = C.minute_of_day(t_arrive) > close_m - 120 or C.minute_of_day(t_arrive) < open_m
        hours = float(c.site_hours) * 0.72 * float(rng.lognormal(0, 0.28))
        hours += 1.5 * max(0, queue - int(c.bays) + 1) + (2.2 if late else 0.0)
        dow = int((t_arrive // C.DAY) % 7)
        hours += {5: 1.4, 6: 2.0, 0: 0.6}.get(dow, 0.0)          # weekends and Monday backlog
        if self.rng.random() < 0.04:
            hours += float(rng.uniform(6, 20))                  # a site that is simply not ready
        hours = float(min(hours, 40.0))

        reroute = None
        if hours > RULES.site_reroute_hours and rng.random() < 0.62:
            t_trig = C.advance_window(t_arrive, RULES.site_reroute_hours * 60, open_m, close_m)
            near = np.where((w.dist_cc[ci] < 60) & (w.dist_cc[ci] > 0.2) &
                            (~w.customers["on_hold"].to_numpy()))[0]
            if len(near):
                d = w.dist_cc[ci, near]
                alt = int(rng.choice(near, p=(1 / (d + 3)) / (1 / (d + 3)).sum()))
                a = w.customers.iloc[alt]
                km2 = float(w.dist_cc[ci, alt]) * RULES.road_factor
                t_leave = t_trig + float(rng.uniform(15, 40))
                t_arr2 = C.drive(t_leave, self._travel(km2, a, tk.transporter, t_leave))
                h2 = float(a.site_hours) * 0.6 * float(rng.lognormal(0, 0.3))
                t_off = C.advance_window(t_arr2, h2 * 60, a.receive_open * 60.0, a.receive_close * 60.0)
                reroute = {"to": alt, "t_trigger": t_trig, "t_leave": t_leave, "t_arrive": t_arr2,
                           "km": km2, "hours2": h2}
                self.site_busy[ci].append((t_arrive, t_leave))
                self.site_busy[alt].append((t_arr2, t_off))
                hours = RULES.site_reroute_hours
        if reroute is None:
            t_off = C.advance_window(t_arrive, hours * 60, open_m, close_m)
            self.site_busy[ci].append((t_arrive, t_off))

        t_depart = t_off + float(rng.uniform(10, 30))
        final = reroute["to"] if reroute else ci
        if rng.random() < 0.85:
            base = origin
        else:
            base = w.points["code"].iloc[int(w.dist_cp[final].argmin())]
        fc = w.customers.iloc[final]
        rkm = float(w.dist_cp[final, w.point_index[base]]) * RULES.road_factor
        rmin = self._travel(rkm, fc, tk.transporter, t_depart)
        t_back = C.drive(t_depart, rmin)

        self.n += 1
        rel = self.open_releases.get((c.customer_id, product))
        trip = Trip(id=f"TRP-{self.n:06d}", truck_id=truck_id, transporter=tk.transporter, origin=origin,
                    cust=ci, release_id=rel or f"DLV-{self.n:06d}", product=product,
                    qty_t=float(tk.capacity_t), t_assign=t_assign, t_load_start=t_load_start,
                    t_gate_out=t_gate_out, t_promised=t_promised, t_arrive=t_arrive, t_offloaded=t_off,
                    t_depart=t_depart, t_back=t_back, base=base, dist_km=km, return_km=rkm,
                    plan_travel_min=plan, travel_min=C.driving_minutes_between(t_gate_out, t_arrive),
                    return_min=C.driving_minutes_between(t_depart, t_back), site_hours=hours,
                    queue_on_arrival=queue, queue_at_load=busy, reroute=reroute)

        # Tracking gaps: weaker transporters lose GPS more often
        if rng.random() < (1 - trans["reliability"]) * 1.7 and t_back - t_gate_out > 60:
            g0 = float(rng.uniform(t_gate_out, max(t_gate_out + 1, t_back - 40)))
            trip.gps_gaps.append((g0, min(t_back, g0 + 30 + float(rng.exponential(85)))))

        if self.predictor is not None:
            try:
                trip.pred = self.predictor(trip)
            except Exception:                                   # noqa: BLE001
                trip.pred = None

        self.trips[truck_id].append(trip)
        self.by_id[trip.id] = trip
        if record:
            self._journal(trip, c)
        return trip

    def _journal(self, trip, c):
        w = self.w
        name = c.customer_name
        pt = w.point(trip.origin)["name"]
        self._event(trip.t_assign, "Load assigned", trip, f"{trip.truck_id} to load {trip.product} at {pt} for {name}")
        self._event(trip.t_gate_out, "Dispatched", trip,
                    f"{trip.truck_id} left {pt} for {name} ({c.town}), {trip.qty_t:.0f} t {trip.product}")
        late = (trip.t_arrive - trip.t_promised) / 60
        self._event(trip.t_arrive, "Arrived", trip,
                    f"{trip.truck_id} arrived at {name}" + (f", {late:.1f}h after the promised time" if late > 0.25 else ""))
        open_m, close_m = c.receive_open * 60.0, c.receive_close * 60.0
        for h, kind in ((RULES.site_watch_hours, "Watch: 5h on site"),
                        (RULES.site_reroute_hours, "Past reroute trigger"),
                        (RULES.site_escalate_hours, "Escalated")):
            if trip.site_hours >= h - 1e-6 and (kind != "Escalated" or not trip.reroute):
                self._event(C.advance_window(trip.t_arrive, h * 60, open_m, close_m), kind, trip,
                            f"{trip.truck_id} at {name}: {h:g}h on site")
        if trip.reroute:
            a = w.customers.iloc[trip.reroute["to"]]
            self._event(trip.reroute["t_leave"], "Rerouted", trip,
                        f"{trip.truck_id} moved from {name} to {a.customer_name} ({trip.reroute['km']:.0f} km)")
            self._event(trip.reroute["t_arrive"], "Arrived", trip, f"{trip.truck_id} arrived at {a.customer_name} (rerouted)")
        final = w.customers.iloc[trip.final_cust]
        self._event(trip.t_offloaded, "Offloaded", trip, f"{trip.truck_id} offloaded at {final.customer_name}")
        self._event(trip.t_back, "Back at base", trip, f"{trip.truck_id} back at {w.point(trip.base)['name']}, empty")
        for g0, g1 in trip.gps_gaps:
            self._event(g0, "GPS lost", trip, f"{trip.truck_id} stopped reporting position")
            if g1 - g0 >= RULES.gps_lost_minutes:
                self._event(g0 + RULES.gps_lost_minutes, "GPS lost 30 min", trip,
                            f"{trip.truck_id} has not reported for {RULES.gps_lost_minutes} minutes")
            self._event(g1, "GPS restored", trip, f"{trip.truck_id} reporting again after {(g1 - g0):.0f} min")

    # -- reading state ----------------------------------------------------
    def current_trip(self, truck_id, t):
        trips = self.trips.get(truck_id, [])
        for tr in reversed(trips):
            if tr.t_assign <= t:
                return tr
        return None

    def state(self, truck_id, t):
        """Stage, position and the facts the pages need, for one truck at time t."""
        w = self.w
        tk = self.truck[truck_id]
        tr = self.current_trip(truck_id, t)
        s = {"truck_id": truck_id, "plate": tk.plate, "transporter": tk.transporter, "body": tk.body,
             "capacity_t": float(tk.capacity_t), "trip_id": "", "gps_ok": True}
        if tr is None or t >= tr.t_back:
            base = tr.base if tr else tk.home_point
            p = w.point(base)
            # idle time counts only in dispatch hours, not overnight
            s.update(stage="Idle", sub="At base", lat=float(p["lat"]), lon=float(p["lon"]), at_point=base,
                     idle_h=C.window_minutes_between(tr.t_back, t, 5 * 60, 20 * 60) / 60 if tr else 0.0)
            return s
        c = w.customers.iloc[tr.cust]
        s.update(trip_id=tr.id, customer_id=c.customer_id, release_id=tr.release_id, product=tr.product,
                 qty_t=tr.qty_t, origin=tr.origin)
        for g0, g1 in tr.gps_gaps:
            if g0 <= t < g1:
                s["gps_ok"] = False
                s["gps_lost_min"] = t - g0
                t_seen = g0
                break
        else:
            t_seen = t
        p0 = w.point(tr.origin)
        a = (float(p0["lat"]), float(p0["lon"]))
        site = (float(c.lat), float(c.lon))
        if t < tr.t_gate_out:
            s.update(stage="Loading", sub="Queued" if t < tr.t_load_start else "Loading",
                     lat=a[0], lon=a[1], at_point=tr.origin)
        elif t < tr.t_arrive:
            frac = C.driving_minutes_between(tr.t_gate_out, t_seen) / max(1.0, tr.travel_min)
            lat, lon = along(a, site, frac)
            s.update(stage="In transit", sub="To customer", lat=lat, lon=lon, progress=frac)
        elif tr.reroute and t >= tr.reroute["t_leave"] and t < tr.reroute["t_arrive"]:
            alt = w.customers.iloc[tr.reroute["to"]]
            leg = tr.reroute["t_arrive"] - tr.reroute["t_leave"]
            frac = C.driving_minutes_between(tr.reroute["t_leave"], t_seen) / max(1.0, C.driving_minutes_between(tr.reroute["t_leave"], tr.reroute["t_arrive"]) or leg)
            lat, lon = along(site, (float(alt.lat), float(alt.lon)), frac)
            s.update(stage="In transit", sub="Rerouted", lat=lat, lon=lon, progress=frac)
        elif t < tr.t_depart:
            cc = w.customers.iloc[tr.final_cust] if (tr.reroute and t >= tr.reroute["t_arrive"]) else c
            t_in = tr.reroute["t_arrive"] if cc is not c else tr.t_arrive
            cico = C.window_minutes_between(t_in, t, cc.receive_open * 60.0, cc.receive_close * 60.0) / 60.0
            s.update(stage="At site", sub="Offloaded" if t >= tr.t_offloaded else
                     ("Waiting for the site to open" if cico == 0 and t > t_in + 10 else "Offloading"),
                     lat=float(cc.lat), lon=float(cc.lon), site_cust=cc.customer_id, cico_h=cico,
                     on_site_since=t_in, wall_h=(t - t_in) / 60)
        else:
            fc = w.customers.iloc[tr.final_cust]
            b = w.point(tr.base)
            frac = C.driving_minutes_between(tr.t_depart, t_seen) / max(1.0, tr.return_min)
            lat, lon = along((float(fc.lat), float(fc.lon)), (float(b["lat"]), float(b["lon"])), frac)
            s.update(stage="Returning", sub="Empty, heading to base", lat=lat, lon=lon, progress=frac)
        return s

    def completed(self, t):
        """Trips finished (back at base) before time t."""
        return [tr for trips in self.trips.values() for tr in trips if tr.t_back <= t]

    def pop_events(self, t):
        out = []
        while self.events and self.events[0][0] <= t:
            out.append(heapq.heappop(self.events))
        return out


def tier(hours):
    if hours is None or (isinstance(hours, float) and math.isnan(hours)):
        return ""
    if hours < RULES.site_watch_hours:
        return "Normal"
    if hours < RULES.site_reroute_hours:
        return "Watch"
    if hours < RULES.site_escalate_hours:
        return "Reroute"
    return "Escalate"
