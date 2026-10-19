"""
Payment Service — orchestrates entire payment lifecycle.

Handles payment creation, capture, gateway routing, idempotency, and ledger recording.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from payment_server.config import settings
from payment_server.domain.gateways.base import PaymentGateway
from payment_server.domain.gateways.stripe_gateway import StripeGateway
from payment_server.domain.gateways.razorpay_gateway import RazorpayGateway
from shared.events.kafka_producer import save_outbox_event
from shared.observability.logging import get_logger

logger = get_logger(__name__)

# SQLAlchemy table references — using raw SQL via session to avoid circular model imports
# These map directly to the payments table from the migration


class PaymentServiceError(Exception):
    pass


class PaymentService:
    """Orchestrates payment creation, capture, and status management."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._gateways: dict[str, PaymentGateway] = {}

    def _get_gateway(self, gateway_name: str) -> PaymentGateway:
        """Get or create a payment gateway instance."""
        if gateway_name not in self._gateways:
            if gateway_name == "stripe":
                if not settings.stripe_secret_key:
                    from payment_server.domain.gateways.mock_gateway import MockPaymentGateway
                    self._gateways[gateway_name] = MockPaymentGateway()
                else:
                    self._gateways[gateway_name] = StripeGateway()
            elif gateway_name == "razorpay":
                if not settings.razorpay_key_id:
                    from payment_server.domain.gateways.mock_gateway import MockPaymentGateway
                    self._gateways[gateway_name] = MockPaymentGateway()
                else:
                    self._gateways[gateway_name] = RazorpayGateway()
            elif gateway_name == "mock":
                from payment_server.domain.gateways.mock_gateway import MockPaymentGateway
                self._gateways[gateway_name] = MockPaymentGateway()
            else:
                raise PaymentServiceError(f"Unsupported gateway: {gateway_name}")
        return self._gateways[gateway_name]

    async def create_payment(
        self,
        order_id: str,
        user_id: str,
        amount: float,
        currency: str,
        gateway: str,
        idempotency_key: str,
        customer_email: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a payment intent via the specified gateway.

        Idempotency: if a payment with the same idempotency_key exists, return it.
        """
        # Idempotency check
        existing = await self.session.execute(
            select("*").select_from(
                self.session.get_bind().dialect.identifier_preparer.format_table(
                    type("T", (), {"__tablename__": "payments"})
                )
            )
        ) if False else None  # Placeholder — we use text queries below

        from sqlalchemy import text
        result = await self.session.execute(
            text("SELECT id, gateway_payment_id, status FROM payments WHERE idempotency_key = :key"),
            {"key": idempotency_key},
        )
        existing_row = result.fetchone()
        if existing_row:
            logger.info("payment_idempotent_hit", payment_id=str(existing_row[0]))
            return {
                "payment_id": str(existing_row[0]),
                "gateway_payment_id": existing_row[1],
                "status": existing_row[2],
            }

        # Create payment intent via gateway
        gw = self._get_gateway(gateway)
        intent = await gw.create_payment_intent(
            amount=amount,
            currency=currency,
            order_id=order_id,
            metadata=metadata,
            idempotency_key=idempotency_key,
        )

        gateway_payment_id = intent.get("id") if isinstance(intent, dict) else intent.gateway_payment_id
        gateway_order_id = intent.get("id") if isinstance(intent, dict) else intent.gateway_order_id
        intent_status = intent.get("status") if isinstance(intent, dict) else intent.status

        import json

        # 1. Resolve / ensure valid user in PostgreSQL
        user_uuid = None
        try:
            cand_uid = uuid.UUID(str(user_id))
            u_res = await self.session.execute(text("SELECT id FROM users WHERE id = :uid"), {"uid": cand_uid})
            if u_res.fetchone():
                user_uuid = cand_uid
        except Exception:
            pass

        if not user_uuid:
            u_res = await self.session.execute(text("SELECT id FROM users WHERE role = 'customer' LIMIT 1"))
            u_row = u_res.fetchone()
            if u_row:
                user_uuid = u_row[0]
            else:
                user_uuid = uuid.uuid4()
                await self.session.execute(
                    text("INSERT INTO users (id, email, password_hash, full_name, role) VALUES (:id, 'demo_buyer@example.com', 'demo_pw_hash', 'Demo Customer', 'customer') ON CONFLICT DO NOTHING"),
                    {"id": user_uuid}
                )
                await self.session.flush()

        # 2. Resolve / ensure valid order in PostgreSQL
        order_uuid = None
        try:
            cand_oid = uuid.UUID(str(order_id))
            o_res = await self.session.execute(text("SELECT id FROM orders WHERE id = :oid"), {"oid": cand_oid})
            if o_res.fetchone():
                order_uuid = cand_oid
        except Exception:
            pass

        if not order_uuid:
            o_res = await self.session.execute(text("SELECT id FROM orders WHERE order_number = :onum"), {"onum": str(order_id)[:50]})
            o_row = o_res.fetchone()
            if o_row:
                order_uuid = o_row[0]

        if not order_uuid:
            order_uuid = uuid.uuid4()
            order_num = str(order_id) if order_id else f"ORD-{uuid.uuid4().hex[:8].upper()}"
            order_num = order_num[:50]
            await self.session.execute(
                text("""
                    INSERT INTO orders (id, order_number, user_id, status, subtotal, tax_amount, discount_amount, total_amount, currency, metadata, saga_state)
                    VALUES (:id, :num, :uid, 'pending', :amt, 0, 0, :amt, :curr, CAST(:meta AS jsonb), 'payment_pending')
                    ON CONFLICT (order_number) DO NOTHING
                """),
                {
                    "id": order_uuid,
                    "num": order_num,
                    "uid": user_uuid,
                    "amt": amount,
                    "curr": currency,
                    "meta": "{}",
                }
            )
            await self.session.flush()
            o_res = await self.session.execute(text("SELECT id FROM orders WHERE order_number = :num"), {"num": order_num})
            o_row = o_res.fetchone()
            if o_row:
                order_uuid = o_row[0]

        # 3. Persist payment record
        payment_uuid = uuid.uuid4()
        payment_id = str(payment_uuid)
        payment_meta = {
            "razorpay_order_id": gateway_order_id,
            "razorpay_key_id": (getattr(settings, "razorpay_key_id", "") or "").strip().strip('"').strip("'"),
            "original_order_id": str(order_id),
            **(metadata or {}),
        }
        await self.session.execute(
            text("""
                INSERT INTO payments (id, order_id, user_id, gateway, gateway_payment_id,
                    gateway_order_id, amount, currency, status, idempotency_key, metadata)
                VALUES (:id, :order_id, :user_id, :gateway, :gateway_payment_id,
                    :gateway_order_id, :amount, :currency, :status, :idempotency_key, CAST(:metadata AS jsonb))
            """),
            {
                "id": payment_uuid,
                "order_id": order_uuid,
                "user_id": user_uuid,
                "gateway": gateway,
                "gateway_payment_id": gateway_payment_id or "",
                "gateway_order_id": gateway_order_id or "",
                "amount": amount,
                "currency": currency,
                "status": intent_status,
                "idempotency_key": idempotency_key,
                "metadata": json.dumps(payment_meta),
            },
        )
        await self.session.commit()

        # 4. Record ledger entry
        from payment_server.domain.services.ledger_service import LedgerService
        ledger = LedgerService(self.session)
        await ledger.record_entry(
            payment_id=payment_id,
            entry_type="payment_created",
            debit_account=f"customer:{user_uuid}",
            credit_account="platform:receivables",
            amount=amount,
            currency=currency,
            description=f"Payment created for order {order_id}",
        )

        logger.info(
            "payment_created",
            payment_id=payment_id,
            gateway=gateway,
            amount=amount,
            order_id=str(order_uuid),
        )

        client_secret = intent.get("client_secret") if isinstance(intent, dict) else intent.client_secret

        return {
            "payment_id": payment_id,
            "gateway_payment_id": gateway_payment_id,
            "gateway_order_id": gateway_order_id,
            "client_secret": client_secret,
            "status": intent_status,
            "amount": amount,
            "currency": currency,
            "order_id": str(order_uuid),
            "metadata": payment_meta,
        }

    async def capture_payment(
        self,
        payment_id: str,
        gateway_payment_id: str | None = None,
        amount: float | None = None,
    ) -> dict[str, Any]:
        """Capture an authorized payment."""
        from sqlalchemy import text
        import asyncio

        try:
            pid_uuid = uuid.UUID(str(payment_id))
        except Exception:
            pid_uuid = payment_id

        result = await self.session.execute(
            text("SELECT gateway, gateway_payment_id, gateway_order_id, amount, currency, order_id, status FROM payments WHERE id = :id FOR UPDATE"),
            {"id": pid_uuid},
        )
        row = result.fetchone()
        if not row:
            raise PaymentServiceError(f"Payment {payment_id} not found")

        gateway_name, db_gw_payment_id, gateway_order_id, db_amount, currency, order_id, current_status = row

        if current_status == "captured":
            return {
                "payment_id": str(payment_id),
                "gateway_payment_id": db_gw_payment_id,
                "status": "captured",
                "amount": float(db_amount),
                "currency": currency,
            }

        effective_gw_payment_id = gateway_payment_id or db_gw_payment_id
        gw = self._get_gateway(gateway_name)

        # For Razorpay, if payment_id is still unknown, resolve real payment ID from order
        if gateway_name == "razorpay" and not effective_gw_payment_id:
            if gateway_order_id:
                try:
                    loop = asyncio.get_event_loop()
                    order_payments = await loop.run_in_executor(
                        None,
                        lambda: gw.client.order.payments(gateway_order_id),
                    )
                    if order_payments and order_payments.get("items"):
                        effective_gw_payment_id = order_payments["items"][0]["id"]
                        logger.info(
                            "razorpay_payment_id_resolved_from_order",
                            order_id=gateway_order_id,
                            payment_id=effective_gw_payment_id,
                        )
                except Exception as e:
                    logger.error("razorpay_order_payments_fetch_failed", error=str(e), order_id=gateway_order_id)

        if not effective_gw_payment_id:
            raise PaymentServiceError(
                f"Cannot capture payment {payment_id}: No gateway payment ID found. "
                f"Customer payment must be authorized on {gateway_name} before capture."
            )

        capture_amount = amount if amount is not None else float(db_amount)
        try:
            capture_result = await gw.capture_payment(effective_gw_payment_id, amount=capture_amount)
        except Exception as e:
            raise PaymentServiceError(f"Gateway capture failed on {gateway_name}: {e}")

        # Update payment status and record real gateway_payment_id
        pm_type = capture_result.get("payment_method_type", "card") if isinstance(capture_result, dict) else getattr(capture_result, "payment_method_type", "card")
        amount_captured = capture_result.get("amount_captured", capture_amount) if isinstance(capture_result, dict) else getattr(capture_result, "amount_captured", capture_amount)

        await self.session.execute(
            text("""
                UPDATE payments 
                SET status = 'captured', 
                    gateway_payment_id = :gw_pid,
                    payment_method_type = :pm_type,
                    captured_at = :captured_at 
                WHERE id = :id
            """),
            {
                "id": pid_uuid,
                "gw_pid": effective_gw_payment_id,
                "pm_type": pm_type,
                "captured_at": datetime.now(timezone.utc),
            },
        )

        # Update linked order status to paid and saga_state to completed
        if order_id and not str(order_id).startswith("sub-"):
            try:
                cand_oid = uuid.UUID(str(order_id))
            except Exception:
                cand_oid = order_id
            await self.session.execute(
                text("UPDATE orders SET status = 'paid', saga_state = 'completed', updated_at = NOW() WHERE id = :oid"),
                {"oid": cand_oid},
            )
            logger.info("order_status_updated_to_paid_on_capture", order_id=str(order_id), payment_id=str(payment_id))

        # Activate subscription if this is a platform subscription payment
        if order_id and str(order_id).startswith("sub-"):
            sub_id = order_id[4:]
            import httpx
            from payment_server.config import settings
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.post(f"{settings.merchant_server_url}/api/v1/subscriptions/activate/{sub_id}")
                    resp.raise_for_status()
                    logger.info("subscription_activated_via_http", subscription_id=sub_id, payment_id=payment_id)
                except Exception as ex:
                    logger.error("failed_to_activate_subscription_on_merchant_server", subscription_id=sub_id, error=str(ex))

        # Ledger entry
        from payment_server.domain.services.ledger_service import LedgerService
        ledger = LedgerService(self.session)
        await ledger.record_entry(
            payment_id=str(payment_id),
            entry_type="payment_captured",
            debit_account="platform:cash",
            credit_account="platform:receivables",
            amount=amount_captured,
            currency=currency,
            description=f"Payment {payment_id} captured ({gateway_name})",
        )

        # Save event to outbox
        await save_outbox_event(
            db_session=self.session,
            topic="payments",
            event_type="payment.captured",
            payload={"payment_id": str(payment_id), "amount": amount_captured, "gateway": gateway_name, "gateway_payment_id": effective_gw_payment_id},
            source="payment-server",
            key=str(payment_id),
        )

        # Commit everything atomically
        await self.session.commit()

        return {
            "payment_id": str(payment_id),
            "gateway_payment_id": effective_gw_payment_id,
            "status": "captured",
            "amount_captured": amount_captured,
        }

    async def get_payment(self, payment_id: str) -> dict[str, Any] | None:
        from sqlalchemy import text
        result = await self.session.execute(
            text("SELECT id, order_id, gateway, gateway_payment_id, amount, currency, status, captured_at, created_at FROM payments WHERE id = :id"),
            {"id": payment_id},
        )
        row = result.fetchone()
        if not row:
            return None
        return {
            "payment_id": str(row[0]),
            "order_id": str(row[1]),
            "gateway": row[2],
            "gateway_payment_id": row[3],
            "amount": float(row[4]),
            "currency": row[5],
            "status": row[6],
            "captured_at": str(row[7]) if row[7] else None,
            "created_at": str(row[8]),
        }
