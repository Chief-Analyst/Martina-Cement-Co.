"""Shift reports, written at each shift change from the control tower journal.

The figures are counted here. With a Groq key the summary paragraph is
written by the model from those figures only; without one a plain template
writes it, so a report always exists.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from ..ai import llm
from ..config import RULES
from . import clock as C

PROMPT = """You are the control tower lead at a cement company. Write a short shift report
for managers from the JSON figures given. Two short paragraphs, then a list headed
"Decisions and actions" with up to four bullets. Use only the figures given; never
invent numbers, names or causes. Plain English, no em dashes."""


def build(feed, t_from, t_to):
    """Figures for the shift between two simulation times, counted from the trips."""
    events = [e for e in feed.journal if t_from <= e["t"] < t_to]
    kinds = Counter(e["kind"] for e in events)
    sim = feed.sim
    all_trips = [tr for trips in sim.trips.values() for tr in trips]
    inside = lambda x: t_from <= x < t_to  # noqa: E731
    trips = [tr for tr in all_trips if inside(tr.t_gate_out)]
    visits = [tr for tr in all_trips if inside(tr.reroute["t_trigger"] if tr.reroute else tr.t_offloaded)]
    arrivals = [tr for tr in all_trips if inside(tr.t_arrive)]
    on_time = np.mean([tr.t_arrive <= tr.t_promised for tr in arrivals]) if arrivals else None
    site_h = np.mean([tr.site_hours for tr in visits]) if visits else None
    tonnes = sum(tr.qty_t for tr in trips)
    long_stays = sorted(visits, key=lambda tr: -tr.site_hours)[:3]
    w = feed.world
    worst = [{"truck": tr.truck_id, "customer": w.customers.iloc[tr.cust].customer_name,
              "hours": round(tr.site_hours, 1)} for tr in long_stays if tr.site_hours >= RULES.site_watch_hours]
    gaps = [(tr.transporter, g0) for tr in all_trips for g0, g1 in tr.gps_gaps if inside(g0)]
    by_trans = Counter(name for name, _ in gaps)
    idle = 0
    for ts in sim.trips.values():
        for a, b in zip(ts[:-1], ts[1:]):
            if C.window_minutes_between(a.t_back, b.t_assign, 5 * 60, 20 * 60) >= RULES.idle_alert_hours * 60:
                if inside(C.advance_window(a.t_back, RULES.idle_alert_hours * 60, 5 * 60, 20 * 60)):
                    idle += 1
    return {
        "dispatched": len(trips), "tonnes_dispatched": round(tonnes),
        "arrived": len(arrivals), "offloaded": sum(1 for tr in all_trips if inside(tr.t_offloaded)),
        "rerouted": sum(1 for tr in visits if tr.reroute),
        "past_trigger": sum(1 for tr in visits if tr.site_hours >= RULES.site_reroute_hours),
        "escalated": sum(1 for tr in visits if tr.site_hours >= RULES.site_escalate_hours),
        "gps_lost": len(gaps), "idle_4h": idle,
        "on_time_pct": None if on_time is None else round(float(on_time) * 100),
        "avg_site_hours": None if site_h is None else round(float(site_h), 1),
        "longest_stays": worst, "gps_lost_by_transporter": dict(by_trans.most_common(3)),
        "decisions_in_app": kinds.get("Actioned", 0),
    }


def template(f, label):
    on_time = f"{f['on_time_pct']}% of arrivals were on time" if f["on_time_pct"] is not None else "no arrivals were recorded"
    site = (f"trucks spent {f['avg_site_hours']} hours on site on average"
            if f["avg_site_hours"] is not None else "no visits finished")
    p1 = (f"The {label} dispatched {f['dispatched']} trucks carrying {f['tonnes_dispatched']:,} t. "
          f"{f['arrived']} arrivals and {f['offloaded']} offloads were recorded; {on_time}, and {site}.")
    worst = ", ".join(f"{x['truck']} at {x['customer']} ({x['hours']}h)" for x in f["longest_stays"])
    p2 = (f"{f['past_trigger']} trucks passed the {RULES.site_reroute_hours:g}-hour trigger and {f['rerouted']} were rerouted. "
          f"Tracking dropped {f['gps_lost']} times and {f['idle_4h']} trucks sat idle for 4 hours or more."
          + (f" Longest stays: {worst}." if worst else ""))
    acts = []
    if f["past_trigger"] > f["rerouted"]:
        acts.append("Review trucks past the trigger that were not rerouted and line up ready customers nearby")
    if f["gps_lost_by_transporter"]:
        top = max(f["gps_lost_by_transporter"], key=f["gps_lost_by_transporter"].get)
        acts.append(f"Raise tracking compliance with {top}")
    if f["idle_4h"]:
        acts.append("Match idle trucks to released orders at their base")
    if not acts:
        acts.append("No actions needed: the shift ran inside every threshold")
    return p1 + "\n\n" + p2 + "\n\n**Decisions and actions**\n" + "\n".join(f"- {a}" for a in acts[:4])


def write(feed, t_from, t_to):
    f = build(feed, t_from, t_to)
    clk = feed.clock
    start, end = clk.dt(t_from), clk.dt(t_to)
    label = "night shift" if start.hour >= 18 or start.hour < 6 else "day shift"
    title = f"{start:%a %d %b}, {label} {start:%H:%M} to {end:%H:%M}"
    text = None
    if llm.enabled():
        import json
        text = llm.chat(PROMPT, f"Shift: {title}\nFigures: {json.dumps(f)}", max_tokens=500)
    return {"t": t_to, "title": title, "figures": f, "text": text or template(f, label),
            "writer": "Groq" if text else "Template"}
