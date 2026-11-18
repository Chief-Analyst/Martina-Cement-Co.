"""Operations views: what to release, what is stuck, who is served out of turn.

Release planning applies to Delivered (DEL) orders only: Collect customers
send their own trucks, so a daily run rate does not apply to them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..cache import cached
from ..config import RULES
from ..data.store import STORE
from .pipeline import filter_frame


def _book():
    return STORE.ensure().book


@cached("ops_summary")
def summary(f):
    op = filter_frame(_book().open, f)
    dl = op[op["terms"] == "DEL"]
    rel = op[op["level"] == "release"]
    partial = rel[(rel["status"] == "PARTIAL") & (rel["age_days"] >= RULES.partial_alert_days)]
    fifo = fifo_watch(f, RULES.fifo_wait_days, "all")
    return {
        "del_queue_t": float(dl.loc[dl["level"] == "release", "open_t"].sum()),
        "del_contract_t": float(dl.loc[dl["level"] == "contract", "open_t"].sum()),
        "partial_aged_n": int(len(partial)),
        "partial_aged_t": float(partial["open_t"].sum()),
        "fifo_customers": int(fifo.loc[fifo["priority"] == "HIGH", "customer_id"].nunique()) if len(fifo) else 0,
    }


@cached("release_planning")
def release_planning(f, horizon):
    """Per customer: delivered tonnage in the queue against the run rate."""
    b = _book()
    op = filter_frame(b.open, f)
    dl = op[op["terms"] == "DEL"]
    q = dl[dl["level"] == "release"].groupby("customer_id", observed=True)
    c = dl[dl["level"] == "contract"].groupby("customer_id", observed=True)
    cust = filter_frame(b.customers, f[:4] + ("", ""))
    df = cust[["customer_id", "customer_name", "channel", "region", "daily_target_t"]].copy()
    df["queue_t"] = df["customer_id"].map(q["open_t"].sum()).fillna(0.0)
    df["contract_t"] = df["customer_id"].map(c["open_t"].sum()).fillna(0.0)
    df["releases"] = df["customer_id"].map(q.size()).fillna(0).astype(int)
    df["partials"] = df["customer_id"].map(
        dl[(dl["level"] == "release") & (dl["status"] == "PARTIAL")]
        .groupby("customer_id", observed=True).size()).fillna(0).astype(int)
    df["oldest_days"] = df["customer_id"].map(q["age_days"].max()).round(0)
    df = df[(df["queue_t"] > 0) | (df["contract_t"] > 0)]
    tgt = df["daily_target_t"]
    df["queue_days"] = np.where(tgt > 0, df["queue_t"] / tgt.replace(0, np.nan), np.nan).round(2)
    need = (tgt * horizon - df["queue_t"]).clip(lower=0)
    df["to_release_t"] = np.minimum(need, df["contract_t"]).round(0)
    df["short_t"] = (need - df["contract_t"]).clip(lower=0).round(0)
    df["status"] = np.select(
        [df["channel"] == "Project", tgt <= 0, df["queue_days"] < 1, df["queue_days"] < horizon],
        ["PROJECT", "NO TARGET", "HIGH", "MEDIUM"], "HEALTHY")
    order = {"HIGH": 0, "MEDIUM": 1, "HEALTHY": 2, "NO TARGET": 3, "PROJECT": 4}
    df["_o"] = df["status"].map(order)
    df = df.sort_values(["_o", "queue_days"]).drop(columns="_o")
    return df.reset_index(drop=True)


@cached("partials")
def partial_releases(f, mode):
    op = filter_frame(_book().open, f)
    rel = op[(op["level"] == "release") & (op["status"] == "PARTIAL")].copy()
    rel["priority"] = np.where(rel["age_days"] >= RULES.partial_alert_days, "HIGH", "MEDIUM")
    if mode == "aged":
        rel = rel[rel["priority"] == "HIGH"]
    rel["lifted_pct"] = (rel["done_t"] / rel["qty_t"] * 100).round(0)
    cols = ["priority", "order_id", "contract_id", "customer_name", "region", "terms",
            "product", "point_name", "age_days", "qty_t", "done_t", "open_t", "lifted_pct"]
    out = rel.sort_values("age_days", ascending=False)[cols].copy()
    for c in ("customer_name", "region", "terms", "product", "point_name"):
        out[c] = out[c].astype(str)
    return out.reset_index(drop=True)


@cached("fifo")
def fifo_watch(f, min_days, mode):
    """Older releases still waiting while newer ones for the same customer moved."""
    b = _book()
    o = filter_frame(b.orders, f[:4] + ("", ""))
    rel = o[o["level"] == "release"]
    waiting = rel[(rel["open_t"] > 0) & (rel["age_days"] >= min_days)]
    if waiting.empty:
        return pd.DataFrame(columns=["priority", "customer_id", "customer_name"])
    oldest = (waiting.sort_values("created_at")
                     .groupby("customer_id", observed=True).head(1)
                     .set_index("customer_id"))
    newer = rel.merge(oldest[["created_at"]].rename(columns={"created_at": "oldest_at"}),
                      left_on="customer_id", right_index=True)
    newer = newer[newer["created_at"] > newer["oldest_at"]]
    agg = newer.groupby("customer_id", observed=True).agg(
        newer_n=("order_id", "size"), newer_t=("qty_t", "sum"),
        newer_lifted_t=("done_t", "sum"))
    df = oldest.join(agg, how="left").fillna({"newer_n": 0, "newer_t": 0, "newer_lifted_t": 0})
    df = df.reset_index()
    df["priority"] = np.where(df["newer_lifted_t"] > 0, "HIGH",
                              np.where(df["age_days"] >= 2 * min_days, "MEDIUM", "LOW"))
    df["action"] = df["priority"].map({
        "HIGH": "Served out of turn: load the older release next",
        "MEDIUM": "Older release waiting: confirm site and credit",
        "LOW": "Within tolerance"})
    if mode != "all":
        df = df[df["priority"] != "LOW"]
    cols = ["priority", "customer_id", "customer_name", "region", "order_id", "product",
            "point_name", "age_days", "open_t", "newer_n", "newer_t", "newer_lifted_t", "action"]
    out = df[cols].copy()
    for c in ("customer_name", "region", "product", "point_name"):
        out[c] = out[c].astype(str)
    out["newer_n"] = out["newer_n"].astype(int)
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    out["_o"] = out["priority"].map(order)
    return out.sort_values(["_o", "age_days"], ascending=[True, False]).drop(columns="_o").reset_index(drop=True)


@cached("order_book")
def order_book(f):
    op = filter_frame(_book().open, f)
    con = op[op["level"] == "contract"].groupby("customer_id", observed=True)
    rel = op[op["level"] == "release"].groupby("customer_id", observed=True)
    part = op[(op["level"] == "release") & (op["status"] == "PARTIAL")].groupby("customer_id", observed=True)
    base = op.groupby("customer_id", observed=True).agg(
        customer_name=("customer_name", "first"), channel=("channel", "first"),
        region=("region", "first"), total_open_t=("open_t", "sum"))
    base["contracts"] = con.size()
    base["contract_open_t"] = con["open_t"].sum()
    base["releases"] = rel.size()
    base["release_open_t"] = rel["open_t"].sum()
    base["partials"] = part.size()
    base = base.fillna(0)
    for c in ("contracts", "releases", "partials"):
        base[c] = base[c].astype(int)
    for c in ("customer_name", "channel", "region"):
        base[c] = base[c].astype(str)
    cols = ["customer_name", "channel", "region", "contracts", "contract_open_t", "releases",
            "release_open_t", "partials", "total_open_t"]
    return base.reset_index()[["customer_id"] + cols].sort_values("total_open_t", ascending=False).reset_index(drop=True)


@cached("points")
def shipping_points(f, kind):
    op = filter_frame(_book().open, f)
    if kind in ("Works", "Depot"):
        op = op[op["point_type"] == kind]
    g = op.groupby(["point_code", "point_name", "point_type"], observed=True)
    df = g.agg(open_t=("open_t", "sum"), customers=("customer_id", "nunique"),
               orders=("order_id", "size")).reset_index()
    dl = op[op["terms"] == "DEL"].groupby("point_code", observed=True)["open_t"].sum()
    df["delivered_t"] = df["point_code"].map(dl).fillna(0)
    df["collect_t"] = df["open_t"] - df["delivered_t"]
    tot = df["open_t"].sum()
    df["share_pct"] = (df["open_t"] / tot * 100).round(1) if tot else 0
    df["point_name"] = df["point_name"].astype(str)
    return df.sort_values("open_t", ascending=False).reset_index(drop=True)
