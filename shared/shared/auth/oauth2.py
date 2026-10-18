"""
OAuth2 — Password-based and token refresh flows for FastAPI.

Provides the FastAPI security scheme and authentication middleware.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.auth.jwt_handler import JWTHandler, TokenPayload

# HTTP Bearer scheme for OpenAPI docs
bearer_scheme = HTTPBearer(auto_error=False)


from starlette.middleware.base import BaseHTTPMiddleware


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that extracts and validates JWT from Authorization header.

    Populates request.state.user with the decoded TokenPayload.
    Non-authenticated requests get request.state.user = None (for optional auth endpoints).
    """

    def __init__(
        self,
        app,
        jwt_handler: JWTHandler,
        exclude_paths: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.jwt_handler = jwt_handler
        self.exclude_paths = set(exclude_paths or [])

    async def dispatch(self, request: Request, call_next):
        is_excluded = any(request.url.path == p or request.url.path.startswith(p + "/") for p in self.exclude_paths) or request.url.path.startswith("/api/v1/subscriptions/activate/")

        if is_excluded:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]
                try:
                    payload = await self.jwt_handler.verify_token(token)
                    request.state.user = payload
                    if payload.merchant_id:
                        from shared.db.session import current_tenant_id
                        current_tenant_id.set(payload.merchant_id)
                except Exception:
                    request.state.user = None
            else:
                request.state.user = None
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = await self.jwt_handler.verify_token(token)
                request.state.user = payload
                if payload.merchant_id:
                    from shared.db.session import current_tenant_id
                    current_tenant_id.set(payload.merchant_id)
            except Exception:
                request.state.user = None
        else:
            request.state.user = None

        return await call_next(request)


async def get_token_payload(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenPayload:
    """FastAPI dependency to enforce authentication and return the token payload."""
    user: TokenPayload | None = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
