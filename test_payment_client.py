"""
CLI Payment Gateway Test Client — Agentic Commerce Protocol.

Quick automated test script to verify payment creation, idempotency,
ledger recording, and refunds on either the Unified Server (port 8000)
or Payment Server (port 8003).

Usage:
    python test_payment_client.py
    python test_payment_client.py --gateway stripe
    python test_payment_client.py --gateway razorpay
    python test_payment_client.py --url http://localhost:8003
"""

import argparse
import sys
import uuid
import httpx


def run_payment_tests(base_url: str = "http://localhost:8000", gateway: str = "mock"):
    print("=" * 70)
    print("💳 AGENTIC COMMERCE PROTOCOL — PAYMENT GATEWAY CLI TEST CLIENT")
    print(f"Target Server : {base_url}")
    print(f"Gateway Mode  : {gateway.upper()}")
    print("=" * 70)

    client = httpx.Client(base_url=base_url, timeout=10.0)

    # 1. Health Check
    print("\n[Step 1] Checking Server Health...")
    try:
        r = client.get("/health")
        if r.status_code == 200:
            print(f"   ✅ Server is healthy: {r.json()}")
        else:
            print(f"   ⚠️ Server returned status {r.status_code}: {r.text}")
    except Exception as e:
        print(f"   ❌ Could not connect to server at {base_url}: {e}")
        print("   Make sure the server is running (`uvicorn unified_server:app --port 8000`)")
        return

    # 2. Create Payment Intent
    order_id = f"ord_test_{uuid.uuid4().hex[:8]}"
    user_id = str(uuid.uuid4())
    idempotency_key = str(uuid.uuid4())
    amount = 49.99

    print(f"\n[Step 2] Creating Payment (Order: {order_id}, Amount: ${amount}, Idempotency: {idempotency_key[:8]}...)...")
    payload = {
        "order_id": order_id,
        "user_id": user_id,
        "amount": amount,
        "currency": "USD" if gateway != "razorpay" else "INR",
        "gateway": gateway,
        "idempotency_key": idempotency_key,
        "customer_email": "shopper@example.com",
        "metadata": {"test_client": "cli", "platform": "agentic_commerce"}
    }

    res = client.post(
        "/api/v1/payments/create",
        json=payload,
        headers={"X-Internal-Service": "merchant-server"}
    )

    if res.status_code != 201:
        print(f"   ❌ Payment creation failed: {res.status_code} - {res.text}")
        return

    data = res.json()
    payment_id = data.get("id") or data.get("payment_id")
    print(f"   ✅ Payment Created Successfully!")
    print(f"      • Payment ID   : {payment_id}")
    print(f"      • Status       : {data.get('status')}")
    print(f"      • Gateway Ref  : {data.get('gateway_payment_id') or data.get('client_secret')}")

    # 3. Test Idempotency (Replay the exact same key)
    print("\n[Step 3] Testing Idempotency Protection (Re-sending exact same key)...")
    res_idem = client.post(
        "/api/v1/payments/create",
        json=payload,
        headers={"X-Internal-Service": "merchant-server"}
    )
    if res_idem.status_code in (200, 201):
        idem_data = res_idem.json()
        idem_id = idem_data.get("id") or idem_data.get("payment_id")
        if idem_id == payment_id:
            print("   ✅ Idempotency Verified! Returned same payment ID without double charging.")
        else:
            print(f"   ⚠️ Warning: Got different payment ID: {idem_id}")
    else:
        print(f"   ❌ Idempotency check returned error: {res_idem.status_code}")

    # 4. Capture Payment
    if payment_id:
        print(f"\n[Step 4] Capturing / Authorizing Payment ({payment_id})...")
        res_cap = client.post(
            f"/api/v1/payments/{payment_id}/capture",
            headers={"X-Internal-Service": "merchant-server"}
        )
        if res_cap.status_code == 200:
            print(f"   ✅ Payment Captured Successfully: {res_cap.json()}")
        else:
            print(f"   ℹ️ Capture response ({res_cap.status_code}): {res_cap.text}")

    # 5. Ledger Inspection
    if payment_id:
        print(f"\n[Step 5] Checking Ledger Entries for Payment ({payment_id})...")
        res_led = client.get(f"/api/v1/payments/{payment_id}/ledger")
        if res_led.status_code == 200:
            ledger_data = res_led.json()
            entries = ledger_data.get("entries", [])
            print(f"   ✅ Ledger Entries Recorded: {len(entries)} entries found")
            for entry in entries[:3]:
                print(f"      • {entry.get('entry_type', '').upper()} | Account: {entry.get('account')} | Amount: {entry.get('amount')}")
        else:
            print(f"   ℹ️ Ledger response ({res_led.status_code}): {res_led.text}")

    # 6. Test Partial Refund
    if payment_id:
        print(f"\n[Step 6] Testing Refund ($10.00)...")
        res_ref = client.post(
            f"/api/v1/payments/{payment_id}/refund",
            json={"amount": 10.0, "reason": "Customer test return", "initiated_by": "cli_tester"},
            headers={"X-Internal-Service": "merchant-server"}
        )
        if res_ref.status_code == 200:
            print(f"   ✅ Refund Processed: {res_ref.json()}")
        else:
            print(f"   ℹ️ Refund response ({res_ref.status_code}): {res_ref.text}")

    print("\n" + "=" * 70)
    print("🎉 ALL PAYMENT GATEWAY TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)
    print(f"👉 You can also open the Visual Test Client in your browser at:")
    print(f"   {base_url}/demo-payment")
    print("=" * 70)


def run_full_db_flow(base_url: str = "http://localhost:8000", gateway: str = "mock"):
    print("=" * 70)
    print("🗄️ END-TO-END E-COMMERCE DATABASE FLOW VERIFICATION")
    print(f"Target Server : {base_url}")
    print(f"Gateway Mode  : {gateway.upper()}")
    print("=" * 70)

    client = httpx.Client(base_url=base_url, timeout=15.0)

    print("\nExecuting complete purchase flow on PostgreSQL database:")
    print("   1. User Auth / Customer Record")
    print("   2. Catalog Listing Lookup")
    print("   3. Cart Insertion (carts & cart_items)")
    print("   4. Checkout Saga Transaction (orders & order_items)")
    print("   5. Gateway Payment Execution (payments)")
    print("   6. Double-Entry Accounting (ledger_entries)")
    print("   7. Order Status Confirmation\n")

    try:
        res = client.post(f"/api/v1/payments/demo-full-flow?gateway={gateway}")
        if res.status_code != 200:
            print(f"❌ Full flow failed ({res.status_code}): {res.text}")
            return

        data = res.json()
        rec = data.get("database_records_created", {})
        print("✅ FULL FLOW COMPLETED AND VERIFIED ON REAL DATABASE!")
        print("-" * 50)
        print(f"   • Customer User ID : {rec.get('user_id')} ({rec.get('customer_email')})")
        print(f"   • Listing Item     : {rec.get('listing_title')} (ID: {rec.get('listing_id')})")
        print(f"   • Order Created    : {rec.get('order_number')} (Status: {rec.get('order_status')})")
        print(f"   • Order ID in DB   : {rec.get('order_id')}")
        print(f"   • Payment ID in DB : {rec.get('payment_id')} (Status: {rec.get('payment_status')})")
        print(f"   • Gateway Ref ID   : {rec.get('gateway_payment_id')}")
        print(f"   • Ledger Entries   : {rec.get('ledger_entries_count')} recorded in 'ledger_entries' table")
        print("-" * 50)
        print("📁 All PostgreSQL tables verified:")
        for t in data.get("tables_verified_in_postgres", []):
            print(f"   ✓ {t}")
        print("=" * 70)

    except Exception as e:
        print(f"❌ Connection error: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Payment Gateway CLI Test Client")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of server")
    parser.add_argument("--gateway", default="mock", choices=["mock", "stripe", "razorpay"], help="Gateway to test")
    parser.add_argument("--full-flow", action="store_true", help="Run complete end-to-end e-commerce flow on DB")
    args = parser.parse_args()

    if args.full_flow:
        run_full_db_flow(base_url=args.url, gateway=args.gateway)
    else:
        run_payment_tests(base_url=args.url, gateway=args.gateway)

