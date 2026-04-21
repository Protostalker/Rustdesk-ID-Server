FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# App DB lives in /data (volume mount).
RUN mkdir -p /data
ENV APP_DB_PATH=/data/companion.sqlite3 \
    RUSTDESK_DATA_DIR=/rustdesk-data \
    SYNC_INTERVAL_SECONDS=60 \
    LAUNCH_RUSTDESK_ENABLED=false

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
