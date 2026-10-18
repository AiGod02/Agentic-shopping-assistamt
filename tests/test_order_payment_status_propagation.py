"""
Test suite for order payment status propagation via webhooks (test_order_payment_status_propagation.py).
"""

import pytest
import uuid
from decimal import Decimal
from payment_server.api.v1.webhooks import _update_payment_status
from merchant_server.domain.models.order import Order
from merchant_server.domain.models.payment import Payment
from sqlalchemy import select


@pytest.mark.asyncio
async def test_order_payment_status_propagation_success(db_session, merchant_setup):
    """Successful payment webhook transitions payments.status to captured and orders.status to paid."""
    order_a_id = merchant_setup["order_a"].id
    payment_a_id = merchant_setup["payment_a"].id
    gw_id = merchant_setup["gw_pay_a_id"]

    # Trigger payment success
    await _update_payment_status(db_session, gw_id, "captured", "stripe")
    db_session.expire_all()

    # Verify Order A status updated to paid
    res_o = await db_session.execute(select(Order).where(Order.id == order_a_id))
    order = res_o.scalars().first()
    assert order.status == "paid", f"Expected order status 'paid', got '{order.status}'"

    # Verify Payment A status updated to captured
    res_p = await db_session.execute(select(Payment).where(Payment.id == payment_a_id))
    pay = res_p.scalars().first()
    assert pay.status == "captured"
    assert pay.captured_at is not None


@pytest.mark.asyncio
async def test_order_payment_status_propagation_failure(db_session, merchant_setup):
    """Failed payment webhook transitions payments.status to failed and orders.status to payment_failed."""
    user_id = merchant_setup["user_a"].id
    order_id = uuid.uuid4()
    payment_id = uuid.uuid4()
    gw_fail_id = f"pi_fail_{uuid.uuid4().hex[:12]}"

    order_fail = Order(
        id=order_id,
        order_number=f"ORD-F-{uuid.uuid4().hex[:6].upper()}",
        user_id=user_id,
        status="pending_payment",
        subtotal=50.00,
        tax_amount=5.00,
        total_amount=55.00,
        currency="USD",
    )
    payment_fail = Payment(
        id=payment_id,
        order_id=order_id,
        user_id=user_id,
        gateway="stripe",
        gateway_payment_id=gw_fail_id,
        amount=Decimal("55.00"),
        currency="USD",
        status="pending",
        idempotency_key=f"pay-f-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(order_fail)
    db_session.add(payment_fail)
    await db_session.commit()

    # Trigger payment failure
    await _update_payment_status(db_session, gw_fail_id, "failed", "stripe", failure_reason="Card declined")
    db_session.expire_all()

    res_o = await db_session.execute(select(Order).where(Order.id == order_id))
    order = res_o.scalars().first()
    assert order.status == "payment_failed"

    res_p = await db_session.execute(select(Payment).where(Payment.id == payment_id))
    pay = res_p.scalars().first()
    assert pay.status == "failed"
    assert pay.failure_reason == "Card declined"


@pytest.mark.asyncio
async def test_webhook_missing_signature_rejected(payment_client):
    """Stripe webhook endpoint without Stripe-Signature header returns 400 Bad Request."""
    res = await payment_client.post("/api/v1/webhooks/stripe", content=b"{}")
    assert res.status_code == 400
    assert "Missing Stripe-Signature header" in res.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_invalid_signature_rejected(payment_client, db_session, merchant_setup):
    """Forged/invalid webhook signature returns 400 Bad Request and does NOT modify order/payment status."""
    order_a_id = merchant_setup["order_a"].id

    headers = {"Stripe-Signature": "t=12345,v1=invalid_forged_signature_hash"}
    res = await payment_client.post("/api/v1/webhooks/stripe", content=b'{"type": "payment_intent.succeeded"}', headers=headers)

    assert res.status_code == 400, f"Expected 400 for forged webhook signature, got {res.status_code}"

    # Verify Order status in DB remains unchanged ('pending_payment')
    db_session.expire_all()
    res_o = await db_session.execute(select(Order).where(Order.id == order_a_id))
    order = res_o.scalars().first()
    assert order.status == "pending_payment", f"Forged webhook altered order status to {order.status}!"
