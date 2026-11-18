"""Turns the raw tables into the order book every page reads.

Built once per data refresh. Pages then filter and aggregate these frames,
which are small enough (tens of thousands of rows) to do in milliseconds.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import brand
from ..config import RULES

POINT_NAMES = {p["code"]: p["name"] for p in brand.POINTS}
POINT_TYPES = {p["code"]: p["type"] for p in brand.POINTS}
FAMILY = {p["name"]: p["family"] for p in brand.PRODUCTS}


@dataclass
class Book:
    anchor: pd.Timestamp
    orders: pd.DataFrame          # every order, enriched
    open: pd.DataFrame            # orders with tonnage still open
    lifts: pd.DataFrame           # lift history, enriched
    customers: pd.DataFrame       # master + target + credit
    demand: pd.DataFrame          # daily demand history, enriched


def age_bucket(days: pd.Series) -> pd.Series:
    labels = [b[2] for b in RULES.ageing_buckets]
    bins = [-1] + [b[1] for b in RULES.ageing_buckets]
    return pd.cut(days, bins=bins, labels=labels).astype(str)


def build_book(frames) -> Book:
    cust = frames["customers"].copy()
    cust = cust.merge(frames["targets"], on="customer_id", how="left")
    cust = cust.merge(frames["credit"], on="customer_id", how="left")
    cust["daily_target_t"] = cust["daily_target_t"].fillna(0.0)
    cust["on_hold"] = cust["on_hold"].fillna(False).astype(bool)
    cust["serving_point_name"] = cust["serving_point"].map(POINT_NAMES).fillna(cust["serving_point"])

    o = frames["orders"].copy()
    anchor = pd.Timestamp(max(o["created_at"].max(), frames["lifts"]["lifted_at"].max())).ceil("h")
    keep = ["customer_id", "customer_name", "channel", "region", "state", "town",
            "sales_rep", "daily_target_t"]
    o = o.merge(cust[keep], on="customer_id", how="left")
    o["open_t"] = (o["qty_t"] - o["done_t"]).clip(lower=0)
    o.loc[o["status"].isin(["CLOSED", "CANCELLED"]), "open_t"] = 0.0
    o["open_value_ngn"] = o["open_t"] * o["price_ngn_t"]
    o["age_days"] = (anchor - o["created_at"]).dt.total_seconds() / 86400.0
    o["age_days"] = o["age_days"].clip(lower=0).round(1)
    o["age_bucket"] = age_bucket(o["age_days"])
    o["family"] = o["product"].map(FAMILY).fillna("Cement")
    o["point_name"] = o["point_code"].map(POINT_NAMES).fillna(o["point_code"])
    o["point_type"] = o["point_code"].map(POINT_TYPES).fillna("")
    o["terms_label"] = o["terms"].map({"DEL": "Delivered", "COL": "Collect"}).fillna(o["terms"])
    for c in ("customer_name", "channel", "region", "state", "product", "level",
              "status", "terms", "point_name", "family", "age_bucket"):
        o[c] = o[c].astype("category")

    lifts = frames["lifts"].merge(cust[["customer_id", "customer_name", "region", "channel"]],
                                  on="customer_id", how="left")
    lifts["day"] = lifts["lifted_at"].dt.normalize()

    demand = frames["demand_daily"].merge(cust[["customer_id", "customer_name", "region", "channel"]],
                                          on="customer_id", how="left")

    open_ = o[o["open_t"] > 0].copy()
    return Book(anchor=anchor, orders=o, open=open_, lifts=lifts, customers=cust,
                demand=demand)


# ---------------------------------------------------------------------------
# Filters shared by every order book page
# ---------------------------------------------------------------------------
def norm_filters(f: dict | None) -> tuple:
    """A hashable form of the sidebar filters (for caches)."""
    f = f or {}
    def t(v):
        if not v:
            return ()
        return tuple(sorted(v)) if isinstance(v, (list, tuple)) else (v,)
    return (t(f.get("region")), t(f.get("channel")), t(f.get("product")),
            t(f.get("customer")), f.get("start") or "", f.get("end") or "")


def filter_frame(df: pd.DataFrame, f: tuple, date_col: str | None = None) -> pd.DataFrame:
    region, channel, product, customer, start, end = f
    m = np.ones(len(df), bool)
    if region and "region" in df:
        m &= df["region"].isin(region).to_numpy()
    if channel and "channel" in df:
        m &= df["channel"].isin(channel).to_numpy()
    if product and "product" in df:
        m &= df["product"].isin(product).to_numpy()
    if customer and "customer_id" in df:
        m &= df["customer_id"].isin(customer).to_numpy()
    if date_col and (start or end):
        d = df[date_col]
        if start:
            m &= (d >= pd.Timestamp(start)).to_numpy()
        if end:
            m &= (d < pd.Timestamp(end) + pd.Timedelta(days=1)).to_numpy()
    return df[m] if not m.all() else df


def period(book: Book, f: tuple, default_days=30):
    """The flow period: the sidebar dates, or the last `default_days`."""
    start, end = f[4], f[5]
    end_ts = pd.Timestamp(end) + pd.Timedelta(days=1) if end else book.anchor
    start_ts = pd.Timestamp(start) if start else end_ts.normalize() - pd.Timedelta(days=default_days)
    return start_ts, end_ts
