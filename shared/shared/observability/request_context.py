"""
Request Context — per-request trace_id propagated across all layers via contextvars.

Usage:
    from shared.observability.request_context import set_trace, trace_log

    # At request entry (e.g. FastAPI middleware or endpoint):
    set_trace(new_trace_id())

    # Anywhere inside the request (sync or async, any module):
    trace_log("step_name", key=value, ...)
"""
from __future__ import annotations

import contextvars
import time
import uuid
from typing import Any

# Per-request context vars — set once at HTTP entry, readable anywhere in the call stack
_trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="--------")
_request_start_var: contextvars.ContextVar[float] = contextvars.ContextVar("req_start", default=0.0)


def new_trace_id() -> str:
    """Generate a short 12-char hex trace ID."""
    return uuid.uuid4().hex[:12]


def set_trace(trace_id: str) -> None:
    """Set the trace_id and start the request timer. Call once at HTTP request entry."""
    _trace_id_var.set(trace_id)
    _request_start_var.set(time.perf_counter())


def get_trace_id() -> str:
    return _trace_id_var.get()


def elapsed_ms() -> str:
    start = _request_start_var.get()
    if start == 0.0:
        return "    ?ms"
    return f"{(time.perf_counter() - start) * 1000:>7.1f}ms"


def trace_log(step: str, **kwargs: Any) -> None:
    """
    Emit a structured trace line — always flushed to stdout.
    Visible in the uvicorn terminal alongside normal log output.

    Example output:
    [TRACE 4a3f2c9b1d7e] +   12.4ms  weaviate_search_start             query='laptop'  url='https://...'
    """
    tid = _trace_id_var.get()
    t = elapsed_ms()
    extras = "  ".join(f"{k}={v!r}" for k, v in kwargs.items()) if kwargs else ""
    line = f"[TRACE {tid}] +{t}  {step:<45} {extras}"
    print(line, flush=True)

