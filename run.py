"""Start the dashboard: python run.py, then open http://127.0.0.1:8050"""
import logging
import os
import socket
import sys
os.environ["REACT_VERSION"] = "19.2.4"
from martina.app_server import build


def _already_running(host, port):
    """True when something already answers on this port. On Windows a second copy
    can share the port with an old one, and the browser keeps getting the old code."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
app = build()

if __name__ == "__main__":
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", 8050))
    if _already_running("127.0.0.1" if host == "0.0.0.0" else host, port):
        sys.exit(f"Port {port} is already in use, most likely by an earlier run of this dashboard.\n"
                 "Stop it first (the red square in PyCharm's Run window, or close that terminal), then run again.")
    app.run(host=host, port=port, debug=os.environ.get("MC_DEBUG", "0") == "1")
