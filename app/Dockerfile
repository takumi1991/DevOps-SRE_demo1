# ====== builder ======
FROM python:3.11-slim AS builder
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps -r requirements.txt -w /wheels

# ====== runtime ======
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PORT=8080
# 依存をインストール
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels
# アプリ本体
COPY main.py ./
# Cloud Run は 8080 をリッスン
EXPOSE 8080
# gunicorn で Flask を起動
CMD ["gunicorn", "-b", "0.0.0.0:8080", "-w", "2", "main:app"]
