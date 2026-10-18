import httpx
import asyncio
import json
from merchant_server.main import create_app as create_merchant_app
from agent_server.main import create_app as create_agent_app
from payment_server.main import create_app as create_payment_app

async def run_audit():
    print("=" * 70)
    print("PART 3 — REGRESSION CHECK & AUTH DOMAIN VERIFICATION")
    print("=" * 70)

    merchant_app = create_merchant_app()
    agent_app = create_agent_app()
    payment_app = create_payment_app()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=merchant_app), base_url="http://test-merchant") as merchant_client, \
               httpx.AsyncClient(transport=httpx.ASGITransport(app=agent_app), base_url="http://test-agent") as agent_client, \
               httpx.AsyncClient(transport=httpx.ASGITransport(app=payment_app), base_url="http://test-payment") as payment_client:

        # -------------------------------------------------------------
        # TEST 2: Anonymous Public Endpoints (ZERO auth headers)
        # -------------------------------------------------------------
        print("\n[TEST 2] Anonymous Public Endpoints (ZERO auth headers)")
        
        # 2a. Search listings (Agent Server)
        r_agent_search = await agent_client.get("/api/v1/agent/search?q=tv")
        print(f"  2a. Agent GET /api/v1/agent/search?q=tv -> Status: {r_agent_search.status_code}")
        assert r_agent_search.status_code == 200, f"Expected 200, got {r_agent_search.status_code}"
        listings_data = r_agent_search.json()
        print(f"      Response items: {len(listings_data.get('listings', [])) if isinstance(listings_data, dict) else len(listings_data)}")

        # 2b. Search listings (Merchant Server)
        r_merch_search = await merchant_client.get("/api/v1/listings?q=tv")
        print(f"  2b. Merchant GET /api/v1/listings?q=tv -> Status: {r_merch_search.status_code}")
        assert r_merch_search.status_code == 200, f"Expected 200, got {r_merch_search.status_code}"
        items = r_merch_search.json().get("items", [])
        sample_id = items[0]["id"] if items else "477adabe-fb65-42bd-a57d-4d12f1315323"

        # 2c. Get listing details
        r_detail = await merchant_client.get(f"/api/v1/listings/{sample_id}")
        print(f"  2c. Merchant GET /api/v1/listings/{sample_id} -> Status: {r_detail.status_code}")
        assert r_detail.status_code == 200, f"Expected 200, got {r_detail.status_code}"

        # 2d. Get reviews
        r_reviews = await merchant_client.get(f"/api/v1/listings/{sample_id}/reviews")
        print(f"  2d. Merchant GET /api/v1/listings/{sample_id}/reviews -> Status: {r_reviews.status_code}")
        assert r_reviews.status_code == 200, f"Expected 200, got {r_reviews.status_code}"

        # 2e. Check availability
        r_avail = await merchant_client.get(f"/api/v1/availability/listing/{sample_id}")
        print(f"  2e. Merchant GET /api/v1/availability/listing/{sample_id} -> Status: {r_avail.status_code}")
        assert r_avail.status_code == 200, f"Expected 200, got {r_avail.status_code}"

        print("  -> ALL PUBLIC / CATEGORY B ENDPOINTS WORK WITH ZERO AUTH HEADERS! [PASS]")

        # -------------------------------------------------------------
        # TEST 3: Anonymous Protected Endpoints (MUST return 401/403)
        # -------------------------------------------------------------
        print("\n[TEST 3] Anonymous Protected Endpoints (MUST return 401/403)")

        # 3a. Create listing
        r_create = await merchant_client.post("/api/v1/listings", json={"title": "Test", "type": "product", "base_price": 100})
        print(f"  3a. POST /api/v1/listings -> Status: {r_create.status_code} (Expected 401/403)")
        assert r_create.status_code in (401, 403)

        # 3b. Delete listing
        r_del = await merchant_client.delete(f"/api/v1/listings/{sample_id}")
        print(f"  3b. DELETE /api/v1/listings/{sample_id} -> Status: {r_del.status_code} (Expected 401/403)")
        assert r_del.status_code in (401, 403)

        # 3c. Payment capture
        r_cap = await payment_client.post(f"/api/v1/payments/{sample_id}/capture")
        print(f"  3c. POST /api/v1/payments/{sample_id}/capture -> Status: {r_cap.status_code} (Expected 401/403)")
        assert r_cap.status_code in (401, 403)

        # 3d. Payment refund
        r_ref = await payment_client.post(f"/api/v1/payments/{sample_id}/refund", json={"amount": 50.0})
        print(f"  3d. POST /api/v1/payments/{sample_id}/refund -> Status: {r_ref.status_code} (Expected 401/403)")
        assert r_ref.status_code in (401, 403)

        print("  -> ALL MERCHANT AUTH / CATEGORY A ENDPOINTS REJECT ANONYMOUS ACCESS! [PASS]")

        # -------------------------------------------------------------
        # TEST 4: Full Chat Conversation (Zero merchant auth)
        # -------------------------------------------------------------
        print("\n[TEST 4] Full Chat Conversation (Zero merchant auth, anonymous customer)")
        r_chat = await agent_client.post("/api/v1/agent/chat", json={"message": "find me a tv"})
        print(f"  4a. Agent POST /api/v1/agent/chat ('find me a tv') -> Status: {r_chat.status_code}")
        assert r_chat.status_code == 200
        chat_data = r_chat.json()
        print(f"      Session ID: {chat_data.get('session_id')}")
        print(f"      Tools Invoked: {[tc.get('tool') for tc in chat_data.get('tool_calls', [])]}")
        print("  -> CONVERSATION RUNS FULLY ANONYMOUS WITH ZERO MERCHANT AUTH! [PASS]")

        print("\n" + "=" * 70)
        print("FULL AUDIT COMPLETE: ALL REQUIREMENTS SATISFIED!")
        print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_audit())
