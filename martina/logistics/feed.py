"""The live control tower: one simulation clock shared by every viewer.

A background thread moves the clock, releases journal events as their time
comes, raises alerts, writes shift reports at 07:00 and 19:00, scores the
models' predictions as outcomes arrive and retrains them every morning.
Pages only ever read `FEED.snapshot()`, a frame rebuilt once per tick, so
ten viewers cost the same as one.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..alerts.notify import NOTIFIER
from ..config import RULES, SETTINGS
from ..data.store import STORE
from . import clock as C
from . import reports
from .learn import Learner
from .sim import Simulator, tier
from .world import build_world

log = logging.getLogger("martina.feed")

SEVERITY = {"Escalated": "Critical", "Past reroute trigger": "Warning", "GPS lost 30 min": "Warning",
            "Rerouted": "Warning", "Watch: 5h on site": "Watch", "GPS lost": "Watch", "Idle 4h+": "Watch",
            "Dispatched to hold": "Warning"}


class Feed:
    def __init__(self):
        self.lock = threading.RLock()
        self.world = None
        self.sim = None
        self.learner = None
        self.clock = None
        self.t = 0.0
        self.journal = deque(maxlen=6000)
        self.reports = deque(maxlen=60)
        self.actioned = {}
        self.state = "idle"
        self.error = None
        self._snap = None
        self._snap_t = None
        self._scored = set()
        self._last_shift = None
        self._last_train_day = None
        self._ready_cache = (None, None)
        self.tick_seconds = 1.0
        self.version = 0
        self.site_counts = {}
        self.heading_counts = {}

    # -- start-up ---------------------------------------------------------
    def start(self):
        if self.state != "idle":
            return
        self.state = "warming up"
        threading.Thread(target=self._boot, daemon=True, name="feed-boot").start()

    def _boot(self):
        try:
            t0 = time.perf_counter()
            STORE.ensure()
            self.world = build_world(STORE.frames, STORE.traits)
            H = SETTINGS.sim_history_days
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            self.clock = C.Clock(today - timedelta(days=H))
            self.sim = Simulator(self.world, seed=SETTINGS.seed + 7, open_releases=self._open_releases())
            self.sim.start(0.0)
            self.sim.run_until(H * C.DAY, record_events=False)
            self.learner = Learner(self.sim)
            self.learner.train(H * C.DAY)
            self.sim.predictor = self._predict
            self.t = H * C.DAY + 6.5 * 60            # live from 06:30 today, control tower clock
            # trips already under way when the live clock starts still owe their journal events
            for trips in self.sim.trips.values():
                for tr in trips:
                    if tr.t_back > self.t:
                        self.sim._journal(tr, self.world.customers.iloc[tr.cust])
            self.sim.events = [e for e in self.sim.events if e[0] >= self.t]
            # trips already planned or under way get the same predictions a live dispatch gets
            for trips in self.sim.trips.values():
                for tr in trips:
                    if tr.t_back > self.t and tr.pred is None:
                        tr.pred = self._predict(tr)
            import heapq
            heapq.heapify(self.sim.events)
            self.sim.run_until(self.t + C.DAY)
            self._scored = {tr.id for tr in self.sim.completed(self.t)}
            self._last_shift = self._shift_start(self.t)
            self._last_train_day = int(self.t // C.DAY)
            NOTIFIER.set_recipients(STORE.frames.get("recipients"))
            # the last two shifts already have reports, written from the history
            s1 = self._last_shift
            for a, b in ((s1 - 2 * 720, s1 - 720), (s1 - 720, s1)):
                self.reports.appendleft(reports.write(self, a, b))
            STORE.on_refresh(self._on_data_refresh)
            self._rebuild()
            self.state = "running"
            log.info("control tower ready in %.1fs", time.perf_counter() - t0)
            threading.Thread(target=self._loop, daemon=True, name="feed-loop").start()
        except Exception as e:                               # noqa: BLE001
            self.state = "failed"
            self.error = repr(e)
            log.exception("control tower failed to start")

    def _open_releases(self):
        b = STORE.ensure().book
        rel = b.open[(b.open["level"] == "release") & (b.open["terms"] == "DEL")]
        return {(r.customer_id, str(r.product)): r.order_id for r in rel.itertuples()}

    def _on_data_refresh(self, store):
        if self.world is None:
            return
        credit = store.frames["credit"].set_index("customer_id")
        with self.lock:
            c = self.world.customers
            c["on_hold"] = c["customer_id"].map(credit["on_hold"]).fillna(False).astype(bool)
            c["hold_reason"] = c["customer_id"].map(credit["hold_reason"]).fillna("")
            c["balance_ngn"] = c["customer_id"].map(credit["balance_ngn"]).fillna(0.0)
            self.sim.open_releases = self._open_releases()

    # -- the clock ----------------------------------------------------------
    def _loop(self):
        last = time.perf_counter()
        while True:
            time.sleep(self.tick_seconds)
            now = time.perf_counter()
            try:
                self.advance((now - last) * SETTINGS.sim_minutes_per_second)
            except Exception:                                # noqa: BLE001
                log.exception("control tower tick failed")
            last = now

    def advance(self, minutes):
        with self.lock:
            self.t += minutes
            self.sim.run_until(self.t + 12 * 60)
            for t, _seq, kind, trip_id, detail in self.sim.pop_events(self.t):
                self._log(t, kind, trip_id, detail)
            finished = [tr for trips in self.sim.trips.values() for tr in trips[-3:]
                        if tr.t_back <= self.t and tr.id not in self._scored]
            if finished:
                self.learner.record_outcomes(finished)
                self._scored.update(tr.id for tr in finished)
            shift = self._shift_start(self.t)
            if shift != self._last_shift:
                prev = self._last_shift
                self._last_shift = shift
                threading.Thread(target=self._write_report, args=(prev, shift), daemon=True).start()
            day = int(self.t // C.DAY)
            if day != self._last_train_day and C.minute_of_day(self.t) >= 5.5 * 60:
                self._last_train_day = day
                threading.Thread(target=self.retrain, daemon=True, name="retrain").start()
            self._rebuild()

    @staticmethod
    def _shift_start(t):
        d, m = C.day_start(t), C.minute_of_day(t)
        a, b = RULES.shift_hours[0] * 60, RULES.shift_hours[1] * 60
        if m < a:
            return d - C.DAY + b
        return d + (a if m < b else b)

    def _write_report(self, t_from, t_to):
        try:
            rep = reports.write(self, t_from, t_to)
            with self.lock:
                self.reports.appendleft(rep)
        except Exception:                                    # noqa: BLE001
            log.exception("shift report failed")

    def write_report_now(self):
        rep = reports.write(self, self._shift_start(self.t), self.t)
        rep["title"] += " (so far)"
        with self.lock:
            self.reports.appendleft(rep)
        return rep

    def retrain(self):
        rep = self.learner.train(self.t)
        self._log(self.t, "Models retrained", "", "Daily retrain on every finished trip" if rep else "Retrain skipped")
        return rep

    # -- journal and alerts ---------------------------------------------------
    def _log(self, t, kind, trip_id, detail):
        tr = self.sim.by_id.get(trip_id) if trip_id else None
        c = self.world.customers.iloc[tr.cust] if tr else None
        entry = {"t": t, "when": self.clock.fmt(t, True), "kind": kind, "severity": SEVERITY.get(kind, "Info"),
                 "truck": tr.truck_id if tr else (trip_id.split("-", 1)[1] if trip_id.startswith("idle-") else ""),
                 "trip": trip_id if tr else "", "customer": c.customer_name if c is not None else "",
                 "state": c.state if c is not None else "", "region": c.region if c is not None else "",
                 "transporter": tr.transporter if tr else "", "text": detail}
        self.journal.appendleft(entry)
        self._alert(entry, tr, c)

    def _alert(self, e, tr, c):
        kind = e["kind"]
        when = e["when"]
        if kind == "Dispatched" and c is not None and bool(c.on_hold):
            NOTIFIER.raise_alert("Dispatched to hold", f"hold:{tr.id}", when,
                                 f"{tr.truck_id} left with {tr.qty_t:.0f} t for {c.customer_name}, "
                                 f"which is on credit hold ({c.hold_reason}).", region=c.region,
                                 customer=c.customer_name)
            self._log(e["t"], "Dispatched to hold", tr.id, f"{tr.truck_id} dispatched to {c.customer_name} on credit hold")
        elif kind in ("Past reroute trigger", "Escalated") and tr is not None:
            h = RULES.site_reroute_hours if kind == "Past reroute trigger" else RULES.site_escalate_hours
            NOTIFIER.raise_alert(kind, f"{kind}:{tr.id}", when,
                                 f"{tr.truck_id} ({tr.transporter}) has been {h:g} hours on site at "
                                 f"{c.customer_name}, {c.town}. Check the Rerouting tab for ready customers nearby.",
                                 region=c.region, point=tr.origin, h=f"{h:g}", truck=tr.truck_id,
                                 customer=c.customer_name)
        elif kind == "GPS lost 30 min" and tr is not None:
            NOTIFIER.raise_alert(kind, f"gps:{tr.id}:{int(e['t'])}", when,
                                 f"{tr.truck_id} ({tr.transporter}) stopped reporting its position. "
                                 "No tracking, no next load until it reports again.",
                                 truck=tr.truck_id, transporter=tr.transporter)
        elif kind == "Idle 4h+":
            truck = e["truck"]
            tk = self.sim.truck.get(truck)
            if tk is not None:
                prev = self.sim.current_trip(truck, e["t"])
                base = prev.base if prev else tk.home_point
                NOTIFIER.raise_alert(kind, f"idle:{truck}:{int(e['t'] // 60)}", when,
                                     f"{truck} has been idle for {RULES.idle_alert_hours:g} hours at "
                                     f"{self.world.point(base)['name']}.", point=base, truck=truck,
                                     point_name=self.world.point(base)["name"])

    def mark_actioned(self, key, note):
        with self.lock:
            self.actioned[key] = {"t": self.t, "note": note}
            self._log(self.t, "Actioned", "", note)

    # -- the snapshot pages read ---------------------------------------------
    def _predict(self, trip):
        at_site = sum(1 for a, b in self.sim.site_busy[trip.cust] if a <= trip.t_gate_out < b)
        heading = 0
        for trips in self.sim.trips.values():
            if trips:
                x = trips[-1]
                if x.cust == trip.cust and x.t_gate_out <= trip.t_gate_out < x.t_arrive:
                    heading += 1
        return self.learner.predict(trip, at_site, heading)

    def _rebuild(self):
        sim, w, t = self.sim, self.world, self.t
        rows = []
        for tid in sim.truck:
            s = sim.state(tid, t)
            tr = sim.by_id.get(s["trip_id"]) if s["trip_id"] else None
            if tr is not None:
                c = w.customers.iloc[tr.cust]
                s.update(customer_name=c.customer_name, region=c.region, state=c.state, town=c.town,
                         dest_lat=float(c.lat), dest_lon=float(c.lon), on_hold=bool(c.on_hold),
                         origin_name=w.point(tr.origin)["name"], base=tr.base,
                         base_name=w.point(tr.base)["name"], t_gate_out=tr.t_gate_out,
                         t_promised=tr.t_promised, rerouted=bool(tr.reroute and t >= tr.reroute["t_leave"]))
                p = tr.pred
                if p:
                    s["risk"] = p["value"]["risk"]
                    s["eta_t"] = C.drive(tr.t_gate_out, p["value"]["eta"])
                    off_h = p["value"]["site"]
                    s["offload_t"] = C.advance_window(s["eta_t"], off_h * 60, c.receive_open * 60.0,
                                                      c.receive_close * 60.0)
                    s["back_t"] = C.drive(s["offload_t"] + 20, p["value"]["back"])
                    s["back_late_t"] = C.drive(s["offload_t"] + 20, p["value"]["back"] + p["q90"].get("back", 0))
                if s["stage"] == "In transit" and t > tr.t_promised:
                    s["late_h"] = (t - tr.t_promised) / 60
                if s["stage"] == "At site":
                    s["tier"] = tier(s.get("cico_h", 0))
                if s["stage"] == "Returning" and p:
                    s["back_t"] = C.drive(tr.t_depart, p["value"]["back"])
            else:
                s.update(customer_name="", region="", state="", town="", base=s.get("at_point", ""),
                         base_name=w.point(s.get("at_point", ""))["name"] if s.get("at_point") else "")
            rows.append(s)
        df = pd.DataFrame(rows)
        for col in ("cico_h", "idle_h", "late_h", "risk", "gps_lost_min", "progress", "wall_h"):
            if col not in df:
                df[col] = np.nan
        for col in ("tier", "sub", "at_point", "site_cust"):
            if col not in df:
                df[col] = ""
        df["stage_view"] = np.where(~df["gps_ok"], "No GPS", df["stage"])
        ci = w.cust_index
        site = df.loc[df["stage"] == "At site", "site_cust"].map(ci).dropna().astype(int).value_counts()
        head = df.loc[df["stage"].isin(["In transit", "Loading"]), "customer_id"].map(ci).dropna().astype(int).value_counts()
        self.site_counts = {int(k): int(v) for k, v in site.items()}
        self.heading_counts = {int(k): int(v) for k, v in head.items()}
        self._snap = df
        self._snap_t = t
        self.version += 1

    # -- readers ------------------------------------------------------------
    def ready(self):
        return self.state == "running"

    def snapshot(self):
        return self._snap

    def now(self):
        return self.t

    def now_label(self):
        return self.clock.fmt(self.t, True) if self.clock else "-"

    def headline(self):
        if not self.ready():
            return None
        df = self._snap
        return {"past_reroute": int((df["cico_h"] >= RULES.site_reroute_hours).sum()),
                "gps_lost": int((~df["gps_ok"]).sum()), "at_site": int((df["stage"] == "At site").sum()),
                "trucks": len(df)}

    def latest_report(self):
        return self.reports[0] if self.reports else None

    def readiness_cached(self, build):
        key = int(self.t // 30)
        if self._ready_cache[0] != key:
            self._ready_cache = (key, build())
        return self._ready_cache[1]


FEED = Feed()
