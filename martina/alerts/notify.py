"""Turning control tower events into emails for the right people.

Each trigger names the roles that should hear about it. Recipients come
from the `recipients` table: shared desks by role, sales reps by region, and
supervisors by works or depot. With SMTP settings in .env the alerts are
sent; without them they go to an outbox (shown on the Control Tower and
written to data/outbox.jsonl), so the routing can be checked safely.
"""
from __future__ import annotations

import json
import logging
import smtplib
import threading
from collections import deque
from email.message import EmailMessage

from .. import brand
from ..config import ROOT, SETTINGS

log = logging.getLogger("martina.alerts")

TRIGGERS = {
    "Past reroute trigger": {"roles": ["dispatch", "sales", "point"], "severity": "High",
                             "subject": "Truck past the {h}h reroute trigger at {customer}"},
    "Escalated": {"roles": ["customer", "sales", "dispatch"], "severity": "Critical",
                  "subject": "Escalation: {truck} {h}h on site at {customer}"},
    "GPS lost 30 min": {"roles": ["fleet"], "severity": "High",
                        "subject": "Tracking lost on {truck} ({transporter})"},
    "Idle 4h+": {"roles": ["dispatch", "point"], "severity": "Medium",
                 "subject": "{truck} idle 4h+ at {point_name}"},
    "Dispatched to hold": {"roles": ["credit", "dispatch"], "severity": "High",
                           "subject": "Load dispatched to {customer}, which is on credit hold"},
}


class Notifier:
    def __init__(self):
        self.outbox = deque(maxlen=300)
        self.sent_keys = set()
        self.lock = threading.Lock()
        self.recipients = None

    def set_recipients(self, df):
        self.recipients = df

    def _who(self, roles, region="", point=""):
        df = self.recipients
        if df is None or df.empty:
            return []
        out = []
        for role in roles:
            d = df[df["role"] == role]
            if role == "sales" and region:
                d = d[d["region"] == region]
            if role == "point" and point:
                d = d[d["point_code"] == point]
            out += [f"{r.name} <{r.email}>" for r in d.itertuples()]
        return sorted(set(out))

    def raise_alert(self, kind, key, when_label, body, region="", point="", **fmt):
        spec = TRIGGERS.get(kind)
        if spec is None:
            return None
        with self.lock:
            if key in self.sent_keys:
                return None
            self.sent_keys.add(key)
        to = self._who(spec["roles"], region, point)
        subject = f"[{brand.COMPANY['short']} {brand.COMPANY['product']}] " + spec["subject"].format(**fmt)
        item = {"kind": kind, "severity": spec["severity"], "subject": subject, "to": to,
                "body": body, "when": when_label, "status": "queued"}
        if SETTINGS.smtp_host and to:
            threading.Thread(target=self._send, args=(item,), daemon=True).start()
        else:
            item["status"] = "outbox (no SMTP set)"
            self._write(item)
        with self.lock:
            self.outbox.appendleft(item)
        return item

    def _write(self, item):
        try:
            (ROOT / "data").mkdir(parents=True, exist_ok=True)
            with open(ROOT / "data" / "outbox.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(item) + "\n")
        except OSError:
            pass

    def _send(self, item):
        msg = EmailMessage()
        msg["Subject"] = item["subject"]
        msg["From"] = SETTINGS.smtp_sender or SETTINGS.smtp_user
        msg["To"] = ", ".join(item["to"])
        msg.set_content(item["body"] + "\n\nSent by the FulfilmentIQ control tower.")
        try:
            with smtplib.SMTP(SETTINGS.smtp_host, SETTINGS.smtp_port, timeout=20) as s:
                s.starttls()
                if SETTINGS.smtp_user:
                    s.login(SETTINGS.smtp_user, SETTINGS.smtp_password)
                s.send_message(msg)
            item["status"] = "sent"
        except Exception as e:                                # noqa: BLE001
            item["status"] = f"failed: {type(e).__name__}"
            log.warning("alert email failed: %s", type(e).__name__)
            self._write(item)

    def recent(self, n=50):
        with self.lock:
            return list(self.outbox)[:n]


NOTIFIER = Notifier()
