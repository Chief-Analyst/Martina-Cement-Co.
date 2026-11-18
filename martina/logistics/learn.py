"""Learning from finished trips.

Four models, each with a plain rule it has to beat before it is trusted:

delay risk   chance a truck sent now stays past the reroute trigger
             rule: the customer's own past rate of long stays
site time    hours on site (receiving window only)
             rule: the customer's average
arrival      driving minutes to the customer
             rule: distance at the nominal speed
back at base driving minutes from the customer back to base
             rule: distance at the nominal speed

Every feature is something known at the moment of dispatch. Each model is
tested on the newest quarter of trips it never trained on; it takes over
from its rule only if it is more accurate there.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict

import numpy as np
import pandas as pd

from ..config import RULES
from . import clock as C

MODELS = {
    "risk": {"title": "Delay risk (past the trigger)", "unit": "", "kind": "clf"},
    "site": {"title": "Time on site", "unit": "h", "kind": "reg"},
    "eta": {"title": "Arrival time", "unit": "min", "kind": "reg"},
    "back": {"title": "Back at base", "unit": "min", "kind": "reg"},
}
FEATURES = ["cust_site_h", "cust_long_rate", "cust_trips", "bays", "arr_hour", "close_gap_h",
            "at_site", "heading", "dist_km", "return_km", "region", "channel", "dow", "dep_hour",
            "transporter", "queue_at_load"]
FEATURE_LABELS = {
    "cust_site_h": "Customer's usual time on site", "cust_long_rate": "Customer's share of long stays",
    "cust_trips": "Trips seen at the customer", "bays": "Offloading bays", "arr_hour": "Hour of arrival",
    "close_gap_h": "Hours before the site closes", "at_site": "Trucks already on site",
    "heading": "Trucks already heading there", "dist_km": "Distance", "return_km": "Distance back",
    "region": "Region", "channel": "Channel", "dow": "Day of week", "dep_hour": "Hour of departure",
    "transporter": "Transporter", "queue_at_load": "Queue at loading"}
CATS = ["region", "channel", "transporter"]


class CustomerStats:
    """Running history per customer, updated in time order."""

    def __init__(self, prior_h=3.5, prior_rate=0.08, k=5):
        self.sum = defaultdict(float)
        self.n = defaultdict(int)
        self.long = defaultdict(int)
        self.prior_h, self.prior_rate, self.k = prior_h, prior_rate, k

    def add(self, ci, hours):
        self.sum[ci] += hours
        self.n[ci] += 1
        self.long[ci] += hours >= RULES.site_reroute_hours

    def mean_h(self, ci):
        return (self.sum[ci] + self.prior_h * self.k) / (self.n[ci] + self.k)

    def long_rate(self, ci):
        return (self.long[ci] + self.prior_rate * self.k) / (self.n[ci] + self.k)


class Learner:
    def __init__(self, sim):
        self.sim = sim
        self.w = sim.w
        self.lock = threading.Lock()
        self.models = {}
        self.resid_q90 = {}
        self.in_charge = {k: False for k in MODELS}
        self.report = None
        self.stats = CustomerStats()
        self.codes = {c: {} for c in CATS}
        self.records = []           # prediction records for model health
        self.trained_at = None
        self.trained_sim_t = None
        self.status = "not trained"

    # -- features -------------------------------------------------------
    def _code(self, cat, v):
        d = self.codes[cat]
        if v not in d:
            d[v] = len(d)
        return d[v]

    def features(self, trip, stats: CustomerStats, at_site=0, heading=0):
        c = self.w.customers.iloc[trip.cust]
        plan_arr = C.drive(trip.t_gate_out, trip.plan_travel_min)
        mod = C.minute_of_day(plan_arr) / 60.0
        return {
            "cust_site_h": stats.mean_h(trip.cust), "cust_long_rate": stats.long_rate(trip.cust),
            "cust_trips": stats.n[trip.cust], "bays": int(c.bays), "arr_hour": mod,
            "close_gap_h": (c.receive_close - mod) if c.receive_open <= mod < c.receive_close else -1.0,
            "at_site": at_site, "heading": heading, "dist_km": trip.dist_km,
            "return_km": float(self.w.dist_cp[trip.cust, self.w.point_index[trip.origin]]) * RULES.road_factor,
            "region": self._code("region", c.region), "channel": self._code("channel", c.channel),
            "dow": int((trip.t_gate_out // C.DAY) % 7), "dep_hour": C.minute_of_day(trip.t_gate_out) / 60.0,
            "transporter": self._code("transporter", trip.transporter), "queue_at_load": trip.queue_at_load,
        }

    def _table(self, trips):
        """Training rows in dispatch order, with customer history as it was then."""
        trips = sorted(trips, key=lambda t: t.t_gate_out)
        stats = CustomerStats()
        done = []                         # (t_offloaded, cust, hours) waiting to enter the stats
        rows = []
        active = defaultdict(list)        # cust -> [(t_arrive, t_depart, t_gate_out)]
        for tr in trips:
            while done and done[0][0] <= tr.t_gate_out:
                _, ci, h = done.pop(0)
                stats.add(ci, h)
            iv = active[tr.cust]
            at_site = sum(1 for a, b, g in iv if a <= tr.t_gate_out < b)
            heading = sum(1 for a, b, g in iv if g <= tr.t_gate_out < a)
            f = self.features(tr, stats, at_site, heading)
            f.update(y_risk=float(tr.site_hours >= RULES.site_reroute_hours), y_site=tr.site_hours,
                     y_eta=tr.travel_min, y_back=tr.return_min, t=tr.t_gate_out,
                     rule_risk=stats.long_rate(tr.cust), rule_site=stats.mean_h(tr.cust),
                     rule_eta=tr.plan_travel_min,
                     rule_back=f["return_km"] / RULES.truck_speed_kmh * 60.0)
            rows.append(f)
            iv.append((tr.t_arrive, tr.t_depart, tr.t_gate_out))
            off = tr.reroute["t_trigger"] if tr.reroute else tr.t_offloaded
            done.append((off, tr.cust, tr.site_hours))
            done.sort(key=lambda x: x[0])
        while done:
            _, ci, h = done.pop(0)
            stats.add(ci, h)
        return pd.DataFrame(rows), stats

    # -- training -------------------------------------------------------
    def train(self, now):
        from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
        from sklearn.inspection import permutation_importance
        t0 = time.perf_counter()
        self.status = "training"
        trips = [tr for tr in self.sim.completed(now)]
        df, stats = self._table(trips)
        if len(df) < 400:
            self.status = f"waiting for trips ({len(df)} of 400)"
            return None
        df = df.sort_values("t").reset_index(drop=True)
        cut = int(len(df) * 0.75)
        tr_df, te_df = df.iloc[:cut], df.iloc[cut:]
        X_tr, X_te = tr_df[FEATURES].to_numpy(float), te_df[FEATURES].to_numpy(float)
        cat_mask = [f in CATS for f in FEATURES]
        out, models, q90, charge = {}, {}, {}, {}
        for key, spec in MODELS.items():
            y_tr, y_te = tr_df[f"y_{key}"].to_numpy(), te_df[f"y_{key}"].to_numpy()
            rule = te_df[f"rule_{key}"].to_numpy()
            if spec["kind"] == "clf":
                m = HistGradientBoostingClassifier(max_iter=180, learning_rate=0.05, max_leaf_nodes=15,
                                                   min_samples_leaf=40, l2_regularization=2.0,
                                                   categorical_features=cat_mask,
                                                   random_state=3)
                m.fit(X_tr, y_tr)
                p = m.predict_proba(X_te)[:, 1]
                brier_m = float(np.mean((p - y_te) ** 2))
                brier_r = float(np.mean((rule - y_te) ** 2))
                top = p >= np.quantile(p, 0.8)
                capture = float(y_te[top].sum() / max(1, y_te.sum()))
                top_r = rule >= np.quantile(rule, 0.8)
                capture_r = float(y_te[top_r].sum() / max(1, y_te.sum()))
                calib = pd.DataFrame({"p": p, "y": y_te})
                calib["bin"] = pd.qcut(calib["p"].rank(method="first"), 10, labels=False)
                cal = calib.groupby("bin").agg(pred=("p", "mean"), actual=("y", "mean"), n=("y", "size")).reset_index()
                out[key] = {"model_err": brier_m, "rule_err": brier_r, "capture": capture,
                            "capture_rule": capture_r, "base_rate": float(y_te.mean()), "calibration": cal,
                            "pred": p}
                charge[key] = brier_m < brier_r
                score_fn = "neg_brier_score"
            else:
                m = HistGradientBoostingRegressor(max_iter=220, learning_rate=0.05, max_leaf_nodes=20,
                                                  min_samples_leaf=30, l2_regularization=1.0,
                                                  loss="absolute_error" if key == "site" else "squared_error",
                                                  categorical_features=cat_mask, random_state=3)
                m.fit(X_tr, y_tr)
                p = m.predict(X_te)
                mae_m = float(np.mean(np.abs(p - y_te)))
                mae_r = float(np.mean(np.abs(rule - y_te)))
                resid = y_te - p
                q90[key] = float(np.quantile(resid, 0.9))
                tol = 0.5 if key == "site" else 30.0
                out[key] = {"model_err": mae_m, "rule_err": mae_r,
                            "within": float(np.mean(np.abs(p - y_te) <= tol)),
                            "within_rule": float(np.mean(np.abs(rule - y_te) <= tol)),
                            "late_case_hold": float(np.mean(y_te <= p + q90[key])), "tol": tol, "pred": p}
                charge[key] = mae_m < mae_r
                score_fn = "neg_mean_absolute_error"
            # what the model leans on (permutation importance on a sample of the test quarter)
            n = min(900, len(X_te))
            idx = np.linspace(0, len(X_te) - 1, n).astype(int)
            imp = permutation_importance(m, X_te[idx], y_te[idx], n_repeats=3, random_state=1,
                                         scoring=score_fn)
            out[key]["importance"] = (pd.DataFrame({"feature": [FEATURE_LABELS[f] for f in FEATURES],
                                                    "weight": imp.importances_mean})
                                      .sort_values("weight", ascending=False).head(8))
            models[key] = m
        # test-quarter predictions become the first model-health records
        recs = []
        for i, row in enumerate(te_df.itertuples(index=False)):
            for key in MODELS:
                recs.append({"t": row.t, "model": key, "pred": float(out[key]["pred"][i]),
                             "rule": float(getattr(row, f"rule_{key}")), "actual": float(getattr(row, f"y_{key}")),
                             "source": "test"})
        for key in out:
            out[key].pop("pred", None)
        with self.lock:
            self.models, self.resid_q90, self.in_charge = models, q90, charge
            self.stats = stats
            self.report = {"metrics": out, "rows": len(df), "train_rows": cut, "test_rows": len(df) - cut,
                           "seconds": round(time.perf_counter() - t0, 1), "test_from": float(te_df["t"].iloc[0]),
                           "visits": len(df)}
            keep = [r for r in self.records if r["source"] == "live"]
            self.records = recs + keep
            self.trained_at = time.time()
            self.trained_sim_t = now
            self.status = "ready"
        return self.report

    # -- prediction at dispatch -------------------------------------------
    def predict(self, trip, at_site=0, heading=0):
        if not self.models:
            return None
        f = self.features(trip, self.stats, at_site, heading)
        x = np.array([[f[k] for k in FEATURES]], float)
        rule = {"risk": self.stats.long_rate(trip.cust), "site": self.stats.mean_h(trip.cust),
                "eta": trip.plan_travel_min, "back": f["return_km"] / RULES.truck_speed_kmh * 60.0}
        with self.lock:
            model = {"risk": float(self.models["risk"].predict_proba(x)[0, 1]),
                     "site": float(self.models["site"].predict(x)[0]),
                     "eta": float(self.models["eta"].predict(x)[0]),
                     "back": float(self.models["back"].predict(x)[0])}
            use = dict(self.in_charge)
            q90 = dict(self.resid_q90)
        chosen = {k: (model[k] if use.get(k) else rule[k]) for k in model}
        return {"model": model, "rule": rule, "use": use, "value": chosen, "q90": q90,
                "made_at": trip.t_gate_out}

    def risk_now(self, ci, t, origin_code, transporter, at_site=0, heading=0):
        """Delay risk for a hypothetical truck sent now to customer ci."""
        if not self.models:
            return self.stats.long_rate(ci)
        from .sim import Trip
        c = self.w.customers.iloc[ci]
        km = float(self.w.dist_cp[ci, self.w.point_index[origin_code]]) * RULES.road_factor
        tr = Trip(id="probe", truck_id="", transporter=transporter, origin=origin_code, cust=ci,
                  release_id="", product="", qty_t=30, t_assign=t, t_load_start=t, t_gate_out=t,
                  t_promised=t, t_arrive=t, t_offloaded=t, t_depart=t, t_back=t, base=origin_code,
                  dist_km=km, return_km=km, plan_travel_min=km / RULES.truck_speed_kmh * 60, travel_min=0,
                  return_min=0, site_hours=0, queue_on_arrival=0, queue_at_load=0)
        p = self.predict(tr, at_site, heading)
        return p["value"]["risk"] if p else self.stats.long_rate(ci)

    # -- model health -------------------------------------------------------
    def record_outcomes(self, trips):
        """Score the predictions of trips whose outcomes are now known."""
        with self.lock:
            for tr in trips:
                if not tr.pred:
                    continue
                y = {"risk": float(tr.site_hours >= RULES.site_reroute_hours), "site": tr.site_hours,
                     "eta": tr.travel_min, "back": tr.return_min}
                for key in MODELS:
                    self.records.append({"t": tr.t_gate_out, "model": key, "pred": tr.pred["model"][key],
                                         "rule": tr.pred["rule"][key], "actual": y[key], "source": "live"})

    def health(self, now, days):
        with self.lock:
            df = pd.DataFrame(self.records)
        if df.empty:
            return df, {}
        df = df[df["t"] >= now - days * C.DAY].copy()
        df["day"] = (df["t"] // C.DAY).astype(int)
        risk = df["model"] == "risk"
        df["model_err"] = np.where(risk, (df["pred"] - df["actual"]) ** 2, (df["pred"] - df["actual"]).abs())
        df["rule_err"] = np.where(risk, (df["rule"] - df["actual"]) ** 2, (df["rule"] - df["actual"]).abs())
        daily = df.groupby(["model", "day", "source"]).agg(model_err=("model_err", "mean"),
                                                           rule_err=("rule_err", "mean"),
                                                           n=("actual", "size")).reset_index()
        summary = {}
        for key in MODELS:
            d = df[df["model"] == key]
            if d.empty:
                continue
            me, re_ = d["model_err"].mean(), d["rule_err"].mean()
            live = d[d["source"] == "live"]
            summary[key] = {"model_err": float(me), "rule_err": float(re_), "n": int(len(d)),
                            "live_n": int(len(live)),
                            "state": "Healthy" if me <= re_ * 0.98 else ("Watch" if me <= re_ * 1.05 else "Act now")}
        return daily, summary
