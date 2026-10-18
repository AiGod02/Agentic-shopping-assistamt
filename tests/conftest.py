"""
Shared pytest configuration and fixtures for Agentic Commerce Protocol (ACP) test suite.
"""

import asyncio
import os
import sys
import pathlib
import uuid
from decimal import Decimal
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, delete, text

# Setup sys.path
project_root = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agent_server"))
sys.path.insert(0, str(project_root / "merchant_server"))
sys.path.insert(0, str(project_root / "payment_server"))
sys.path.insert(0, str(project_root / "shared"))

from agent_server.config import settings
from shared.db.session import init_db_engine, get_db_session, init_db_tables
from shared.auth.jwt_handler import JWTHandler
from merchant_server.domain.models.user import User
from merchant_server.domain.models.merchant import Merchant
from merchant_server.domain.models.listing import Listing
from merchant_server.domain.models.order import Order
from merchant_server.domain.models.payment import Payment

from merchant_server.main import app as merchant_app
from payment_server.main import app as payment_app
from agent_server.main import app as agent_app


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    engine = init_db_engine(os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/commerce_platform"))
    await init_db_tables(engine)
    async with get_db_session() as session:
        yield session


@pytest.fixture(scope="session")
def jwt_h():
    return JWTHandler(secret_key=settings.jwt_secret_key)


@pytest.fixture(scope="function")
def guest_token_factory(jwt_h):
    def _create(guest_id: str | None = None):
        uid = guest_id or str(uuid.uuid4())
        return jwt_h.create_access_token(user_id=uid, role="customer")
    return _create


@pytest_asyncio.fixture(scope="function")
async def merchant_setup(db_session, jwt_h):
    """Fixture providing Merchant A and Merchant B users, entities, tokens, listings, orders, and payments."""
    # Retrieve or create Merchant A
    res_m = await db_session.execute(select(Merchant).limit(2))
    merchants = res_m.scalars().all()

    if len(merchants) < 2:
        m_a_user = User(
            id=uuid.uuid4(),
            email=f"merch_a_{uuid.uuid4().hex[:4]}@test.com",
            password_hash="hash_a_test_pwd",
            full_name="Merchant A Owner",
            role="merchant",
        )
        db_session.add(m_a_user)
        await db_session.flush()

        m_a_entity = Merchant(
            id=uuid.uuid4(),
            user_id=m_a_user.id,
            business_name="Merchant A Store",
            business_type="retail",
            verification_status="verified",
            is_active=True,
        )
        db_session.add(m_a_entity)

        m_b_user = User(
            id=uuid.uuid4(),
            email=f"merch_b_{uuid.uuid4().hex[:4]}@test.com",
            password_hash="hash_b_test_pwd",
            full_name="Merchant B Owner",
            role="merchant",
        )
        db_session.add(m_b_user)
        await db_session.flush()

        m_b_entity = Merchant(
            id=uuid.uuid4(),
            user_id=m_b_user.id,
            business_name="Merchant B Store",
            business_type="retail",
            verification_status="verified",
            is_active=True,
        )
        db_session.add(m_b_entity)
        await db_session.commit()

        res_m = await db_session.execute(select(Merchant).limit(2))
        merchants = res_m.scalars().all()

    m_a = merchants[0]
    m_b = merchants[1]

    u_a_res = await db_session.execute(select(User).where(User.id == m_a.user_id))
    u_a = u_a_res.scalars().first()

    u_b_res = await db_session.execute(select(User).where(User.id == m_b.user_id))
    u_b = u_b_res.scalars().first()

    # Create tokens with proper merchant permissions
    perms = ["listings:read", "listings:write", "listings:delete", "orders:read", "orders:write", "analytics:read", "merchants:read", "payments:read", "payments:refund"]
    token_a = jwt_h.create_access_token(
        user_id=str(u_a.id),
        role="merchant",
        merchant_id=str(m_a.id),
        extra_claims={"permissions": perms},
    )
    token_b = jwt_h.create_access_token(
        user_id=str(u_b.id),
        role="merchant",
        merchant_id=str(m_b.id),
        extra_claims={"permissions": perms},
    )

    # Seed Listing A
    listing_a = Listing(
        id=uuid.uuid4(),
        merchant_id=m_a.id,
        type="product",
        title=f"Merchant A Listing {uuid.uuid4().hex[:4]}",
        description="Description A",
        base_price=100.00,
        currency="USD",
        status="active",
    )
    # Seed Listing B
    listing_b = Listing(
        id=uuid.uuid4(),
        merchant_id=m_b.id,
        type="product",
        title=f"Merchant B Listing {uuid.uuid4().hex[:4]}",
        description="Description B",
        base_price=200.00,
        currency="USD",
        status="active",
    )
    db_session.add(listing_a)
    db_session.add(listing_b)
    await db_session.flush()

    # Seed Order A and Order B
    order_a = Order(
        id=uuid.uuid4(),
        order_number=f"ORD-A-{uuid.uuid4().hex[:6].upper()}",
        user_id=u_a.id,
        status="pending_payment",
        subtotal=100.00,
        tax_amount=10.00,
        total_amount=110.00,
        currency="USD",
    )
    order_b = Order(
        id=uuid.uuid4(),
        order_number=f"ORD-B-{uuid.uuid4().hex[:6].upper()}",
        user_id=u_b.id,
        status="pending_payment",
        subtotal=200.00,
        tax_amount=20.00,
        total_amount=220.00,
        currency="USD",
    )
    db_session.add(order_a)
    db_session.add(order_b)
    await db_session.flush()

    # Seed Payment A linked to Order A
    gw_pay_a_id = f"pi_a_{uuid.uuid4().hex[:12]}"
    payment_a = Payment(
        id=uuid.uuid4(),
        order_id=order_a.id,
        user_id=u_a.id,
        gateway="stripe",
        gateway_payment_id=gw_pay_a_id,
        amount=Decimal("110.00"),
        currency="USD",
        status="pending",
        idempotency_key=f"pay-a-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(payment_a)
    await db_session.commit()

    return {
        "merchant_a": m_a,
        "merchant_b": m_b,
        "user_a": u_a,
        "user_b": u_b,
        "token_a": token_a,
        "token_b": token_b,
        "listing_a": listing_a,
        "listing_b": listing_b,
        "order_a": order_a,
        "order_b": order_b,
        "payment_a": payment_a,
        "gw_pay_a_id": gw_pay_a_id,
    }


@pytest_asyncio.fixture(scope="function")
async def merchant_client():
    async with AsyncClient(transport=ASGITransport(app=merchant_app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def payment_client():
    async with AsyncClient(transport=ASGITransport(app=payment_app), base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture(scope="function")
async def agent_client():
    async with AsyncClient(transport=ASGITransport(app=agent_app), base_url="http://test") as client:
        yield client
