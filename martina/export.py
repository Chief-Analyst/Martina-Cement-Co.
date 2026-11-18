"""The management workbook: one Excel file with every list a planner acts on."""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import brand
from .config import RULES
from .orderbook import analytics as A
from .orderbook import operations as O
from .orderbook.pipeline import norm_filters

HEAD = PatternFill("solid", fgColor=brand.COLORS["primary"].lstrip("#"))
BAND = {"CRITICAL": "D1495B", "HIGH": "D1495B", "POOR": "D1495B", "Hold": "D1495B",
        "WATCH": "E0A126", "MEDIUM": "E0A126", "FAIR": "E0A126", "Caution": "E0A126",
        "HEALTHY": "2F9E6B", "GOOD": "2F9E6B", "Ready": "2F9E6B"}


def _sheet(writer, name, df, note):
    df = df.copy()
    for c in df.columns:
        if str(df[c].dtype) == "category":
            df[c] = df[c].astype(str)
    df.to_excel(writer, sheet_name=name, index=False, startrow=2)
    ws = writer.sheets[name]
    ws["A1"] = note
    ws["A1"].font = Font(italic=True, color="64748B")
    for i, col in enumerate(df.columns, start=1):
        cell = ws.cell(row=3, column=i)
        cell.fill, cell.font = HEAD, Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        width = max(10, min(45, int(max([len(str(col))] + [len(str(v)) for v in df[col].head(200)]) * 1.1)))
        ws.column_dimensions[get_column_letter(i)].width = width
        for r in range(4, 4 + len(df)):
            v = ws.cell(row=r, column=i)
            if isinstance(v.value, float):
                v.number_format = "0.0%" if any(k in col for k in ("ratio", "rate", "share")) else "#,##0.00"
            if v.value in BAND:
                v.font = Font(bold=True, color=BAND[v.value])
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:{get_column_letter(max(1, len(df.columns)))}{3 + len(df)}"


def workbook(filters=None) -> bytes:
    f = norm_filters(filters or {})
    k = A.kpis(f)
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    summary = pd.DataFrame([
        ("Ordered (last 30 days), t", k["ordered_t"]), ("Lifted (last 30 days), t", k["lifted_t"]),
        ("Fill rate", k["fill_rate"]), ("Backlog, t", k["open_t"]),
        ("Open on contracts, t", k["open_contract_t"]), ("Open released, t", k["open_release_t"]),
        ("Open value, NGN", k["open_value_ngn"]), ("Customers with open orders", k["customers_open"]),
    ], columns=["Measure", "Value"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        _sheet(w, "Summary", summary, f"{brand.COMPANY['name']} order fulfilment report, {stamp}. Demo data.")
        _sheet(w, "Order cover", A.cover_risk(f), f"Critical under {RULES.cover_critical_days:g} days of orders booked")
        _sheet(w, "Lifting behaviour", A.behaviour(f), "Lifted as a share of ordered, last 30 days")
        _sheet(w, "Release plan 3d", O.release_planning(f, 3), "Delivered orders only")
        _sheet(w, "Partial releases", O.partial_releases(f, "all"), f"HIGH once {RULES.partial_alert_days} days old")
        _sheet(w, "FIFO watch", O.fifo_watch(f, RULES.fifo_wait_days, "flag"), "Older releases waiting")
        _sheet(w, "Order book", O.order_book(f), "Per customer")
        _sheet(w, "Shipping points", O.shipping_points(f, "all"), "Open tonnage by works and depot")
        try:
            from .orderbook.forecast import FORECASTER
            r = FORECASTER.get()
            if r:
                fc = r["forecast"].copy()
                fc["date"] = fc["date"].dt.strftime("%a %d %b")
                _sheet(w, "Demand forecast", fc, "Tonnes likely to be ordered, next 7 days")
        except Exception:                                   # noqa: BLE001
            pass
        try:
            from .logistics import rules as R
            from .logistics.feed import FEED
            if FEED.ready():
                ex = R.exceptions(FEED.snapshot(), FEED).drop(columns=["sev", "order", "key"])
                _sheet(w, "Fleet exceptions", ex, f"Simulated fleet, control tower clock {FEED.now_label()}")
        except Exception:                                   # noqa: BLE001
            pass
    return buf.getvalue()
