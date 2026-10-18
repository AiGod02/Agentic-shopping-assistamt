FROM python:3.12-slim AS base

WORKDIR /app

# Install shared library
COPY shared/ /app/shared/
RUN pip install --no-cache-dir /app/shared/

# Install merchant server
COPY merchant_server/pyproject.toml /app/merchant_server/
RUN pip install --no-cache-dir /app/merchant_server/

COPY merchant_server/ /app/merchant_server/

EXPOSE 8002

CMD ["uvicorn", "merchant_server.main:app", "--host", "0.0.0.0", "--port", "8002", "--workers", "4"]
