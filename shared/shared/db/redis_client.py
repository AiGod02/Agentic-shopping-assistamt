"""
Redis Client — async Redis connection pool with in-memory fallback.

When Redis is unavailable, automatically falls back to an in-memory dict
so the platform can run without any external infrastructure.
"""

from __future__ import annotations

import time
from typing import Any

from shared.observability.logging import get_logger

logger = get_logger(__name__)

_redis: Any = None
_pool: Any = None
_using_fallback = False


class InMemoryPipeline:
    """Mock Redis pipeline for in-memory fallback client."""

    def __init__(self, db: InMemoryRedis) -> None:
        self.db = db
        self.calls = []

    def incr(self, key: str) -> InMemoryPipeline:
        self.calls.append(lambda: self.db.incr(key))
        return self

    def incrby(self, key: str, amount: int) -> InMemoryPipeline:
        self.calls.append(lambda: self.db.incrby(key, amount))
        return self

    def set(self, key: str, value: str) -> InMemoryPipeline:
        self.calls.append(lambda: self.db.set(key, value))
        return self

    def setex(self, key: str, ttl: int, value: str) -> InMemoryPipeline:
        self.calls.append(lambda: self.db.setex(key, ttl, value))
        return self

    def expire(self, key: str, ttl: int) -> InMemoryPipeline:
        self.calls.append(lambda: self.db.expire(key, ttl))
        return self

    def delete(self, *keys: str) -> InMemoryPipeline:
        self.calls.append(lambda: self.db.delete(*keys))
        return self

    async def execute(self) -> list[Any]:
        results = []
        for call in self.calls:
            res = await call()
            results.append(res)
        return results


class InMemoryRedis:
    """In-memory Redis replacement for development/testing without Redis.

    Supports the subset of Redis commands used by the platform:
    get, set, setex, delete, ping, hmset, hmget, scan_iter, expire,
    evalsha, script_load, incr, incrby, ttl, exists.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._expiry: dict[str, float] = {}
        self._scripts: dict[str, str] = {}

    def pipeline(self) -> InMemoryPipeline:
        return InMemoryPipeline(self)

    def _is_expired(self, key: str) -> bool:
        if key in self._expiry and time.time() > self._expiry[key]:
            self._store.pop(key, None)
            self._expiry.pop(key, None)
            return True
        return False

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        self._is_expired(key)
        return self._store.get(key)

    async def set(self, key: str, value: str, **kwargs) -> None:
        self._store[key] = value

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value
        self._expiry[key] = time.time() + ttl

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                self._expiry.pop(key, None)
                count += 1
        return count

    async def exists(self, key: str) -> bool:
        self._is_expired(key)
        return key in self._store

    async def incr(self, key: str) -> int:
        self._is_expired(key)
        val = int(self._store.get(key, 0)) + 1
        self._store[key] = str(val)
        return val

    async def incrby(self, key: str, amount: int) -> int:
        self._is_expired(key)
        val = int(self._store.get(key, 0)) + amount
        self._store[key] = str(val)
        return val

    async def ttl(self, key: str) -> int:
        if key in self._expiry:
            remaining = self._expiry[key] - time.time()
            return max(0, int(remaining))
        return -1

    async def expire(self, key: str, ttl: int) -> None:
        self._expiry[key] = time.time() + ttl

    async def hmset(self, key: str, mapping: dict | None = None, **kwargs) -> None:
        self._is_expired(key)
        if key not in self._store or not isinstance(self._store[key], dict):
            self._store[key] = {}
        if mapping:
            self._store[key].update(mapping)
        self._store[key].update(kwargs)

    async def hmget(self, key: str, *fields: str) -> list:
        self._is_expired(key)
        data = self._store.get(key, {})
        if isinstance(data, dict):
            return [data.get(f) for f in fields]
        return [None] * len(fields)

    async def hset(self, key: str, field: str = None, value: str = None, mapping: dict = None) -> None:
        self._is_expired(key)
        if key not in self._store or not isinstance(self._store[key], dict):
            self._store[key] = {}
        if field and value is not None:
            self._store[key][field] = value
        if mapping:
            self._store[key].update(mapping)

    async def hget(self, key: str, field: str) -> str | None:
        self._is_expired(key)
        data = self._store.get(key, {})
        if isinstance(data, dict):
            return data.get(field)
        return None

    async def hgetall(self, key: str) -> dict:
        self._is_expired(key)
        data = self._store.get(key, {})
        return data if isinstance(data, dict) else {}

    async def script_load(self, script: str) -> str:
        sha = str(hash(script))
        self._scripts[sha] = script
        return sha

    async def evalsha(self, sha: str, numkeys: int, *args) -> list:
        # Simplified token bucket for rate limiting
        key = args[0] if args else ""
        max_tokens = float(args[1]) if len(args) > 1 else 10
        return [1, max_tokens, 0]  # Always allow in dev mode

    async def scan_iter(self, match: str = "*"):
        import fnmatch
        for key in list(self._store.keys()):
            if not self._is_expired(key) and fnmatch.fnmatch(key, match):
                yield key

    async def aclose(self) -> None:
        self._store.clear()
        self._expiry.clear()


async def init_redis(
    redis_url: str = "redis://localhost:6379/0",
    max_connections: int = 50,
    decode_responses: bool = True,
) -> Any:
    """Initialize Redis — falls back to in-memory if Redis is unavailable."""
    global _redis, _pool, _using_fallback

    try:
        from redis.asyncio import Redis, ConnectionPool

        _pool = ConnectionPool.from_url(
            redis_url,
            max_connections=max_connections,
            decode_responses=decode_responses,
        )
        _redis = Redis(connection_pool=_pool)
        await _redis.ping()
        _using_fallback = False
        logger.info("redis_connected", url=redis_url.split("@")[-1])
    except Exception as e:
        logger.warning("redis_unavailable_using_memory_fallback", error=str(e))
        _redis = InMemoryRedis()
        _pool = None
        _using_fallback = True

    return _redis


async def get_redis() -> Any:
    """Get the Redis client (real or in-memory fallback)."""
    if _redis is None:
        # Auto-init with fallback if not initialized
        return await init_redis()
    return _redis


def is_using_fallback() -> bool:
    """Check if using in-memory fallback instead of real Redis."""
    return _using_fallback


async def close_redis() -> None:
    """Close Redis connections."""
    global _redis, _pool, _using_fallback
    if _redis:
        await _redis.aclose()
        _redis = None
    if _pool:
        await _pool.disconnect()
        _pool = None
    _using_fallback = False
    logger.info("redis_disconnected")


class RedisCache:
    """High-level caching utilities — works with both real Redis and fallback."""

    def __init__(self, prefix: str = "", ttl: int = 300) -> None:
        self.prefix = prefix
        self.ttl = ttl

    def _key(self, key: str) -> str:
        return f"{self.prefix}:{key}" if self.prefix else key

    async def get(self, key: str) -> str | None:
        redis = await get_redis()
        value = await redis.get(self._key(key))
        return value

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        redis = await get_redis()
        await redis.setex(self._key(key), ttl or self.ttl, value)

    async def delete(self, key: str) -> None:
        redis = await get_redis()
        await redis.delete(self._key(key))

    async def invalidate_pattern(self, pattern: str) -> int:
        redis = await get_redis()
        full_pattern = self._key(pattern)
        count = 0
        async for key in redis.scan_iter(match=full_pattern):
            await redis.delete(key)
            count += 1
        return count
