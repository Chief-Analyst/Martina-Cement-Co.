"""Entry point for gunicorn: gunicorn wsgi:server --workers 1 --threads 8"""
from martina.app_server import build

app = build()
server = app.server
