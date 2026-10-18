"""
JWT Handler — production-grade token creation and verification.

Supports access tokens, refresh tokens, and token blacklisting via Redis.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pydantic import BaseModel

from shared.db.redis_client import get_redis


class TokenPayload(BaseModel):
    """Decoded JWT payload."""

    sub: str  # user ID
    role: str
    merchant_id: str | None = None
    jti: str  # unique token ID
    exp: datetime
    iat: datetime
    token_type: str  # access | refresh


class TokenPair(BaseModel):
    """Access + refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class JWTHandler:
    """Production JWT handler with Redis-backed blacklisting."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 30,
        refresh_token_expire_days: int = 7,
    ) -> None:
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days

    def create_access_token(
        self,
        user_id: str,
        role: str,
        merchant_id: str | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        """Create a short-lived access token."""
        if not self.secret_key:
            raise ValueError("JWT secret key must not be empty")
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=self.access_token_expire_minutes)
        payload = {
            "sub": user_id,
            "role": role,
            "jti": str(uuid.uuid4()),
            "exp": expires,
            "iat": now,
            "token_type": "access",
        }
        if merchant_id:
            payload["merchant_id"] = merchant_id
        if extra_claims:
            payload.update(extra_claims)
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(
        self,
        user_id: str,
        role: str,
        merchant_id: str | None = None,
    ) -> str:
        """Create a long-lived refresh token."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=self.refresh_token_expire_days)
        payload = {
            "sub": user_id,
            "role": role,
            "jti": str(uuid.uuid4()),
            "exp": expires,
            "iat": now,
            "token_type": "refresh",
        }
        if merchant_id:
            payload["merchant_id"] = merchant_id
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_token_pair(
        self,
        user_id: str,
        role: str,
        merchant_id: str | None = None,
    ) -> TokenPair:
        """Create both access and refresh tokens."""
        return TokenPair(
            access_token=self.create_access_token(user_id, role, merchant_id),
            refresh_token=self.create_refresh_token(user_id, role, merchant_id),
            expires_in=self.access_token_expire_minutes * 60,
        )

    def decode_token(self, token: str) -> TokenPayload:
        """Decode and validate a JWT token. Raises jwt.exceptions on failure."""
        payload = jwt.decode(
            token,
            self.secret_key,
            algorithms=[self.algorithm],
            options={"require": ["sub", "role", "jti", "exp", "iat", "token_type"]},
        )
        return TokenPayload(**payload)

    async def blacklist_token(self, token_payload: TokenPayload) -> None:
        """Add token JTI to Redis blacklist until expiry."""
        redis = await get_redis()
        ttl = int((token_payload.exp - datetime.now(timezone.utc)).total_seconds())
        if ttl > 0:
            await redis.setex(f"token:blacklist:{token_payload.jti}", ttl, "1")

    async def is_blacklisted(self, jti: str) -> bool:
        """Check if a token JTI is blacklisted."""
        redis = await get_redis()
        res = await redis.exists(f"token:blacklist:{jti}")
        return bool(res)

    async def verify_token(self, token: str) -> TokenPayload:
        """Full verification: decode + blacklist check."""
        payload = self.decode_token(token)
        if await self.is_blacklisted(payload.jti):
            raise jwt.InvalidTokenError("Token has been revoked")
        return payload
