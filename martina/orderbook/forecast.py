"""Seven-day demand forecast: tonnes likely to be ordered per day, per region.

One gradient-boosted model is trained across every region on the ratio of a
day's demand to the region's recent level, so small regions learn from the
large ones. Three models give the likely value and a 1-in-10 to 9-in-10
range. It is tested on the most recent four weeks it never saw, against the
plain rule "average of the same weekday over the last four weeks". Where
the rule does better, the page uses the rule for that region and says so.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd

from ..data.store import STORE

HORIZON = 7
TEST_DAYS = 28
QUANTILES = {"low": 0.1, "mid": None, "high": 0.9}     # None: the expected value


def _series(book):
    d = book.demand.groupby(["date", "region"], observed=True)["qty_t"].sum().unstack(fill_value=0.0)
    d.columns = d.columns.astype(str)
    # Today is still in progress, so the series ends yesterday and the
    # forecast's first day is today.
    idx = pd.date_range(d.index.min(), book.anchor.normalize() - pd.Timedelta(days=1), freq="D")
    d = d.reindex(idx, fill_value=0.0)
    d["All regions"] = d.sum(axis=1)
    return d


def _features(series: pd.Series, origin_pos: int, h: int, region_code: int):
    """Features known at the end of day origin_pos for the day h ahead."""
    hist = series.iloc[: origin_pos + 1].to_numpy()
    day = series.index[origin_pos] + pd.Timedelta(days=h)
    last7 = hist[-7:].mean()
    last28 = hist[-28:].mean()
    same_dow = hist[[h - 8, h - 15, h - 22, h - 29]]
    level = max(last28, 1.0)
    yago = hist[-365 + h - 1] / level if len(hist) >= 365 else 1.0
    doy = day.dayofyear
    return [day.dayofweek, np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25),
            day.month, h, last7 / level, same_dow.mean() / level if len(same_dow) else 1.0,
            yago, region_code], level, day


def _rule(series: pd.Series, origin_pos: int, h: int) -> float:
    """Average of the same weekday over the four weeks before the origin."""
    hist = series.iloc[: origin_pos + 1].to_numpy()
    return float(hist[[h - 8, h - 15, h - 22, h - 29]].mean())


class Forecaster:
    def __init__(self):
        self.lock = threading.Lock()
        self.result = None
        self.version = None
        self.status = {"state": "not trained"}

    def train(self):
        from sklearn.ensemble import HistGradientBoostingRegressor
        t0 = time.perf_counter()
        book = STORE.ensure().book
        data = _series(book)
        regions = list(data.columns)
        start = 365 if len(data) > 420 else 35
        X, y, lv, tags = [], [], [], []
        for code, reg in enumerate(regions):
            s = data[reg]
            for pos in range(start, len(s) - 1):
                for h in range(1, HORIZON + 1):
                    if pos + h >= len(s):
                        break
                    feats, level, _ = _features(s, pos, h, code)
                    X.append(feats)
                    y.append(s.iloc[pos + h] / level)
                    lv.append(level)
                    tags.append((reg, pos, h))
        X, y, lv = np.array(X), np.array(y), np.array(lv)
        tag_pos = np.array([t[1] for t in tags])
        cut = len(data) - 1 - TEST_DAYS
        train_m = tag_pos + np.array([t[2] for t in tags]) <= cut
        test_m = (tag_pos >= cut) & (np.array([t[2] for t in tags]) == 1)

        def fit(mask, q):
            kind = {"loss": "quantile", "quantile": q} if q else {"loss": "squared_error"}
            m = HistGradientBoostingRegressor(**kind, max_iter=250,
                                              learning_rate=0.06, max_leaf_nodes=24,
                                              categorical_features=[8], random_state=7)
            return m.fit(X[mask], y[mask])

        # Held-back test: next-day forecasts over the last TEST_DAYS days
        mid = fit(train_m, None)
        pred = mid.predict(X[test_m]) * lv[test_m]
        actual = y[test_m] * lv[test_m]
        test_tags = [t for t, keep in zip(tags, test_m) if keep]
        naive = np.array([_rule(data[r], p, 1) for r, p, _ in test_tags])
        reg_arr = np.array([t[0] for t in test_tags])
        scores = {}
        for reg in regions:
            m = reg_arr == reg
            denom = actual[m].sum() or 1.0
            mw = float(np.abs(pred[m] - actual[m]).sum() / denom)
            rw = float(np.abs(naive[m] - actual[m]).sum() / denom)
            scores[reg] = {"model_wape": mw, "rule_wape": rw, "use_model": mw <= rw}
        test_frame = pd.DataFrame({"region": reg_arr, "date": [data.index[p + 1] for _, p, _ in test_tags],
                                   "actual": actual, "model": pred, "rule": naive})

        # Final models on everything, then forecast from today
        models = {k: fit(np.ones(len(y), bool), q) for k, q in QUANTILES.items()}
        rows = []
        last = len(data) - 1
        for code, reg in enumerate(regions):
            for h in range(1, HORIZON + 1):
                feats, level, day = _features(data[reg], last, h, code)
                vals = {k: float(max(0.0, m.predict(np.array([feats]))[0] * level))
                        for k, m in models.items()}
                if not scores[reg]["use_model"]:
                    vals["mid"] = _rule(data[reg], last, h)
                lo, hi = sorted([vals["low"], vals["high"]])
                rows.append({"region": reg, "date": day, "likely": vals["mid"],
                             "method": "model" if scores[reg]["use_model"] else "rule",
                             "low": min(lo, vals["mid"]), "high": max(hi, vals["mid"])})
        fc = pd.DataFrame(rows)
        result = {
            "trained_at": datetime.now(), "seconds": round(time.perf_counter() - t0, 1),
            "history_days": len(data), "history_start": data.index[0], "history_end": data.index[-1],
            "forecast": fc, "history": data, "scores": scores, "test": test_frame,
            "customers": self._customers(book, fc),
        }
        with self.lock:
            self.result = result
            self.version = STORE.version
            self.status = {"state": "ready", "trained_at": result["trained_at"],
                           "seconds": result["seconds"]}
        return result

    @staticmethod
    def _customers(book, fc):
        """Largest customers: next 7 days = their last 4 weeks' daily rate x season."""
        d = book.demand
        end = book.anchor.normalize()
        last28 = d[d["date"] > end - pd.Timedelta(days=28)]
        hist_total = last28["qty_t"].sum() / 28.0
        fc_total = fc[fc["region"] == "All regions"]["likely"].sum() / HORIZON
        factor = fc_total / hist_total if hist_total else 1.0
        g = (last28.groupby(["customer_id", "customer_name", "region"], observed=True)["qty_t"].sum()
             .sort_values(ascending=False).head(25).reset_index())
        g["last_28d_t"] = g["qty_t"]
        g["next_7d_t"] = (g["qty_t"] / 28.0 * 7 * factor).round(-1)
        g["customer_name"] = g["customer_name"].astype(str)
        g["region"] = g["region"].astype(str)
        return g[["customer_id", "customer_name", "region", "last_28d_t", "next_7d_t"]]

    def get(self, wait=False):
        if self.result is None or self.version != STORE.version:
            if wait:
                self.train()
            else:
                self.train_async()
        return self.result

    def train_async(self):
        if self.status.get("state") == "training":
            return
        self.status = {**self.status, "state": "training"}
        threading.Thread(target=self._safe_train, daemon=True, name="forecast-train").start()

    def _safe_train(self):
        try:
            self.train()
        except Exception as e:                       # noqa: BLE001
            self.status = {"state": "failed", "error": str(e)}


FORECASTER = Forecaster()
