"""
Rate Limiter — token bucket with Redis or in-memory backend.

Automatically uses in-memory rate limiting when Redis is unavailable.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable

from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from shared.observability.logging import get_logger

logger = get_logger(__name__)

# Lua script for atomic token bucket in Redis
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])  -- tokens per second
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = max_tokens
    last_refill = now
end

-- Refill tokens based on elapsed time
local elapsed = now - last_refill
local new_tokens = elapsed * refill_rate
tokens = math.min(max_tokens, tokens + new_tokens)

if tokens < requested then
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, math.ceil(max_tokens / refill_rate) + 1)
    return {0, tokens, math.ceil((requested - tokens) / refill_rate)}
end

tokens = tokens - requested
redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
redis.call('EXPIRE', key, math.ceil(max_tokens / refill_rate) + 1)
return {1, tokens, 0}
"""


class RateLimitConfig:
    def __init__(
        self,
        requests_per_minute: int = 60,
        burst_size: int = 10,
        key_prefix: str = "ratelimit",
    ) -> None:
        self.max_tokens = burst_size
        self.refill_rate = requests_per_minute / 60.0
        self.key_prefix = key_prefix


class RateLimiter:
    """Rate limiter — uses Redis when available, in-memory otherwise."""

    def __init__(self, config: RateLimitConfig) -> None:
        self.config = config
        self._script_sha: str | None = None
        # In-memory fallback buckets
        self._buckets: dict[str, dict] = defaultdict(
            lambda: {"tokens": config.max_tokens, "last_refill": time.time()}
        )

    def _get_key(self, identifier: str) -> str:
        return f"{self.config.key_prefix}:{identifier}"

    async def check_rate_limit(self, identifier: str) -> tuple[bool, int, int]:
        """Check if request is allowed. Works with or without Redis."""
        try:
            from shared.db.redis_client import get_redis, is_using_fallback
            if not is_using_fallback():
                redis = await get_redis()
                return await self._check_redis(redis, identifier)
        except Exception:
            pass

        # In-memory fallback
        return self._check_memory(identifier)

    async def _check_redis(self, redis, identifier: str) -> tuple[bool, int, int]:
        if self._script_sha is None:
            self._script_sha = await redis.script_load(TOKEN_BUCKET_SCRIPT)

        now = time.time()
        result = await redis.evalsha(
            self._script_sha, 1, self._get_key(identifier),
            str(self.config.max_tokens), str(self.config.refill_rate),
            str(now), "1",
        )
        return bool(result[0]), int(float(result[1])), int(result[2])

    def _check_memory(self, identifier: str) -> tuple[bool, int, int]:
        now = time.time()
        bucket = self._buckets[identifier]

        elapsed = now - bucket["last_refill"]
        new_tokens = elapsed * self.config.refill_rate
        bucket["tokens"] = min(self.config.max_tokens, bucket["tokens"] + new_tokens)
        bucket["last_refill"] = now

        if bucket["tokens"] < 1:
            retry_after = int((1 - bucket["tokens"]) / self.config.refill_rate)
            return False, 0, retry_after

        bucket["tokens"] -= 1
        return True, int(bucket["tokens"]), 0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for rate limiting — works without Redis."""

    def __init__(
        self,
        app,
        config: RateLimitConfig | None = None,
        key_func: Callable[[Request], str] | None = None,
        exclude_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.limiter = RateLimiter(config or RateLimitConfig())
        self.key_func = key_func or self._default_key
        self.exclude_paths = exclude_paths or {"/health", "/ready", "/metrics"}

    @staticmethod
    def _default_key(request: Request) -> str:
        user = getattr(request.state, "user", None)
        if user:
            return f"user:{user.sub}"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        client = request.client
        return f"ip:{client.host if client else 'unknown'}"

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        identifier = self.key_func(request)
        allowed, remaining, retry_after = await self.limiter.check_rate_limit(identifier)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
