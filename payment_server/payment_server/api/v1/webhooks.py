"""
Webhook Handlers — Stripe and Razorpay webhook processing.

Both endpoints bypass JWT auth (configured in main.py exclude_paths).
Signature verification is handled by the gateway implementations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from payment_server.domain.gateways.stripe_gateway import StripeGateway
from payment_server.domain.gateways.razorpay_gateway import RazorpayGateway
from shared.db.session import get_db
from shared.events.kafka_producer import publish_event
from shared.observability.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook events.

    Verifies signature, processes event, updates payment status.
    """
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")

    if not signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    try:
        gw = StripeGateway()
        event_data = await gw.verify_webhook_signature(payload, signature)
    except ValueError as e:
        logger.warning("stripe_webhook_invalid", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event_data["event_type"]
    data = event_data["data"]

    logger.info("stripe_webhook_received", event_type=event_type, event_id=event_data["event_id"])

    # Process specific event types
    if event_type == "payment_intent.succeeded":
        payment_intent_id = data.get("id", "")
        await _update_payment_status(db, payment_intent_id, "captured", "stripe")

    elif event_type == "payment_intent.payment_failed":
        payment_intent_id = data.get("id", "")
        failure_message = data.get("last_payment_error", {}).get("message", "Unknown error")
        await _update_payment_status(db, payment_intent_id, "failed", "stripe", failure_message)

    elif event_type == "charge.refunded":
        payment_intent_id = data.get("payment_intent", "")
        await _update_payment_status(db, payment_intent_id, "refunded", "stripe")

    elif event_type == "charge.dispute.created":
        payment_intent_id = data.get("payment_intent", "")
        await _update_payment_status(db, payment_intent_id, "disputed", "stripe")
        logger.warning(
            "stripe_dispute_created",
            payment_intent_id=payment_intent_id,
            reason=data.get("reason"),
        )

    # Publish event for downstream consumers
    await publish_event(
        topic="payment_webhooks",
        event_type=f"stripe.{event_type}",
        payload={"event_type": event_type, "gateway_payment_id": data.get("id", "")},
        source="payment-server",
    )

    return {"received": True}


@router.post("/razorpay")
async def razorpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Razorpay webhook events."""
    payload = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not signature:
        raise HTTPException(status_code=400, detail="Missing X-Razorpay-Signature header")

    try:
        gw = RazorpayGateway()
        event_data = await gw.verify_webhook_signature(payload, signature)
    except ValueError as e:
        logger.warning("razorpay_webhook_invalid", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event_data["event_type"]
    data = event_data["data"]

    logger.info("razorpay_webhook_received", event_type=event_type)

    if event_type in ("payment.captured", "payment.authorized", "order.paid"):
        payment_entity = data.get("payment", {}).get("entity", {})
        payment_id = payment_entity.get("id", "")
        order_id = payment_entity.get("order_id", "")
        await _update_payment_status(db, payment_id, "captured", "razorpay", gateway_order_id=order_id)

    elif event_type == "payment.failed":
        payment_entity = data.get("payment", {}).get("entity", {})
        payment_id = payment_entity.get("id", "")
        order_id = payment_entity.get("order_id", "")
        error_desc = payment_entity.get("error_description", "")
        await _update_payment_status(db, payment_id, "failed", "razorpay", failure_reason=error_desc, gateway_order_id=order_id)

    elif event_type == "refund.processed":
        refund_entity = data.get("refund", {}).get("entity", {})
        payment_id = refund_entity.get("payment_id", "")
        await _update_payment_status(db, payment_id, "refunded", "razorpay")

    await publish_event(
        topic="payment_webhooks",
        event_type=f"razorpay.{event_type}",
        payload={"event_type": event_type},
        source="payment-server",
    )

    return {"received": True}


async def _update_payment_status(
    db: AsyncSession,
    gateway_payment_id: str,
    new_status: str,
    gateway: str,
    failure_reason: str | None = None,
    gateway_order_id: str | None = None,
) -> None:
    """Update payment status in the database based on webhook events."""
    if not gateway_payment_id and not gateway_order_id:
        return

    # Look up payment by gateway_payment_id or gateway_order_id
    res = await db.execute(
        text("""
            SELECT id, order_id, gateway_payment_id FROM payments 
            WHERE (gateway_payment_id = :gw_id OR (gateway_order_id = :gw_oid AND :gw_oid != ''))
              AND gateway = :gateway 
            FOR UPDATE
        """),
        {"gw_id": gateway_payment_id or "", "gw_oid": gateway_order_id or "", "gateway": gateway}
    )
    payment_row = res.fetchone()
    if not payment_row:
        logger.warning("webhook_payment_not_found", gateway_payment_id=gateway_payment_id, gateway_order_id=gateway_order_id, gateway=gateway)
        return

    pid = payment_row[0]
    order_id = payment_row[1]

    params: dict = {"id": pid, "gw_id": gateway_payment_id, "status": new_status}
    set_clause = "status = :status, gateway_payment_id = COALESCE(NULLIF(:gw_id, ''), gateway_payment_id)"

    if failure_reason:
        set_clause += ", failure_reason = :reason"
        params["reason"] = failure_reason

    if new_status == "captured":
        set_clause += ", captured_at = NOW()"

    await db.execute(
        text(f"UPDATE payments SET {set_clause} WHERE id = :id"),
        params,
    )

    # Propagate payment status to linked order
    if order_id:
        order_status = None
        if new_status == "captured":
            order_status = "paid"
        elif new_status == "failed":
            order_status = "payment_failed"
        elif new_status == "refunded":
            order_status = "refunded"

        if order_status:
            await db.execute(
                text("UPDATE orders SET status = :status, updated_at = NOW() WHERE id = :order_id"),
                {"status": order_status, "order_id": order_id},
            )
            logger.info(
                "order_status_updated_via_webhook",
                order_id=str(order_id),
                new_order_status=order_status,
            )

    await db.commit()

    logger.info(
        "payment_status_updated_via_webhook",
        gateway=gateway,
        gateway_payment_id=gateway_payment_id,
        new_status=new_status,
    )
