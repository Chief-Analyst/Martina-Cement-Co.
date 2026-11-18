FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV MC_DATA_SOURCE=synthetic PORT=8050
EXPOSE 8050
# One worker: the data store and the fleet simulation live in memory and are shared by every viewer.
CMD ["sh", "-c", "gunicorn wsgi:server --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:${PORT}"]
