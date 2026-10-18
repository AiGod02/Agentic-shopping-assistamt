"""
Circuit Breaker — distributed circuit breaker pattern backed by Redis.

States: CLOSED → OPEN → HALF_OPEN → CLOSED
Prevents cascading failures in inter-service calls.
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable, TypeVar

from shared.db.redis_client import get_redis

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerError(Exception):
    """Raised when the circuit is open and calls are rejected."""

    def __init__(self, service_name: str, retry_after: float) -> None:
        self.service_name = service_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit breaker OPEN for '{service_name}'. Retry after {retry_after:.1f}s"
        )


class CircuitBreakerConfig:
    """Configuration for a circuit breaker."""

    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 3,
        timeout_seconds: float = 30.0,
        half_open_max_calls: int = 3,
        excluded_exceptions: tuple[type[Exception], ...] | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout_seconds = timeout_seconds
        self.half_open_max_calls = half_open_max_calls
        self.excluded_exceptions = excluded_exceptions or ()


class CircuitBreaker:
    """Redis-backed distributed circuit breaker.

    Usage:
        cb = CircuitBreaker("payment-service", config)

        # As context manager
        async with cb:
            result = await call_payment_service()

        # As decorator
        @cb.protect
        async def call_payment_service():
            ...
    """

    def __init__(self, service_name: str, config: CircuitBreakerConfig | None = None) -> None:
        self.service_name = service_name
        self.config = config or CircuitBreakerConfig()
        self._key_prefix = f"circuit_breaker:{service_name}"

    @property
    def _state_key(self) -> str:
        return f"{self._key_prefix}:state"

    @property
    def _failure_count_key(self) -> str:
        return f"{self._key_prefix}:failures"

    @property
    def _success_count_key(self) -> str:
        return f"{self._key_prefix}:successes"

    @property
    def _last_failure_key(self) -> str:
        return f"{self._key_prefix}:last_failure"

    @property
    def _half_open_calls_key(self) -> str:
        return f"{self._key_prefix}:half_open_calls"

    async def get_state(self) -> CircuitState:
        """Get current circuit state from Redis."""
        redis = await get_redis()
        state = await redis.get(self._state_key)
        if state is None:
            return CircuitState.CLOSED
        return CircuitState(state)

    async def _set_state(self, state: CircuitState) -> None:
        redis = await get_redis()
        ttl = int(self.config.timeout_seconds * 3)  # Keep state for a while
        await redis.setex(self._state_key, ttl, state.value)

    async def _record_failure(self) -> None:
        redis = await get_redis()
        pipe = redis.pipeline()
        pipe.incr(self._failure_count_key)
        pipe.expire(self._failure_count_key, int(self.config.timeout_seconds * 2))
        pipe.set(self._last_failure_key, str(time.time()))
        pipe.expire(self._last_failure_key, int(self.config.timeout_seconds * 2))
        results = await pipe.execute()
        failure_count = results[0]

        current_state = await self.get_state()
        if current_state == CircuitState.CLOSED:
            if failure_count >= self.config.failure_threshold:
                await self._set_state(CircuitState.OPEN)
                # Reset counters
                await redis.delete(self._failure_count_key, self._success_count_key)
        elif current_state == CircuitState.HALF_OPEN:
            # Any failure in half-open → back to open
            await self._set_state(CircuitState.OPEN)
            await redis.delete(
                self._failure_count_key,
                self._success_count_key,
                self._half_open_calls_key,
            )

    async def _record_success(self) -> None:
        redis = await get_redis()
        current_state = await self.get_state()

        if current_state == CircuitState.HALF_OPEN:
            success_count = await redis.incr(self._success_count_key)
            if success_count >= self.config.success_threshold:
                await self._set_state(CircuitState.CLOSED)
                await redis.delete(
                    self._failure_count_key,
                    self._success_count_key,
                    self._half_open_calls_key,
                )
        elif current_state == CircuitState.CLOSED:
            # Reset failure count on success in closed state
            await redis.delete(self._failure_count_key)

    async def _can_execute(self) -> bool:
        """Check if execution is allowed in current state."""
        state = await self.get_state()

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            redis = await get_redis()
            last_failure = await redis.get(self._last_failure_key)
            if last_failure:
                elapsed = time.time() - float(last_failure)
                if elapsed >= self.config.timeout_seconds:
                    await self._set_state(CircuitState.HALF_OPEN)
                    await redis.delete(self._half_open_calls_key)
                    return True
            return False

        if state == CircuitState.HALF_OPEN:
            redis = await get_redis()
            current_calls = await redis.incr(self._half_open_calls_key)
            await redis.expire(
                self._half_open_calls_key, int(self.config.timeout_seconds)
            )
            return current_calls <= self.config.half_open_max_calls

        return False

    async def _get_retry_after(self) -> float:
        redis = await get_redis()
        last_failure = await redis.get(self._last_failure_key)
        if last_failure:
            elapsed = time.time() - float(last_failure)
            return max(0, self.config.timeout_seconds - elapsed)
        return self.config.timeout_seconds

    async def execute(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Execute a function with circuit breaker protection."""
        if not await self._can_execute():
            retry_after = await self._get_retry_after()
            raise CircuitBreakerError(self.service_name, retry_after)

        try:
            result = await func(*args, **kwargs)
            await self._record_success()
            return result
        except self.config.excluded_exceptions:
            # Excluded exceptions don't count as failures
            raise
        except Exception:
            await self._record_failure()
            raise

    def protect(self, func: Callable) -> Callable:
        """Decorator to protect an async function with the circuit breaker."""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.execute(func, *args, **kwargs)

        return wrapper

    async def __aenter__(self):
        if not await self._can_execute():
            retry_after = await self._get_retry_after()
            raise CircuitBreakerError(self.service_name, retry_after)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            await self._record_success()
        elif not isinstance(exc_val, self.config.excluded_exceptions):
            await self._record_failure()
        return False
