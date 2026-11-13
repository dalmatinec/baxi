# Бот в контейнере: для установки на сервер клиента через Docker Compose
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Almaty

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
RUN useradd --system --uid 10001 bot && mkdir -p /app/data && chown -R bot /app/data
USER bot

CMD ["python", "-m", "bot"]
