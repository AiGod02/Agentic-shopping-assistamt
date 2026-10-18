"""
Test suite for authentication and authorization enforcement (test_auth.py).
"""

import pytest
import uuid
from agent_server.config import Settings as AgentSettings


@pytest.mark.asyncio
async def test_unauthenticated_payment_create_returns_401(payment_client):
    """Unauthenticated call to POST /api/v1/payments/create must return 401 Unauthorized."""
    dummy_id = str(uuid.uuid4())
    res = await payment_client.post(
        "/api/v1/payments/create",
        json={
            "order_id": dummy_id,
            "user_id": str(uuid.uuid4()),
            "amount": 100.0,
            "currency": "USD",
            "gateway": "stripe",
            "idempotency_key": f"key-{dummy_id}",
        },
    )
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"


@pytest.mark.asyncio
async def test_unauthenticated_payment_capture_returns_401(payment_client):
    """Unauthenticated call to POST /api/v1/payments/{payment_id}/capture must return 401 Unauthorized."""
    dummy_id = str(uuid.uuid4())
    res = await payment_client.post(f"/api/v1/payments/{dummy_id}/capture")
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"


@pytest.mark.asyncio
async def test_unauthenticated_payment_refund_returns_401(payment_client):
    """Unauthenticated call to POST /api/v1/payments/{payment_id}/refund must return 401 Unauthorized."""
    dummy_id = str(uuid.uuid4())
    res = await payment_client.post(f"/api/v1/payments/{dummy_id}/refund", json={"reason": "test"})
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"


@pytest.mark.asyncio
async def test_unauthenticated_payment_escrow_returns_401(payment_client):
    """Unauthenticated call to POST /api/v1/payments/escrow/hold must return 401 Unauthorized."""
    dummy_id = str(uuid.uuid4())
    res = await payment_client.post(
        "/api/v1/payments/escrow/hold",
        json={"payment_id": dummy_id, "order_id": dummy_id, "amount": 100.0},
    )
    assert res.status_code == 401, f"Expected 401, got {res.status_code}"


@pytest.mark.asyncio
async def test_cross_merchant_payment_capture_refund_returns_403(payment_client, merchant_setup):
    """Merchant B token used to capture/refund Merchant A's payment must return 403 Forbidden."""
    payment_a_id = str(merchant_setup["payment_a"].id)
    headers_b = {"Authorization": f"Bearer {merchant_setup['token_b']}"}

    # Merchant B attempts capture on Merchant A payment
    res_cap = await payment_client.post(f"/api/v1/payments/{payment_a_id}/capture", headers=headers_b)
    assert res_cap.status_code == 403, f"Expected 403 for cross-merchant capture, got {res_cap.status_code}"

    # Merchant B attempts refund on Merchant A payment
    res_ref = await payment_client.post(f"/api/v1/payments/{payment_a_id}/refund", json={"reason": "test"}, headers=headers_b)
    assert res_ref.status_code == 403, f"Expected 403 for cross-merchant refund, got {res_ref.status_code}"


@pytest.mark.asyncio
async def test_legitimate_merchant_payment_access_authorized(payment_client, merchant_setup):
    """Merchant A token used on their own payment passes ownership check (not 401/403)."""
    payment_a_id = str(merchant_setup["payment_a"].id)
    headers_a = {"Authorization": f"Bearer {merchant_setup['token_a']}"}

    # Attempt capture on Merchant A's own payment (may fail business logic if pending, but ownership check passes -> not 401 or 403)
    res = await payment_client.post(f"/api/v1/payments/{payment_a_id}/capture", headers=headers_a)
    assert res.status_code not in (401, 403), f"Ownership check failed for legitimate merchant, got {res.status_code}"


@pytest.mark.asyncio
async def test_jwt_secret_unset_config_validation():
    """System raises error or validation failure if secret key is empty/invalid."""
    from shared.auth.jwt_handler import JWTHandler
    handler = JWTHandler(secret_key="")
    with pytest.raises(Exception):
        handler.create_access_token(user_id="user123", role="customer")


@pytest.mark.asyncio
async def test_public_endpoints_require_no_auth(merchant_client, merchant_setup):
    """Search, listing details, reviews, availability must succeed with NO auth header."""
    listing_id = str(merchant_setup["listing_a"].id)

    # 1. Search listings
    res1 = await merchant_client.get("/api/v1/listings")
    assert res1.status_code == 200, f"Public listings search failed: {res1.status_code}"

    # 2. Get listing details
    res2 = await merchant_client.get(f"/api/v1/listings/{listing_id}")
    assert res2.status_code == 200, f"Public listing details failed: {res2.status_code}"

    # 3. Get listing reviews
    res3 = await merchant_client.get(f"/api/v1/listings/{listing_id}/reviews")
    assert res3.status_code == 200, f"Public listing reviews failed: {res3.status_code}"

    # 4. Check availability
    res4 = await merchant_client.get(f"/api/v1/availability/listing/{listing_id}")
    assert res4.status_code == 200, f"Public availability check failed: {res4.status_code}"


@pytest.mark.asyncio
async def test_direct_cart_without_jwt_returns_401(merchant_client):
    """Direct HTTP requests to merchant_server /api/v1/cart without JWT must return 401."""
    res1 = await merchant_client.get("/api/v1/cart")
    assert res1.status_code == 401, f"Expected 401 for GET /cart without token, got {res1.status_code}"

    res2 = await merchant_client.post("/api/v1/cart/items", json={"listing_id": str(uuid.uuid4()), "quantity": 1})
    assert res2.status_code == 401, f"Expected 401 for POST /cart/items without token, got {res2.status_code}"
