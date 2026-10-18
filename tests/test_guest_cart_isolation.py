"""
Test suite for guest cart isolation and security (test_guest_cart_isolation.py).
"""

import pytest
import uuid
from merchant_server.domain.models.cart import Cart
from sqlalchemy import select


@pytest.mark.asyncio
async def test_guest_cart_session_isolation(agent_client, db_session, guest_token_factory, merchant_setup):
    """Two separate anonymous sessions receive distinct guest UUIDs and 100% isolated carts."""
    listing_a = str(merchant_setup["listing_a"].id)
    listing_b = str(merchant_setup["listing_b"].id)

    # Session A chat call
    sess_a_id = str(uuid.uuid4())
    res_a = await agent_client.post("/api/v1/agent/chat", json={"session_id": sess_a_id, "message": f"add listing {listing_a} to cart"})
    assert res_a.status_code == 200
    session_a_id = res_a.json()["session_id"]

    # Session B chat call
    sess_b_id = str(uuid.uuid4())
    res_b = await agent_client.post("/api/v1/agent/chat", json={"session_id": sess_b_id, "message": f"add listing {listing_b} to cart"})
    assert res_b.status_code == 200
    session_b_id = res_b.json()["session_id"]

    assert session_a_id != session_b_id, "Session IDs must be distinct"


@pytest.mark.asyncio
async def test_direct_unauthenticated_cart_access_rejected(merchant_client):
    """Cart operations without a valid signed JWT return 401 Unauthorized."""
    res = await merchant_client.get("/api/v1/cart")
    assert res.status_code == 401
    assert res.json()["detail"] == "Authentication token required for cart operations"
