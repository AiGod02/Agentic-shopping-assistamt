FROM python:3.12-slim AS base

WORKDIR /app

COPY shared/ /app/shared/
RUN pip install --no-cache-dir /app/shared/

COPY agent_server/pyproject.toml /app/agent_server/
RUN pip install --no-cache-dir /app/agent_server/

COPY agent_server/ /app/agent_server/

EXPOSE 8001

CMD ["uvicorn", "agent_server.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "4"]
