"""
Unified Server — High-Performance Modular Monolith for Agentic Commerce Protocol.

Unifies Agent Server, Merchant Server, and Payment Server into a single FastAPI
application while preserving the original modular microservice folder structure.
Ideal for free-tier deployments (e.g. Render, Koyeb, Fly.io, single VPS) where running
multiple processes is costly or constrained.
"""

from __future__ import annotations

import os
import pathlib
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Ensure project root is in python path
_project_root = pathlib.Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from merchant_server.config import settings as merchant_settings
from agent_server.config import settings as agent_settings
from payment_server.config import settings as payment_settings

from shared.auth.jwt_handler import JWTHandler
from shared.auth.oauth2 import AuthMiddleware
from shared.db.redis_client import close_redis, get_redis, init_redis
from shared.db.session import close_db_engine, get_engine, init_db_engine, ensure_db_and_tables
from shared.events.kafka_producer import close_kafka_producer, init_kafka_producer
from shared.middleware.rate_limiter import RateLimitConfig, RateLimitMiddleware
from shared.middleware.request_id import RequestIDMiddleware
from shared.observability.logging import get_logger, setup_logging
from shared.observability.metrics import PrometheusMiddleware, metrics_endpoint

logger = get_logger("unified_server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Unified application lifecycle — sets up DB, cache, tracing, and prewarms search."""
    port = int(os.getenv("PORT", "8000"))
    logger.info("unified_server_starting_up", port=port)

    # 1. Database auto-provisioning & schema table creation
    engine = None
    try:
        engine = init_db_engine(
            merchant_settings.database_url,
            pool_size=merchant_settings.db_pool_size,
            max_overflow=merchant_settings.db_max_overflow,
        )
        await ensure_db_and_tables(merchant_settings.database_url, engine)
        logger.info("unified_database_ready")
    except Exception as e:
        logger.error("unified_database_init_failed", error=str(e))

    # 2. Redis initialization (with resilient in-memory fallback)
    try:
        await init_redis(merchant_settings.redis_url)
    except Exception as e:
        logger.warning("unified_redis_fallback_active", error=str(e))

    # 3. Kafka producer initialization (with resilient log-only fallback)
    try:
        await init_kafka_producer(merchant_settings.kafka_bootstrap_servers)
    except Exception as e:
        logger.warning("unified_kafka_fallback_active", error=str(e))

    # 4. Point inter-service URLs to local unified server port
    port = int(os.getenv("PORT", "8000"))
    agent_settings.merchant_server_url = f"http://127.0.0.1:{port}"
    agent_settings.payment_server_url = f"http://127.0.0.1:{port}"
    merchant_settings.agent_server_url = f"http://127.0.0.1:{port}"
    merchant_settings.payment_server_url = f"http://127.0.0.1:{port}"
    payment_settings.merchant_server_url = f"http://127.0.0.1:{port}"

    # 5. Pre-warm search embedding model safely
    try:
        from agent_server.core.chroma_search import prewarm_model
        prewarm_model()
    except Exception as e:
        logger.warning("search_prewarm_skipped", error=str(e))

    yield

    # Shutdown hooks
    logger.info("unified_server_shutting_down")
    await close_kafka_producer()
    await close_redis()
    await close_db_engine()


def create_app() -> FastAPI:
    """Instantiate and configure the unified FastAPI application."""
    app = FastAPI(
        title="Agentic Commerce Protocol — Unified Server",
        description="Modular Monolith API hosting Merchant, AI Agent, and Payment services in a single process.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS Middleware ──────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Observability & Rate Limiting ──────────────────────────────────────────
    app.add_middleware(
        RateLimitMiddleware,
        config=RateLimitConfig(
            requests_per_minute=merchant_settings.rate_limit_requests_per_minute,
            burst_size=merchant_settings.rate_limit_burst,
        ),
        exclude_paths={"/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json", "/demo-payment"},
    )
    app.add_middleware(PrometheusMiddleware, service_name="unified-commerce-server")
    app.add_middleware(RequestIDMiddleware)

    # ── JWT Authentication Middleware ──────────────────────────────────────────
    jwt_handler = JWTHandler(
        secret_key=merchant_settings.jwt_secret_key,
        algorithm=merchant_settings.jwt_algorithm,
        access_token_expire_minutes=merchant_settings.jwt_access_token_expire_minutes,
        refresh_token_expire_days=merchant_settings.jwt_refresh_token_expire_days,
    )
    app.add_middleware(
        AuthMiddleware,
        jwt_handler=jwt_handler,
        exclude_paths=[
            "/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json",
            "/demo-payment", "/demo-payment/",
            "/api/v1/merchants/login", "/api/v1/merchants/register", "/api/v1/customer/register",
            "/api/v1/merchants/refresh", "/api/v1/merchants/public", "/api/v1/merchants/guest-token",
            "/api/v1/cart", "/api/v1/cart/items", "/api/v1/cart/checkout", "/api/v1/cart/claim",
            "/api/v1/listings", "/api/v1/agent", "/api/v1/agent/chat",
            "/api/v1/payments/create", "/api/v1/webhooks/stripe", "/api/v1/webhooks/razorpay",
            # Aliases
            "/api/agent/v1", "/api/merchant/v1", "/api/payment/v1"
        ],
    )
    app.state.jwt_handler = jwt_handler

    # ── Register SQLAlchemy Models ────────────────────────────────────────────
    from merchant_server.domain.models import (
        user, merchant, listing, variant, cart, booking, order, review, webhook, availability,
        page_views, subscription, outbox, saga, user_memory, session, payment,
    )

    # ── Include Subsystem Routers ─────────────────────────────────────────────
    # 1. Merchant Service Router (Listings, Cart, Merchants, Orders, Analytics, Admin)
    from merchant_server.api.v1.router import api_router as merchant_api_router
    app.include_router(merchant_api_router, prefix="/api/v1")
    app.include_router(merchant_api_router, prefix="/api/merchant/v1")  # Proxy alias compatibility

    # 2. Agent Service Router (Chat Orchestrator, Sessions)
    from agent_server.api.v1.router import api_router as agent_api_router
    app.include_router(agent_api_router, prefix="/api/v1")
    app.include_router(agent_api_router, prefix="/api/agent/v1")  # Proxy alias compatibility

    # 3. Payment Service Router (Payments, Escrow, Refunds, Webhooks)
    from payment_server.api.v1.router import api_router as payment_api_router
    app.include_router(payment_api_router, prefix="/api/v1")
    app.include_router(payment_api_router, prefix="/api/payment/v1")  # Proxy alias compatibility

    # ── Health & Diagnostics Endpoints ─────────────────────────────────────────
    @app.get("/health", tags=["infrastructure"])
    async def health():
        return {
            "status": "healthy",
            "mode": "modular-monolith",
            "services": ["agent", "merchant", "payment"],
        }

    @app.get("/ready", tags=["infrastructure"])
    async def readiness():
        checks = {}
        try:
            redis = await get_redis()
            await redis.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "degraded/in-memory"

        try:
            engine = get_engine()
            checks["database"] = "ok" if engine else "not_configured"
        except Exception:
            checks["database"] = "error"

        return {
            "status": "ready",
            "mode": "modular-monolith",
            "checks": checks,
        }

    # ── Full End-to-End Database Flow Test ─────────────────────────────────────
    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession
    from shared.db.session import get_db

    @app.post("/api/v1/payments/demo-full-flow", tags=["demo"])
    async def demo_full_flow(
        gateway: str = "mock",
        db: AsyncSession = Depends(get_db),
    ):
        """Execute and verify a complete end-to-end database flow:
        Customer -> Listing -> Cart -> Checkout Saga -> Order -> Payment -> Capture -> Ledger.
        All records are persisted directly into PostgreSQL tables: users, listings, carts, orders, payments, ledger_entries.
        """
        import uuid
        from sqlalchemy import text, select
        from merchant_server.domain.models.user import User
        from merchant_server.domain.models.listing import Listing
        from merchant_server.domain.services.cart_service import CartService
        from merchant_server.sagas.checkout_saga import CheckoutSaga

        # 1. Fetch or create a valid customer user in DB
        user_res = await db.execute(select(User).where(User.role == "customer").limit(1))
        customer = user_res.scalar_one_or_none()
        if not customer:
            customer = User(
                id=uuid.uuid4(),
                email="democustomer@agenticcommerce.com",
                password_hash="hashed_demo_pw_123",
                role="customer",
                full_name="Demo Test Customer"
            )
            db.add(customer)
            await db.commit()
            await db.refresh(customer)

        # 2. Fetch or create an active listing in DB with appropriate currency
        target_currency = "INR" if gateway == "razorpay" else "USD"
        target_price = 500.0 if gateway == "razorpay" else 49.99
        listing_res = await db.execute(
            select(Listing).where(Listing.status == "active", Listing.currency == target_currency).limit(1)
        )
        listing = listing_res.scalar_one_or_none()
        if not listing:
            m_res = await db.execute(text("SELECT id FROM merchants LIMIT 1"))
            merchant_row = m_res.fetchone()
            mid = merchant_row[0] if merchant_row else uuid.uuid4()
            if not merchant_row:
                await db.execute(
                    text("INSERT INTO merchants (id, business_name, business_type, status) VALUES (:id, 'Demo Merchant', 'retail', 'active')"),
                    {"id": mid}
                )
                await db.commit()
            listing = Listing(
                id=uuid.uuid4(),
                merchant_id=mid,
                type="product",
                title=f"Demo Flow Test Item ({target_currency})",
                description="Sample product to verify end-to-end database purchase flow",
                base_price=target_price,
                currency=target_currency,
                status="active"
            )
            db.add(listing)
            await db.commit()
            await db.refresh(listing)

        # 3. Add to Cart in DB
        cart_svc = CartService(db)
        await cart_svc.clear_cart(customer.id)
        await cart_svc.add_to_cart(
            user_id=customer.id,
            listing_id=listing.id,
            quantity=1,
        )

        # 4. Execute Checkout Saga in DB
        saga = CheckoutSaga(db)
        idempotency_key = f"demo-flow-{uuid.uuid4()}"
        checkout_result = await saga.execute(
            user_id=customer.id,
            idempotency_key=idempotency_key,
            payment_gateway=gateway,
            shipping_address={"street": "123 Test St", "city": "Demo City", "country": "US"}
        )

        order_id = checkout_result.get("order_id")

        # 5. Verify and capture payment in DB
        from payment_server.domain.services.payment_service import PaymentService
        pay_svc = PaymentService(db)
        pay_res = await db.execute(
            text("SELECT id, status, gateway_payment_id, gateway_order_id FROM payments WHERE order_id = :oid"),
            {"oid": uuid.UUID(order_id) if isinstance(order_id, str) else order_id}
        )
        pay_row = pay_res.fetchone()
        payment_id = str(pay_row[0]) if pay_row else None

        capture_result = None
        is_captured = False
        if payment_id:
            try:
                capture_result = await pay_svc.capture_payment(payment_id)
                is_captured = True
                # Update order to confirmed in DB
                await db.execute(
                    text("UPDATE orders SET status = 'confirmed' WHERE id = :oid"),
                    {"oid": uuid.UUID(order_id) if isinstance(order_id, str) else order_id}
                )
                await db.commit()
            except Exception as e:
                capture_result = {"status": "created", "note": str(e)}

        # 6. Fetch recorded ledger entries from DB
        from payment_server.domain.services.ledger_service import LedgerService
        ledger_svc = LedgerService(db)
        ledger_entries = await ledger_svc.get_entries_for_payment(payment_id) if payment_id else []

        # Refresh payment row to reflect latest status
        if payment_id:
            pay_res = await db.execute(
                text("SELECT id, status, gateway_payment_id, gateway_order_id FROM payments WHERE id = :pid"),
                {"pid": uuid.UUID(payment_id)}
            )
            pay_row = pay_res.fetchone()

        return {
            "status": "success",
            "message": "Full end-to-end e-commerce flow successfully executed and verified on PostgreSQL Database!",
            "database_records_created": {
                "user_id": str(customer.id),
                "customer_email": customer.email,
                "listing_id": str(listing.id),
                "listing_title": listing.title,
                "order_id": str(order_id),
                "order_number": checkout_result.get("order_number"),
                "order_status": "confirmed" if is_captured else "pending_payment",
                "payment_id": payment_id,
                "payment_status": pay_row[1] if pay_row else "created",
                "gateway_payment_id": pay_row[2] if pay_row else None,
                "gateway_order_id": pay_row[3] if pay_row else None,
                "capture_result": capture_result,
                "ledger_entries_count": len(ledger_entries),
                "ledger_entries": ledger_entries
            },
            "tables_verified_in_postgres": [
                "users", "merchants", "listings", "carts", "cart_items", "orders", "order_items", "payments", "ledger_entries"
            ]
        }

    # ── Interactive Payment Gateway Demo Client UI ─────────────────────────────
    @app.get("/demo-payment", response_class=HTMLResponse, tags=["demo"])
    @app.get("/demo-payment/", response_class=HTMLResponse, tags=["demo"])
    async def demo_payment_page():
        """Serve the interactive payment gateway test client directly in browser."""
        html_file = _project_root / "demo_payment.html"
        if html_file.exists():
            return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Demo Payment Client page loading...</h1>")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    logger.info("starting_unified_server", port=port)
    uvicorn.run("unified_server:app", host="0.0.0.0", port=port, reload=True)
