"""
Payment Server — FastAPI application entry point.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from payment_server.config import settings
from shared.auth.jwt_handler import JWTHandler
from shared.auth.oauth2 import AuthMiddleware
from shared.db.redis_client import close_redis, get_redis, init_redis
from shared.db.session import close_db_engine, get_engine, init_db_engine
from shared.events.kafka_producer import close_kafka_producer, init_kafka_producer
from shared.middleware.rate_limiter import RateLimitConfig, RateLimitMiddleware
from shared.middleware.request_id import RequestIDMiddleware
from shared.observability.logging import setup_logging
from shared.observability.metrics import PrometheusMiddleware, metrics_endpoint
from shared.observability.tracing import (
    instrument_fastapi, instrument_httpx, instrument_redis,
    instrument_sqlalchemy, setup_tracing,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.app_name, settings.log_level, json_format=settings.environment != "development")

    engine = None
    try:
        from shared.db.session import ensure_db_and_tables
        engine = init_db_engine(settings.database_url, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow)
        await ensure_db_and_tables(settings.database_url, engine)
    except Exception as e:
        from shared.observability.logging import get_logger
        get_logger(__name__).error("database_init_failed", error=str(e))

    await init_redis(settings.redis_url)
    await init_kafka_producer(settings.kafka_bootstrap_servers)

    try:
        if settings.environment != "test" and engine:
            tp = setup_tracing(settings.app_name, settings.otel_exporter_otlp_endpoint, settings.environment)
            if tp:
                instrument_fastapi(app, tp)
                instrument_sqlalchemy(engine, tp)
                instrument_redis(tp)
                instrument_httpx(tp)
    except Exception:
        pass

    # Init Stripe (only if key provided)
    if settings.stripe_secret_key:
        try:
            import stripe
            stripe.api_key = settings.stripe_secret_key
        except ImportError:
            pass

    # Start transactional outbox worker task
    import asyncio
    from shared.events.kafka_producer import process_outbox_events
    from shared.db.session import get_db_session

    async def outbox_worker():
        from shared.observability.logging import get_logger
        worker_logger = get_logger("outbox_worker")
        worker_logger.info("outbox_worker_started")
        while True:
            try:
                async with get_db_session() as db:
                    processed = await process_outbox_events(db)
                    if processed > 0:
                        worker_logger.info("outbox_processed_events", count=processed)
            except Exception as ex:
                worker_logger.error("outbox_worker_error", error=str(ex))
            await asyncio.sleep(5)

    outbox_task = asyncio.create_task(outbox_worker())

    yield

    outbox_task.cancel()
    try:
        await outbox_task
    except asyncio.CancelledError:
        pass

    await close_kafka_producer()
    await close_redis()
    await close_db_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Payment Server",
        description="Universal Agentic Commerce — Payment API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.environment != "production" else None,
    )

    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(
        RateLimitMiddleware,
        config=RateLimitConfig(requests_per_minute=settings.rate_limit_requests_per_minute, burst_size=settings.rate_limit_burst),
        exclude_paths={"/health", "/ready", "/metrics", "/api/v1/webhooks/stripe", "/api/v1/webhooks/razorpay"},
    )
    app.add_middleware(PrometheusMiddleware, service_name=settings.app_name)
    app.add_middleware(RequestIDMiddleware)

    jwt_handler = JWTHandler(secret_key=settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    app.add_middleware(
        AuthMiddleware, jwt_handler=jwt_handler,
        exclude_paths=["/health", "/ready", "/metrics", "/docs", "/openapi.json",
                       "/api/v1/payments/create", "/api/v1/webhooks/stripe", "/api/v1/webhooks/razorpay"],
    )

    from payment_server.api.v1.router import api_router
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": settings.app_name}

    @app.get("/ready")
    async def ready():
        checks = {}
        try:
            redis = await get_redis()
            await redis.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "error"
        try:
            get_engine()
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "error"
        all_ok = all(v == "ok" for v in checks.values())
        return {"status": "ready" if all_ok else "degraded", "checks": checks}

    @app.get("/metrics")
    async def metrics():
        return Response(content=metrics_endpoint(), media_type="text/plain")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("payment_server.main:app", host=settings.host, port=settings.port, reload=True)
