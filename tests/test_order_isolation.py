"""
Test suite for order isolation and IDOR protection (test_order_isolation.py).
"""

import pytest
import uuid
from merchant_server.domain.repositories.order_repo import OrderRepository


@pytest.mark.asyncio
async def test_merchant_orders_listing_isolation(merchant_client, merchant_setup):
    """Merchant A order list never includes Merchant B's orders."""
    headers_a = {"Authorization": f"Bearer {merchant_setup['token_a']}"}
    headers_b = {"Authorization": f"Bearer {merchant_setup['token_b']}"}

    res_a = await merchant_client.get("/api/v1/orders", headers=headers_a)
    assert res_a.status_code == 200
    orders_a_ids = {o["id"] for o in res_a.json().get("items", [])}

    order_b_id = str(merchant_setup["order_b"].id)
    assert order_b_id not in orders_a_ids, "Merchant A order list contains Merchant B order!"


@pytest.mark.asyncio
async def test_merchant_order_by_id_idor(merchant_client, merchant_setup):
    """Merchant A fetching Merchant B's order directly by ID returns 403 or 404."""
    headers_a = {"Authorization": f"Bearer {merchant_setup['token_a']}"}
    order_b_id = str(merchant_setup["order_b"].id)

    res = await merchant_client.get(f"/api/v1/orders/{order_b_id}", headers=headers_a)
    assert res.status_code in (403, 404), f"Expected 403 or 404 for IDOR fetch, got {res.status_code}"


@pytest.mark.asyncio
async def test_order_repository_query_level_scoping(db_session, merchant_setup):
    """Assert OrderRepository methods enforce merchant_id filter at the query level."""
    repo = OrderRepository(db_session)
    m_a_id = merchant_setup["merchant_a"].id
    m_b_id = merchant_setup["merchant_b"].id
    order_b_id = merchant_setup["order_b"].id

    # Querying Order B with Merchant A's ID must return None
    fetched_order = await repo.get_by_id_for_merchant(order_b_id, m_a_id)
    assert fetched_order is None, "Repository returned Order B when scoped to Merchant A!"

    # Querying Order B with Merchant B's ID must return the order
    fetched_valid = await repo.get_by_id_for_merchant(order_b_id, m_b_id)
    assert fetched_valid is not None
    assert fetched_valid.id == order_b_id
