"""Order book views behind Executive Summary and Analytics.

Every function takes the normalised sidebar filters (pipeline.norm_filters)
and returns plain DataFrames or dicts, cached until the next refresh.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import brand
from ..cache import cached
from ..config import RULES
from ..data.store import STORE
from .pipeline import filter_frame, period


def _book():
    return STORE.ensure().book


@cached("kpis")
def kpis(f):
    b = _book()
    start, end = period(b, f)
    o = filter_frame(b.orders, f)
    created = o[(o["level"] == "contract") & (o["created_at"] >= start) & (o["created_at"] < end)]
    lifts = filter_frame(b.lifts, f[:4] + ("", ""))
    lifted = lifts[(lifts["lifted_at"] >= start) & (lifts["lifted_at"] < end)]
    op = o[o["open_t"] > 0]
    ordered_t = float(created["qty_t"].sum())
    lifted_t = float(lifted["qty_t"].sum())
    mortar = op["family"].astype(str) == "Mortar"
    return {
        "period_start": start, "period_end": end,
        "ordered_t": ordered_t, "lifted_t": lifted_t,
        "fill_rate": lifted_t / ordered_t if ordered_t else 0.0,
        "open_t": float(op["open_t"].sum()),
        "open_cement_t": float(op.loc[~mortar, "open_t"].sum()),
        "open_mortar_t": float(op.loc[mortar, "open_t"].sum()),
        "open_contract_t": float(op.loc[op["level"] == "contract", "open_t"].sum()),
        "open_release_t": float(op.loc[op["level"] == "release", "open_t"].sum()),
        "open_value_ngn": float(op["open_value_ngn"].sum()),
        "customers_open": int(op["customer_id"].nunique()),
        "products_open": int(op["product"].astype(str).nunique()),
    }


@cached("backlog_by")
def backlog_by(f, dim):
    op = filter_frame(_book().open, f)
    g = op.groupby(dim, observed=True)["open_t"].sum().sort_values(ascending=False)
    g = g[g > 0]
    df = g.reset_index()
    df[dim] = df[dim].astype(str)
    if dim == "region":
        order = {r: i for i, r in enumerate(brand.REGIONS)}
        df = df.sort_values(dim, key=lambda s: s.map(order).fillna(99))
    return df


@cached("concentration")
def concentration(f):
    """How much of the backlog sits with the largest customers."""
    op = filter_frame(_book().open, f)
    per = (op.groupby(["customer_id", "customer_name"], observed=True)["open_t"].sum()
             .sort_values(ascending=False).reset_index())
    per = per[per["open_t"] > 0]
    total = per["open_t"].sum()
    if not total:
        return {"total": 0, "customers": 0, "top10_share": 0, "top20pct_share": 0,
                "hhi": 0, "label": "No backlog", "pareto": per}
    share = per["open_t"] / total
    n = len(per)
    top20 = max(1, int(round(n * 0.2)))
    hhi = float((share ** 2).sum() * 10000)
    label = ("Concentrated" if hhi > 1500 or share.head(10).sum() > 0.6
             else "Moderate" if share.head(10).sum() > 0.35 else "Spread")
    pareto = per.head(20).copy()
    pareto["cum_share"] = pareto["open_t"].cumsum() / total
    pareto["customer_name"] = pareto["customer_name"].astype(str)
    return {"total": float(total), "customers": n,
            "top10_share": float(share.head(10).sum()),
            "top20pct_share": float(share.head(top20).sum()), "top20pct_n": top20,
            "hhi": hhi, "label": label, "pareto": pareto,
            "avg_per_customer": float(total / n)}


@cached("fill_by_region")
def fill_by_region(f):
    b = _book()
    start, end = period(b, f)
    o = filter_frame(b.orders, f)
    c = o[(o["level"] == "contract") & (o["created_at"] >= start) & (o["created_at"] < end)]
    lifts = filter_frame(b.lifts, f[:4] + ("", ""))
    li = lifts[(lifts["lifted_at"] >= start) & (lifts["lifted_at"] < end)]
    a = c.groupby("region", observed=True)["qty_t"].sum().rename("ordered_t")
    d = li.groupby("region", observed=True)["qty_t"].sum().rename("lifted_t")
    df = pd.concat([a, d], axis=1).fillna(0).reset_index()
    df["region"] = df["region"].astype(str)
    df["fill_rate"] = np.where(df["ordered_t"] > 0, df["lifted_t"] / df["ordered_t"], 0.0)
    order = {r: i for i, r in enumerate(brand.REGIONS)}
    return df.sort_values("region", key=lambda s: s.map(order).fillna(99))


@cached("lift_trend")
def lift_trend(f, days=60):
    b = _book()
    lifts = filter_frame(b.lifts, f[:4] + ("", ""))
    since = b.anchor.normalize() - pd.Timedelta(days=days)
    li = lifts[lifts["lifted_at"] >= since]
    g = li.groupby(["day", "region"], observed=True)["qty_t"].sum().reset_index()
    g["region"] = g["region"].astype(str)
    return g


@cached("ageing")
def ageing(f):
    op = filter_frame(_book().open, f)
    labels = [x[2] for x in RULES.ageing_buckets]
    g = op.groupby("age_bucket", observed=True)["open_t"].sum().reindex(labels).fillna(0)
    oldest = (op.sort_values("age_days", ascending=False)
                .head(200)[["order_id", "level", "customer_name", "region", "product",
                            "point_name", "open_t", "age_days", "status"]])
    return g.reset_index().rename(columns={"index": "age_bucket"}), oldest


@cached("cover_risk")
def cover_risk(f):
    """Days of work booked per customer (all open tonnage / daily target)."""
    b = _book()
    op = filter_frame(b.open, f)
    cust = filter_frame(b.customers, f[:4] + ("", ""))
    dl = op[op["terms"] == "DEL"].groupby("customer_id", observed=True)["open_t"].sum()
    allo = op.groupby("customer_id", observed=True)["open_t"].sum()
    df = cust[["customer_id", "customer_name", "channel", "region", "daily_target_t",
               "sales_rep"]].copy()
    df["open_t"] = df["customer_id"].map(allo).fillna(0.0)
    df["delivered_open_t"] = df["customer_id"].map(dl).fillna(0.0)
    tgt = df["daily_target_t"]
    df["cover_days"] = np.where(tgt > 0, df["open_t"] / tgt.replace(0, np.nan), np.nan)
    band = np.select(
        [df["channel"] == "Project", tgt <= 0,
         df["cover_days"] < RULES.cover_critical_days,
         df["cover_days"] < RULES.cover_watch_days],
        ["PROJECT", "NO TARGET", "CRITICAL", "WATCH"], "HEALTHY")
    df["band"] = band
    action = {
        "CRITICAL": "Call today: under {:.2g} days of orders booked".format(RULES.cover_critical_days),
        "WATCH": "Follow up this week: cover is thinning",
        "HEALTHY": "Well covered",
        "NO TARGET": "Set a daily target to track cover",
        "PROJECT": "Project account: planned by contract, no run rate",
    }
    df["action"] = df["band"].map(action)
    df["cover_days"] = df["cover_days"].round(2)
    order = {"CRITICAL": 0, "WATCH": 1, "HEALTHY": 2, "NO TARGET": 3, "PROJECT": 4}
    df = df.sort_values(["band", "cover_days"], key=lambda s: s.map(order) if s.name == "band" else s)
    return df.reset_index(drop=True)


@cached("behaviour")
def behaviour(f, days=30):
    """How much of what each customer ordered they actually lifted."""
    b = _book()
    since = b.anchor - pd.Timedelta(days=days)
    o = filter_frame(b.orders, f[:4] + ("", ""))
    c = o[(o["level"] == "contract") & (o["created_at"] >= since)]
    li = filter_frame(b.lifts, f[:4] + ("", ""))
    li = li[li["lifted_at"] >= since]
    a = c.groupby(["customer_id", "customer_name"], observed=True)["qty_t"].sum().rename("ordered_t")
    d = li.groupby(["customer_id", "customer_name"], observed=True)["qty_t"].sum().rename("lifted_t")
    df = pd.concat([a, d], axis=1).fillna(0).reset_index()
    df = df[df["ordered_t"] > 0]
    df["customer_name"] = df["customer_name"].astype(str)
    df["ratio"] = (df["lifted_t"] / df["ordered_t"]).clip(upper=1.5).round(3)
    df["band"] = np.select([df["ratio"] < RULES.behaviour_poor, df["ratio"] < RULES.behaviour_fair],
                           ["POOR", "FAIR"], "GOOD")
    df["action"] = df["band"].map({
        "POOR": "Orders far ahead of lifting: check credit and site readiness",
        "FAIR": "Lifting unevenly: monitor",
        "GOOD": "Lifting reliably"})
    return df.sort_values("ratio").reset_index(drop=True)


EXPLORER_COLS = ["order_id", "level", "contract_id", "customer_name", "channel", "region",
                 "state", "product", "terms", "point_name", "qty_t", "done_t", "open_t",
                 "price_ngn_t", "open_value_ngn", "created_at", "age_days", "status"]


@cached("explorer")
def explorer(f, status, search):
    b = _book()
    o = filter_frame(b.orders, f, "created_at")
    if status == "open":
        o = o[o["open_t"] > 0]
    elif status:
        o = o[o["status"] == status]
    if search:
        s = search.strip().upper()
        m = (o["order_id"].str.contains(s, regex=False) |
             o["contract_id"].str.contains(s, regex=False) |
             o["customer_name"].astype(str).str.contains(s, regex=False))
        o = o[m]
    out = o[EXPLORER_COLS].sort_values("created_at", ascending=False).copy()
    for c in ("customer_name", "channel", "region", "state", "product", "terms",
              "point_name", "level", "status"):
        out[c] = out[c].astype(str)
    out["created_at"] = out["created_at"].dt.strftime("%Y-%m-%d %H:%M")
    return out.reset_index(drop=True)
