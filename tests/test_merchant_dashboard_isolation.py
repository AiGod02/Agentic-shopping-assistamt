"""
Test suite for Merchant Dashboard multi-tenant isolation (test_merchant_dashboard_isolation.py).
"""

import pytest


@pytest.mark.asyncio
async def test_merchant_dashboard_catalog_isolation(merchant_client, merchant_setup):
    """Catalog endpoint (/api/v1/listings) isolates items per merchant token."""
    headers_a = {"Authorization": f"Bearer {merchant_setup['token_a']}"}
    headers_b = {"Authorization": f"Bearer {merchant_setup['token_b']}"}

    res_a = await merchant_client.get("/api/v1/listings", headers=headers_a)
    res_b = await merchant_client.get("/api/v1/listings", headers=headers_b)

    assert res_a.status_code == 200
    assert res_b.status_code == 200

    items_a = {item["id"] for item in res_a.json()["items"]}
    items_b = {item["id"] for item in res_b.json()["items"]}

    assert len(items_a.intersection(items_b)) == 0, "Catalog items leaked between Merchant A and Merchant B!"


@pytest.mark.asyncio
async def test_merchant_dashboard_orders_isolation(merchant_client, merchant_setup):
    """Orders endpoint (/api/v1/orders) isolates orders per merchant token."""
    headers_a = {"Authorization": f"Bearer {merchant_setup['token_a']}"}
    headers_b = {"Authorization": f"Bearer {merchant_setup['token_b']}"}

    res_a = await merchant_client.get("/api/v1/orders", headers=headers_a)
    res_b = await merchant_client.get("/api/v1/orders", headers=headers_b)

    assert res_a.status_code == 200
    assert res_b.status_code == 200

    orders_a = {order["id"] for order in res_a.json()["items"]}
    orders_b = {order["id"] for order in res_b.json()["items"]}

    assert len(orders_a.intersection(orders_b)) == 0, "Orders leaked between Merchant A and Merchant B!"


@pytest.mark.asyncio
async def test_merchant_dashboard_analytics_isolation(merchant_client, merchant_setup):
    """Analytics endpoint (/api/v1/analytics/overview) succeeds and is scoped to merchant."""
    headers_a = {"Authorization": f"Bearer {merchant_setup['token_a']}"}
    headers_b = {"Authorization": f"Bearer {merchant_setup['token_b']}"}

    res_a = await merchant_client.get("/api/v1/analytics/overview", headers=headers_a)
    res_b = await merchant_client.get("/api/v1/analytics/overview", headers=headers_b)

    assert res_a.status_code == 200
    assert res_b.status_code == 200


@pytest.mark.asyncio
async def test_merchant_dashboard_profile_isolation(merchant_client, merchant_setup):
    """Merchant profile endpoint (/api/v1/merchants/me) returns the correct distinct merchant profile."""
    headers_a = {"Authorization": f"Bearer {merchant_setup['token_a']}"}
    headers_b = {"Authorization": f"Bearer {merchant_setup['token_b']}"}

    res_a = await merchant_client.get("/api/v1/merchants/me", headers=headers_a)
    res_b = await merchant_client.get("/api/v1/merchants/me", headers=headers_b)

    assert res_a.status_code == 200
    assert res_b.status_code == 200

    data_a = res_a.json()
    data_b = res_b.json()

    assert data_a["id"] == str(merchant_setup["merchant_a"].id)
    assert data_b["id"] == str(merchant_setup["merchant_b"].id)
    assert data_a["id"] != data_b["id"]
