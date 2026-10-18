FROM python:3.12-slim AS base

WORKDIR /app

COPY shared/ /app/shared/
RUN pip install --no-cache-dir /app/shared/

COPY payment_server/pyproject.toml /app/payment_server/
RUN pip install --no-cache-dir /app/payment_server/

COPY payment_server/ /app/payment_server/

EXPOSE 8003

CMD ["uvicorn", "payment_server.main:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "4"]
