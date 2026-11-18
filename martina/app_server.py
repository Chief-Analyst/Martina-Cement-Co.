"""Builds the app and starts the background work (data refresh, forecast, fleet)."""
import logging

log = logging.getLogger("martina")


def build():
    from .data.store import STORE, start_refresh_loop
    from .orderbook.forecast import FORECASTER
    from .ui.app import create_app

    STORE.refresh()
    FORECASTER.train_async()
    STORE.on_refresh(lambda _s: FORECASTER.train_async())
    start_refresh_loop()
    try:
        from .logistics.feed import FEED
        FEED.start()
    except ImportError:
        log.info("logistics module not available")
    return create_app()
