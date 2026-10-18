"""
Prometheus Metrics — application metrics for monitoring and alerting.
"""

from __future__ import annotations

import time
from typing import Callable

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ── HTTP Metrics ──────────────────────────────────────────────────
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code", "service"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint", "service"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "Number of HTTP requests currently in progress",
    ["method", "service"],
)

# ── Business Metrics ─────────────────────────────────────────────
orders_created_total = Counter(
    "orders_created_total",
    "Total orders created",
    ["order_type", "service"],
)

payments_processed_total = Counter(
    "payments_processed_total",
    "Total payments processed",
    ["gateway", "status", "service"],
)

cart_operations_total = Counter(
    "cart_operations_total",
    "Total cart operations",
    ["operation", "service"],
)

search_queries_total = Counter(
    "search_queries_total",
    "Total search queries",
    ["search_type", "service"],
)

active_sessions_gauge = Gauge(
    "active_agent_sessions",
    "Number of active agent sessions",
    ["service"],
)

tool_calls_total = Counter(
    "tool_calls_total",
    "Total tool calls made by the agent",
    ["tool_name", "status", "service"],
)

llm_requests_total = Counter(
    "llm_requests_total",
    "Total LLM API requests",
    ["provider", "status", "service"],
)

llm_request_duration_seconds = Histogram(
    "llm_request_duration_seconds",
    "LLM request duration in seconds",
    ["provider", "service"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

# ── Infrastructure Metrics ───────────────────────────────────────
db_query_duration_seconds = Histogram(
    "db_query_duration_seconds",
    "Database query duration in seconds",
    ["operation", "table", "service"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)

cache_hits_total = Counter(
    "cache_hits_total",
    "Total cache hits",
    ["cache_key_prefix", "service"],
)

cache_misses_total = Counter(
    "cache_misses_total",
    "Total cache misses",
    ["cache_key_prefix", "service"],
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Middleware to collect HTTP metrics."""

    def __init__(self, app, service_name: str = "unknown") -> None:
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        # Normalize path to avoid cardinality explosion
        path = self._normalize_path(request.url.path)

        http_requests_in_progress.labels(method=method, service=self.service_name).inc()
        start_time = time.monotonic()

        try:
            response = await call_next(request)
            status_code = str(response.status_code)
        except Exception:
            status_code = "500"
            raise
        finally:
            duration = time.monotonic() - start_time
            http_requests_in_progress.labels(
                method=method, service=self.service_name
            ).dec()
            http_requests_total.labels(
                method=method,
                endpoint=path,
                status_code=status_code,
                service=self.service_name,
            ).inc()
            http_request_duration_seconds.labels(
                method=method, endpoint=path, service=self.service_name
            ).observe(duration)

        return response

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize paths to prevent metric cardinality explosion.

        Replaces UUIDs and numeric IDs with placeholders.
        """
        import re

        # Replace UUIDs
        path = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "{id}",
            path,
        )
        # Replace numeric IDs
        path = re.sub(r"/\d+(?=/|$)", "/{id}", path)
        return path


def metrics_endpoint() -> bytes:
    """Generate Prometheus metrics output for the /metrics endpoint."""
    return generate_latest()
