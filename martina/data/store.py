"""One in-memory copy of the data, shared by every page and user.

`STORE.frames` holds the raw tables, `STORE.book` the derived order book
(see orderbook.pipeline). Every refresh bumps `STORE.version`; page caches
key on it, so nothing is recomputed between refreshes and nothing stale
survives one.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..config import SETTINGS
from . import schema

log = logging.getLogger("martina.data")


def load_csv(folder: Path):
    frames = {}
    for name in schema.TABLES:
        path = Path(folder) / f"{name}.csv"
        if path.exists():
            frames[name] = pd.read_csv(path)
    return frames


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self._gate = threading.Lock()          # one refresh at a time
        self.frames: dict = {}
        self.traits = None
        self.book = None
        self.version = 0
        self.loaded_at: datetime | None = None
        self.anchor: pd.Timestamp | None = None
        self.status = {"ok": False, "message": "not loaded", "seconds": 0.0,
                       "source": SETTINGS.data_source, "problems": []}
        self._listeners = []

    # -- loading -------------------------------------------------------
    def refresh(self, now: datetime | None = None):
        """Reload the source and rebuild the derived book. Returns the status."""
        if not self._gate.acquire(blocking=False):
            return self.status                 # a refresh is already running
        try:
            t0 = time.perf_counter()
            from ..orderbook.pipeline import build_book
            if SETTINGS.data_source == "csv":
                frames, traits = load_csv(SETTINGS.data_dir), None
            else:
                from .synthetic import generate
                frames, traits = generate(now=now)
            problems = schema.validate(frames)
            if problems:
                self.status = {**self.status, "ok": False,
                               "message": "data problems: " + " ".join(problems),
                               "problems": problems}
                log.error("data refresh failed: %s", problems)
                return self.status
            schema.coerce(frames)
            book = build_book(frames)
            with self.lock:
                self.frames, self.traits, self.book = frames, traits, book
                self.anchor = book.anchor
                self.version += 1
                self.loaded_at = datetime.now()
                secs = round(time.perf_counter() - t0, 2)
                self.status = {"ok": True, "message": "loaded", "seconds": secs,
                               "source": SETTINGS.data_source, "problems": [],
                               "rows": int(len(frames["orders"]))}
            log.info("data refreshed in %.2fs (version %s)", secs, self.version)
            for fn in list(self._listeners):
                try:
                    fn(self)
                except Exception:                       # noqa: BLE001
                    log.exception("refresh listener failed")
            return self.status
        finally:
            self._gate.release()

    def on_refresh(self, fn):
        self._listeners.append(fn)

    def ensure(self):
        if self.book is None:
            self.refresh()
        return self

    def table(self, name) -> pd.DataFrame:
        self.ensure()
        return self.frames[name]


STORE = Store()


def start_refresh_loop():
    """Refresh in the background every SETTINGS.refresh_minutes."""
    def loop():
        while True:
            time.sleep(max(60, SETTINGS.refresh_minutes * 60))
            try:
                STORE.refresh()
            except Exception:                           # noqa: BLE001
                log.exception("scheduled refresh failed")
    threading.Thread(target=loop, name="data-refresh", daemon=True).start()
