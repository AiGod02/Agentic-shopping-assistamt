"""
Item 2 Test: Order Status Propagation (payments.status -> orders.status)
"""

import asyncio
import os
import sys
import pathlib
import uuid
from decimal import Decimal

project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "merchant_server"))
sys.path.insert(0, str(project_root / "payment_server"))

from shared.db.session import init_db_engine, get_db_session
from merchant_server.domain.models.order import Order, OrderItem
from merchant_server.domain.models.payment import Payment
from payment_server.api.v1.webhooks import _update_payment_status
from sqlalchemy import select, text


async def run_item2_test():
    print("=" * 80)
    print("ITEM 2 — ORDER STATUS PROPAGATION END-TO-END TEST")
    print("=" * 80)

    engine = init_db_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/commerce_platform")

    async with get_db_session() as db:
        # Fetch an existing user_id from users table
        user_res = await db.execute(text("SELECT id FROM users LIMIT 1"))
        user_row = user_res.fetchone()
        if not user_row:
            print("Error: No users found in database!")
            return
        test_user_id = user_row.id

        test_order_id = uuid.uuid4()
        test_payment_id = uuid.uuid4()
        gw_payment_id = f"pi_test_{uuid.uuid4().hex[:12]}"

        # 1. Create a test order in pending_payment status and a linked payment in pending status
        order = Order(
            id=test_order_id,
            order_number=f"ORD-TEST-{uuid.uuid4().hex[:6].upper()}",
            user_id=test_user_id,
            status="pending_payment",
            subtotal=100.00,
            tax_amount=10.00,
            total_amount=110.00,
            currency="USD",
        )
        payment = Payment(
            id=test_payment_id,
            order_id=test_order_id,
            user_id=test_user_id,
            gateway="stripe",
            gateway_payment_id=gw_payment_id,
            amount=Decimal("110.00"),
            currency="USD",
            status="pending",
            idempotency_key=f"pay-test-{uuid.uuid4().hex[:8]}",
        )
        db.add(order)
        db.add(payment)
        await db.commit()

        # Query Order before webhook
        res_before = await db.execute(select(Order).where(Order.id == test_order_id))
        order_before = res_before.scalars().first()

        res_pay_before = await db.execute(select(Payment).where(Payment.id == test_payment_id))
        pay_before = res_pay_before.scalars().first()

        print("\n--- BEFORE WEBHOOK EXECUTION ---")
        print(f"Order ID: {order_before.id}")
        print(f"Order Number: {order_before.order_number}")
        print(f"Order Status: {order_before.status}")
        print(f"Payment Gateway ID: {pay_before.gateway_payment_id}")
        print(f"Payment Status: {pay_before.status}")
        assert order_before.status == "pending_payment", "Order status should initially be pending_payment"

        # 2. Execute Webhook Handler (Payment Intent Succeeded / Captured)
        print(f"\n--- EXECUTING PAYMENT SUCCESS WEBHOOK FOR {gw_payment_id} ---")
        await _update_payment_status(db, gw_payment_id, "captured", "stripe")

        db.expire_all()
        # Query Order after webhook
        res_after = await db.execute(select(Order).where(Order.id == test_order_id))
        order_after = res_after.scalars().first()

        res_pay_after = await db.execute(select(Payment).where(Payment.id == test_payment_id))
        pay_after = res_pay_after.scalars().first()

        print("\n--- AFTER SUCCESS WEBHOOK EXECUTION ---")
        print(f"Order Status: {order_after.status}")
        print(f"Payment Status: {pay_after.status}")
        print(f"Payment Captured At: {pay_after.captured_at}")

        assert pay_after.status == "captured", "Payment status should be captured"
        assert order_after.status == "paid", "Order status should transition from pending_payment to paid"
        print("CONFIRMED: Successful payment webhook correctly transitioned order status to 'paid'!")

        # 3. Test Failure Case
        test_fail_order_id = uuid.uuid4()
        test_fail_pay_id = uuid.uuid4()
        gw_fail_payment_id = f"pi_fail_{uuid.uuid4().hex[:12]}"

        order_fail = Order(
            id=test_fail_order_id,
            order_number=f"ORD-FAIL-{uuid.uuid4().hex[:6].upper()}",
            user_id=test_user_id,
            status="pending_payment",
            subtotal=50.00,
            tax_amount=5.00,
            total_amount=55.00,
            currency="USD",
        )
        payment_fail = Payment(
            id=test_fail_pay_id,
            order_id=test_fail_order_id,
            user_id=test_user_id,
            gateway="stripe",
            gateway_payment_id=gw_fail_payment_id,
            amount=Decimal("55.00"),
            currency="USD",
            status="pending",
            idempotency_key=f"pay-fail-{uuid.uuid4().hex[:8]}",
        )
        db.add(order_fail)
        db.add(payment_fail)
        await db.commit()

        print(f"\n--- EXECUTING PAYMENT FAILURE WEBHOOK FOR {gw_fail_payment_id} ---")
        await _update_payment_status(db, gw_fail_payment_id, "failed", "stripe", failure_reason="Insufficient funds")

        db.expire_all()
        res_fail_order = await db.execute(select(Order).where(Order.id == test_fail_order_id))
        order_failed = res_fail_order.scalars().first()
        res_fail_pay = await db.execute(select(Payment).where(Payment.id == test_fail_pay_id))
        pay_failed = res_fail_pay.scalars().first()

        print("\n--- AFTER FAILURE WEBHOOK EXECUTION ---")
        print(f"Order Status: {order_failed.status}")
        print(f"Payment Status: {pay_failed.status}")
        print(f"Payment Failure Reason: {pay_failed.failure_reason}")

        assert pay_failed.status == "failed", "Payment status should be failed"
        assert order_failed.status == "payment_failed", "Order status should transition to payment_failed"
        print("CONFIRMED: Failed payment webhook correctly transitioned order status to 'payment_failed'!")

        print("\n" + "=" * 80)
        print("SUCCESS: Order status propagation (payments.status -> orders.status) is 100% verified!")
        print("=" * 80)

if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run_item2_test())
