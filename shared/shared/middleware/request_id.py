"""
Request ID Middleware — correlation ID propagation for distributed tracing.

Generates or propagates X-Request-ID header across services.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variable for request-scoped correlation ID
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Get the current request's correlation ID."""
    return request_id_ctx.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that sets a unique request/correlation ID per request.

    If the incoming request has an X-Request-ID header, it is reused.
    Otherwise, a new UUID is generated. The ID is propagated in responses
    and made available via context variable for logging and tracing.
    """

    HEADER_NAME = "X-Request-ID"

    async def dispatch(self, request: Request, call_next) -> Response:
        # Use existing header or generate new
        req_id = request.headers.get(self.HEADER_NAME) or str(uuid.uuid4())
        token = request_id_ctx.set(req_id)

        try:
            response = await call_next(request)
            response.headers[self.HEADER_NAME] = req_id
            return response
        finally:
            request_id_ctx.reset(token)
