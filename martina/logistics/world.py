"""The fixed facts the fleet simulation works with.

Customers, works and depots, trucks and transporters come from the data
store, so the Logistics page shows the same customers as the order book.
Behaviour the data cannot tell us (how long a customer usually keeps a
truck) comes from the synthetic traits, or from defaults for CSV data.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import brand
from ..geo import haversine_km

# Road speed by region: congestion in Lagos, poorer roads in the creeks.
REGION_SPEED = {"Lagos": 0.72, "South West": 0.95, "South South": 0.82, "South East": 0.9,
                "North Central": 1.0, "North West": 1.08, "North East": 1.02}


@dataclass
class World:
    customers: pd.DataFrame
    points: pd.DataFrame
    trucks: pd.DataFrame
    transporters: dict
    cust_index: dict = field(default_factory=dict)
    point_index: dict = field(default_factory=dict)
    dist_cp: np.ndarray | None = None          # customer x point, km
    dist_cc: np.ndarray | None = None          # customer x customer, km
    candidates: dict = field(default_factory=dict)   # point code -> (customer idx, weights)

    def customer(self, cid):
        return self.customers.iloc[self.cust_index[cid]]

    def point(self, code):
        return self.points.iloc[self.point_index[code]]


def build_world(frames, traits=None) -> World:
    c = frames["customers"].copy()
    credit = frames["credit"].set_index("customer_id")
    tgt = frames["targets"].set_index("customer_id")["daily_target_t"]
    c["on_hold"] = c["customer_id"].map(credit["on_hold"]).fillna(False).astype(bool)
    c["hold_reason"] = c["customer_id"].map(credit["hold_reason"]).fillna("")
    c["balance_ngn"] = c["customer_id"].map(credit["balance_ngn"]).fillna(0.0)
    c["daily_target_t"] = c["customer_id"].map(tgt).fillna(0.0)
    if traits is not None:
        tr = traits.set_index("customer_id")
        c["site_hours"] = c["customer_id"].map(tr["site_hours"]).astype(float)
        c["base_t"] = c["customer_id"].map(tr["base_t"]).astype(float)
        mix = tr["mix"]
        c["mix"] = c["customer_id"].map(mix)
    else:
        c["site_hours"] = 2.5 + 0.6 * (3 - c["bays"].clip(1, 4))
        c["base_t"] = c["daily_target_t"].replace(0, 30.0)
        share = np.array([p["share"] for p in brand.PRODUCTS])
        c["mix"] = [share / share.sum()] * len(c)
    c["speed_factor"] = c["region"].map(REGION_SPEED).fillna(1.0)
    c = c.reset_index(drop=True)

    pts = pd.DataFrame(brand.POINTS)
    trucks = frames["trucks"].reset_index(drop=True)
    trans = {t["name"]: t for t in brand.TRANSPORTERS}

    w = World(customers=c, points=pts, trucks=trucks, transporters=trans)
    w.cust_index = {cid: i for i, cid in enumerate(c["customer_id"])}
    w.point_index = {code: i for i, code in enumerate(pts["code"])}
    w.dist_cp = haversine_km(c["lat"].to_numpy()[:, None], c["lon"].to_numpy()[:, None],
                             pts["lat"].to_numpy()[None, :], pts["lon"].to_numpy()[None, :])
    w.dist_cc = haversine_km(c["lat"].to_numpy()[:, None], c["lon"].to_numpy()[:, None],
                             c["lat"].to_numpy()[None, :], c["lon"].to_numpy()[None, :])
    # Which customers each point serves: its own customers first, then others
    # within reach, weighted by demand and nearness.
    nearest = w.dist_cp.argmin(axis=1)
    for j, code in enumerate(pts["code"]):
        d = w.dist_cp[:, j]
        mine = nearest == j
        reach = d < (520 if pts.loc[j, "type"] == "Works" else 260)
        idx = np.where(mine | reach)[0]
        if len(idx) == 0:
            idx = np.argsort(d)[:10]
        wgt = c.loc[idx, "base_t"].to_numpy() * np.where(mine[idx], 3.0, 1.0) / (1 + d[idx] / 120)
        w.candidates[code] = (idx, wgt / wgt.sum())
    return w
