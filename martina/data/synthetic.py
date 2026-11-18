"""Synthetic data for Martina Cement Plc.

Generates a believable order book, lift history, 18 months of demand,
targets, credit status, a truck fleet and alert recipients. Every name and
number is invented. The same seed and anchor date always give the same data.

Demand follows a dry-season peak (November to March), a rainy-season dip
(June to September), a year-end push, weekday effects and slow growth.
Customers differ in size, product mix and how reliably they lift what
they order, which is what gives the Action List and FIFO Watch something
real to find.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .. import brand
from ..config import SETTINGS
from ..geo import STATE_REGION, TOWNS, km

HISTORY_DAYS = 540          # demand history for the forecast
DETAIL_DAYS = 120           # order and lift detail kept for the book

SURNAMES = ["Adeyemi", "Okafor", "Bello", "Eze", "Ibrahim", "Ogunleye", "Nwosu",
            "Abubakar", "Okon", "Balogun", "Chukwu", "Danladi", "Effiong",
            "Fashola", "Garba", "Haruna", "Ikenna", "Jimoh", "Kalu", "Lawal",
            "Musa", "Nnamdi", "Obi", "Popoola", "Quadri", "Sani", "Tijani",
            "Udoh", "Yakubu", "Zubair", "Akande", "Onyeka", "Babatunde", "Etim",
            "Olawale", "Ugwu", "Adamu", "Ekwueme", "Oyelaran", "Mohammed"]
BIZ = ["Building Supplies", "Blocks & Sons", "Cement Mart", "Building Materials",
       "Trading Co", "Enterprises", "Hardware", "Ventures", "Block Industries",
       "Depot Stores"]
PROJECT_A = ["Bluecrest", "Ironwood", "Sunridge", "Oakfield", "Palmgrove",
             "Riverstone", "Kingsbridge", "Northgate", "Clearwater", "Highpoint",
             "Stonebay", "Redwood", "Lakeside", "Brightfield", "Cedarline"]
PROJECT_B = ["Construction Ltd", "Estates Ltd", "Infrastructure Ltd",
             "Builders Ltd", "Developments Ltd", "Engineering Ltd"]
REP_FIRST = ["Amaka", "Tunde", "Halima", "Chidi", "Funmi", "Yusuf", "Ngozi",
             "Segun", "Aisha", "Emeka", "Kemi", "Ibrahim", "Bisi", "Uche"]
REP_LAST = ["Adebayo", "Nwachukwu", "Sule", "Okoro", "Alabi", "Garba", "Eze",
            "Ogundipe", "Bello", "Obi", "Afolabi", "Danjuma", "Ajayi", "Umeh"]

CHANNEL_MIX = {"Distributor": 0.45, "Retail": 0.40, "Project": 0.15}
CHANNEL_BASE = {"Distributor": (math.log(70), 0.55, 15, 320),
                "Retail": (math.log(16), 0.5, 3, 60),
                "Project": (math.log(45), 0.8, 8, 400)}
# A contract covers this many days of the customer's usual demand (low, high).
CONTRACT_DAYS = {"Distributor": (3.0, 10.0), "Retail": (3.0, 9.0), "Project": (8.0, 22.0)}


def _season(d: pd.DatetimeIndex) -> np.ndarray:
    """Multiplier by day of year: dry season high, rainy season low."""
    doy = d.dayofyear.to_numpy()
    s = 1.0 + 0.22 * np.cos(2 * np.pi * (doy - 15) / 365.25)          # peak mid-January
    s += 0.10 * np.exp(-((doy - 340) / 12.0) ** 2)                    # December push
    wk = d.dayofweek.to_numpy()
    s *= np.select([wk == 5, wk == 6], [0.72, 0.35], 1.0)             # Saturday, Sunday
    return s


def _anchor(now: datetime | None) -> pd.Timestamp:
    now = now or datetime.now()
    return pd.Timestamp(now).floor("h")


def _nearest_point(lat, lon, product=None, works_only=False):
    best, best_d = None, 1e9
    for p in brand.POINTS:
        if works_only and p["type"] != "Works":
            continue
        if product and product not in p["products"]:
            continue
        d = km(lat, lon, p["lat"], p["lon"])
        if d < best_d:
            best, best_d = p, d
    return best["code"], best_d


def make_customers(rng, n=260):
    towns = np.array([t[0] for t in TOWNS])
    w = np.array([t[4] for t in TOWNS], float)
    w /= w.sum()
    idx = rng.choice(len(TOWNS), size=n, p=w)
    channels = rng.choice(list(CHANNEL_MIX), size=n, p=list(CHANNEL_MIX.values()))
    reps = {}
    used = set()
    rows = []
    for i in range(n):
        town, state, lat, lon, _ = TOWNS[idx[i]]
        region = STATE_REGION[state]
        ch = channels[i]
        for _try in range(20):
            if ch == "Project":
                name = f"{rng.choice(PROJECT_A)} {rng.choice(PROJECT_B)}"
            elif rng.random() < 0.3:
                name = f"{town} {rng.choice(BIZ)}"
            else:
                name = f"{rng.choice(SURNAMES)} {rng.choice(BIZ)}"
            if name not in used:
                break
            name = f"{name} {i}"
        used.add(name)
        if region not in reps:
            k = 2 if region in ("North East", "South East") else 3
            reps[region] = [f"{rng.choice(REP_FIRST)} {rng.choice(REP_LAST)}" for _ in range(k)]
        rep = reps[region][i % len(reps[region])]
        jlat, jlon = lat + rng.normal(0, 0.035), lon + rng.normal(0, 0.035)
        point, _ = _nearest_point(jlat, jlon)
        opens = int(rng.choice([7, 7, 8])) if ch != "Project" else int(rng.choice([6, 7]))
        closes = int(rng.choice([17, 18, 18])) if ch != "Project" else int(rng.choice([18, 19]))
        rows.append({
            "customer_id": f"C{i + 1:04d}", "customer_name": name.upper(),
            "channel": ch, "region": region, "state": state, "town": town,
            "lat": round(jlat, 5), "lon": round(jlon, 5), "sales_rep": rep,
            "sales_rep_email": rep.lower().replace(" ", ".") + "@" + brand.COMPANY["email_domain"],
            "serving_point": point, "receive_open": opens, "receive_close": closes,
            "bays": int(rng.choice([1, 1, 2, 2, 3, 4])) if ch != "Retail" else int(rng.choice([1, 1, 2])),
        })
    return pd.DataFrame(rows)


def make_traits(rng, customers):
    """Hidden behaviour per customer, used to generate data, never shown."""
    n = len(customers)
    base = np.empty(n)
    for ch, (mu, sd, lo, hi) in CHANNEL_BASE.items():
        m = (customers["channel"] == ch).to_numpy()
        base[m] = np.clip(rng.lognormal(mu, sd, m.sum()), lo, hi)
    reliability = np.clip(rng.beta(3.2, 1.6, n), 0.08, 0.99)
    shares = np.array([p["share"] for p in brand.PRODUCTS])
    mixes = rng.dirichlet(shares * 25, n)
    site_hours = np.clip(rng.lognormal(math.log(3.2), 0.5, n), 0.8, 14)
    return pd.DataFrame({"customer_id": customers["customer_id"], "base_t": base,
                         "reliability": reliability, "site_hours": site_hours,
                         "mix": list(mixes)})


def make_contract_stream(rng, customers, traits, anchor):
    """Every contract over the full history, as arrays (fast)."""
    days = pd.date_range(anchor.normalize() - pd.Timedelta(days=HISTORY_DAYS - 1),
                         anchor.normalize(), freq="D")
    season = _season(days)
    years = (days - days[0]).days.to_numpy() / 365.25
    trend = 1.0 + 0.06 * years
    products = np.array(brand.PRODUCT_NAMES)
    out = []
    for i, c in customers.iterrows():
        t = traits.iloc[i]
        lo, hi = CONTRACT_DAYS[c["channel"]]
        mean_size = max(30.0, t["base_t"] * (lo + hi) / 2)
        lam = t["base_t"] * season * trend * rng.lognormal(0, 0.18, len(days)) / mean_size
        counts = rng.poisson(lam)
        k = counts.sum()
        if k == 0:
            continue
        day_idx = np.repeat(np.arange(len(days)), counts)
        size = np.maximum(30.0, np.round(t["base_t"] * rng.uniform(lo, hi, k) / 30.0) * 30.0)
        prod = rng.choice(products, size=k, p=t["mix"])
        hour = rng.integers(7, 19, size=k)
        minute = rng.integers(0, 60, size=k)
        created = days[day_idx] + pd.to_timedelta(hour, "h") + pd.to_timedelta(minute, "m")
        out.append(pd.DataFrame({"customer_id": c["customer_id"], "created_at": created,
                                 "qty_t": size, "product": prod}))
    df = pd.concat(out, ignore_index=True)
    df = df[df["created_at"] <= anchor].sort_values("created_at", ignore_index=True)
    return df


def _work_time(rng, t, mean_days):
    """t plus an exponential delay, moved into 06:00 to 20:00."""
    t = t + pd.Timedelta(days=float(rng.exponential(mean_days)))
    if t.hour < 6:
        t = t.normalize() + pd.Timedelta(hours=6, minutes=int(rng.integers(0, 120)))
    elif t.hour >= 20:
        t = t.normalize() + pd.Timedelta(days=1, hours=6, minutes=int(rng.integers(0, 120)))
    return t


def make_book(rng, customers, traits, stream, anchor):
    """Contracts, releases and lifts for the detail window."""
    cut = anchor - pd.Timedelta(days=DETAIL_DAYS)
    recent = stream[stream["created_at"] >= cut].reset_index(drop=True)
    cust = customers.set_index("customer_id")
    trait = traits.set_index("customer_id")
    price = {p["name"]: p["price_ngn_t"] for p in brand.PRODUCTS}
    orders, lifts = [], []
    n_rel = n_lift = 0
    p_del = customers["channel"].map({"Distributor": .7, "Retail": .55, "Project": .9}).to_numpy()
    terms_pref = dict(zip(customers["customer_id"],
                          np.where(rng.random(len(customers)) < p_del, "DEL", "COL")))
    for k, row in enumerate(recent.itertuples(index=False)):
        c = cust.loc[row.customer_id]
        r = float(trait.at[row.customer_id, "reliability"])
        pref = terms_pref[row.customer_id]
        terms = pref if rng.random() < 0.92 else ("COL" if pref == "DEL" else "DEL")
        point = c["serving_point"]
        p_obj = next(p for p in brand.POINTS if p["code"] == point)
        if row.product not in p_obj["products"]:
            point, _ = _nearest_point(c["lat"], c["lon"], row.product)
        unit_price = round(price[row.product] * (1 + rng.normal(0, 0.015)), -2)
        cid = f"CON-{k + 1:06d}"
        qty = float(row.qty_t)
        released = 0.0
        t = _work_time(rng, row.created_at, 0.6 if c["channel"] != "Project" else 1.5)
        rel_rows = []
        while released < qty and t <= anchor:
            day_t = float(trait.at[row.customer_id, "base_t"]) * rng.uniform(0.8, 1.6)
            chunk = float(min(qty - released, max(30.0, round(day_t / 30.0) * 30.0)))
            n_rel += 1
            rid = f"REL-{n_rel:06d}"
            lifted, last_lift = 0.0, pd.NaT
            lt = _work_time(rng, t, 0.35 / max(r, 0.2))
            while lifted < chunk and lt <= anchor:
                load = float(min(chunk - lifted, 30.0 if rng.random() < .7 else 40.0))
                n_lift += 1
                lifts.append((f"LFT-{n_lift:07d}", rid, row.customer_id, row.product,
                              point, load, lt))
                lifted += load
                last_lift = lt
                gap = float(rng.exponential(6.0)) if rng.random() < 0.12 * (1 - r) else 0.25
                lt = _work_time(rng, lt, gap)
            status = "CLOSED" if lifted >= chunk else ("PARTIAL" if lifted > 0 else "OPEN")
            rel_rows.append({
                "order_id": rid, "level": "release", "contract_id": cid,
                "customer_id": row.customer_id, "product": row.product, "terms": terms,
                "point_code": point, "qty_t": chunk, "done_t": lifted,
                "price_ngn_t": unit_price, "created_at": t,
                "required_by": t + pd.Timedelta(days=3),
                "closed_at": last_lift if status == "CLOSED" else pd.NaT, "status": status})
            released += chunk
            if rng.random() < 0.5 * (1 - r):         # the customer pauses releasing
                t = _work_time(rng, t, 12.0)
            else:
                t = _work_time(rng, t, 0.9 / max(r, 0.25))
        cstatus = "CLOSED" if released >= qty else ("PARTIAL" if released > 0 else "OPEN")
        orders.append({
            "order_id": cid, "level": "contract", "contract_id": "",
            "customer_id": row.customer_id, "product": row.product, "terms": terms,
            "point_code": point, "qty_t": qty, "done_t": released,
            "price_ngn_t": unit_price, "created_at": row.created_at,
            "required_by": row.created_at + pd.Timedelta(days=14),
            "closed_at": (rel_rows[-1]["created_at"] if cstatus == "CLOSED" and rel_rows else pd.NaT),
            "status": cstatus})
        orders.extend(rel_rows)
    orders = pd.DataFrame(orders)
    lifts = pd.DataFrame(lifts, columns=["lift_id", "release_id", "customer_id", "product",
                                         "point_code", "qty_t", "lifted_at"])
    return orders, lifts


def make_targets(customers, traits):
    t = traits["base_t"].to_numpy() * 0.8
    t = np.where(customers["channel"].to_numpy() == "Project", 0.0, np.round(t / 5) * 5)
    return pd.DataFrame({"customer_id": customers["customer_id"], "daily_target_t": t})


def make_credit(rng, customers, traits):
    price = 175000
    limit = np.round(traits["base_t"].to_numpy() * 10 * price, -5)
    used = limit * np.clip(rng.beta(2.2, 2.0, len(customers)), 0, 1.15)
    balance = np.round(limit - used, -4)        # funds available against the limit
    hold = rng.random(len(customers)) < 0.07
    reasons = rng.choice(["Overdue invoice", "Credit limit exceeded",
                          "Account documents pending"], size=len(customers))
    return pd.DataFrame({"customer_id": customers["customer_id"], "credit_limit_ngn": limit,
                         "balance_ngn": balance, "on_hold": hold,
                         "hold_reason": np.where(hold, reasons, "")})


def make_trucks(rng, n):
    codes = [t["code"] for t in brand.TRANSPORTERS]
    names = {t["code"]: t["name"] for t in brand.TRANSPORTERS}
    share = np.array([t["share"] for t in brand.TRANSPORTERS])
    pick = rng.choice(codes, size=n, p=share / share.sum())
    homes = [p["code"] for p in brand.POINTS]
    home_w = np.array([p["cap_tpd"] for p in brand.POINTS], float)
    home = rng.choice(homes, size=n, p=home_w / home_w.sum())
    body = rng.choice(["Bag", "Bag", "Bag", "Bulk"], size=n)
    rows, count = [], {}
    letters = "ABCDEFGHJKLMNPRSTUVWXYZ"
    for i in range(n):
        count[pick[i]] = count.get(pick[i], 0) + 1
        rows.append({
            "truck_id": f"{pick[i]}-{count[pick[i]]:03d}",
            "plate": f"{rng.choice(list(letters))}{rng.choice(list(letters))}"
                     f"{rng.integers(100, 999)}-{rng.choice(list(letters))}{rng.choice(list(letters))}",
            "transporter": names[pick[i]],
            "capacity_t": 30.0 if body[i] == "Bulk" else float(rng.choice([30, 30, 40])),
            "body": body[i], "home_point": home[i]})
    return pd.DataFrame(rows)


def make_recipients(customers):
    dom = brand.COMPANY["email_domain"]
    rows = [{"name": "Dispatch Desk", "email": f"dispatch@{dom}", "role": "dispatch",
             "region": "", "point_code": ""},
            {"name": "Fleet Compliance", "email": f"fleet@{dom}", "role": "fleet",
             "region": "", "point_code": ""},
            {"name": "Credit Control", "email": f"credit@{dom}", "role": "credit",
             "region": "", "point_code": ""},
            {"name": "Customer Service", "email": f"service@{dom}", "role": "customer",
             "region": "", "point_code": ""}]
    reps = customers[["sales_rep", "sales_rep_email", "region"]].drop_duplicates()
    for r in reps.itertuples(index=False):
        rows.append({"name": r.sales_rep, "email": r.sales_rep_email, "role": "sales",
                     "region": r.region, "point_code": ""})
    for p in brand.POINTS:
        rows.append({"name": f"{p['name']} Supervisor",
                     "email": f"{p['code'].lower()}.supervisor@{dom}", "role": "point",
                     "region": "", "point_code": p["code"]})
    return pd.DataFrame(rows)


def generate(seed: int | None = None, now: datetime | None = None, n_customers=260,
             fleet_size: int | None = None):
    """Build every table. Returns (frames, traits)."""
    seed = SETTINGS.seed if seed is None else seed
    rng = np.random.default_rng(seed)
    anchor = _anchor(now)
    customers = make_customers(rng, n_customers)
    traits = make_traits(rng, customers)
    stream = make_contract_stream(rng, customers, traits, anchor)
    orders, lifts = make_book(rng, customers, traits, stream, anchor)
    demand = (stream.assign(date=stream["created_at"].dt.normalize())
              .groupby(["date", "customer_id", "product"], as_index=False)["qty_t"].sum())
    frames = {
        "customers": customers,
        "orders": orders,
        "lifts": lifts,
        "demand_daily": demand,
        "targets": make_targets(customers, traits),
        "credit": make_credit(rng, customers, traits),
        "trucks": make_trucks(rng, fleet_size or SETTINGS.fleet_size),
        "recipients": make_recipients(customers),
    }
    return frames, traits


def write_csv(out_dir, seed=None, now=None):
    """Write every table to CSV, for anyone who wants to inspect or edit them."""
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames, _ = generate(seed, now)
    for name, df in frames.items():
        df.to_csv(out / f"{name}.csv", index=False)
    return {k: len(v) for k, v in frames.items()}
