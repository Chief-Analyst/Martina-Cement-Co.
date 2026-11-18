"""Shared set-up: a smaller fleet and history so the suite runs in under a minute."""
import os
import sys
from pathlib import Path

os.environ.setdefault("MC_SIM_HISTORY_DAYS", "21")
os.environ.setdefault("MC_FLEET_SIZE", "70")
os.environ.pop("GROQ_API_KEY", None)          # tests never call the network
os.environ["MC_DATA_SOURCE"] = "synthetic"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def store():
    from martina.data.store import STORE
    STORE.refresh()
    return STORE


@pytest.fixture(scope="session")
def feed(store):
    from martina.logistics.feed import FEED
    FEED.tick_seconds = 1e9            # the tests move the clock themselves
    FEED._boot()
    assert FEED.ready(), FEED.error
    for _ in range(60):
        FEED.advance(5)
    return FEED
