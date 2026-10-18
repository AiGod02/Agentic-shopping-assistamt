"""
Item 1 AFTER Fix Test: Guest Cart Independence & Security Test
"""

import asyncio
import os
import sys
import pathlib
import uuid
from httpx import AsyncClient, ASGITransport

project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agent_server"))

from agent_server.config import settings
from shared.db.session import init_db_engine, get_db_session
from agent_server.core.session_manager import SessionManager
from agent_server.core.orchestrator import AgentOrchestrator
from merchant_server.main import app as merchant_app
from agent_server.main import app as agent_app
from merchant_server.domain.models.listing import Listing
from merchant_server.domain.models.cart import Cart
from sqlalchemy import select, delete
from merchant_server.domain.models.cart import CartItem


async def run_item1_after_test():
    print("=" * 80)
    print("ITEM 1 — AFTER FIX GUEST CART INDEPENDENCE & SECURITY LIVE TEST")
    print("=" * 80)

    engine = init_db_engine(settings.database_url)

    # 1. Direct unauthenticated request to merchant_server cart without JWT token
    print("\n--- Test 1.1: Direct HTTP call to merchant_server /api/v1/cart without JWT ---")
    async with AsyncClient(transport=ASGITransport(app=merchant_app), base_url="http://test") as client:
        resp = await client.get("/api/v1/cart")
        print(f"Status Code: {resp.status_code}")
        print(f"Response Payload: {resp.json()}")
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("CONFIRMED: Direct unauthenticated request correctly rejected with 401 Unauthorized!")

    # 2. Dual anonymous session cart test using agent_server / chat API
    async with get_db_session() as db:
        # Fetch 2 listing IDs from DB
        stmt = select(Listing).limit(2)
        res = await db.execute(stmt)
        listings = res.scalars().all()

        listing_a = str(listings[0].id)
        listing_b = str(listings[1].id)
        print(f"\nListing A: {listings[0].title} ({listing_a})")
        print(f"Listing B: {listings[1].title} ({listing_b})")

        session_mgr = SessionManager(db)

        # Create two anonymous chat sessions
        session_a = await session_mgr.create_session()
        session_b = await session_mgr.create_session()
        session_a_id = session_a["id"]
        session_b_id = session_b["id"]
        print(f"\nCreated Anonymous Session A ID: {session_a_id}")
        print(f"Created Anonymous Session B ID: {session_b_id}")

    # Use HTTP client against agent_app to test chat endpoint end-to-end
    async with AsyncClient(transport=ASGITransport(app=agent_app), base_url="http://test") as agent_client:
        print("\n--- Session A Chat: Add Listing A to cart ---")
        req_a = {"session_id": session_a_id, "message": f"add listing {listing_a} to cart"}
        res_a = await agent_client.post("/api/v1/agent/chat", json=req_a)
        print(f"Session A Chat Response Status: {res_a.status_code}")
        print(f"Session A Agent Text: {res_a.json().get('response')}")

        print("\n--- Session B Chat: Add Listing B to cart ---")
        req_b = {"session_id": session_b_id, "message": f"add listing {listing_b} to cart"}
        res_b = await agent_client.post("/api/v1/agent/chat", json=req_b)
        print(f"Session B Chat Response Status: {res_b.status_code}")
        print(f"Session B Agent Text: {res_b.json().get('response')}")

    # Direct DB read-back to verify cart separation
    async with get_db_session() as db:
        session_mgr = SessionManager(db)
        sess_a = await session_mgr.get_session(session_a_id)
        sess_b = await session_mgr.get_session(session_b_id)

        guest_a_id = sess_a["context"].get("guest_user_id")
        guest_b_id = sess_b["context"].get("guest_user_id")

        print("\n" + "=" * 80)
        print("DIRECT DB READ-BACK RESULT (AFTER FIX)")
        print("=" * 80)
        print(f"Session A Guest User ID stored in context: {guest_a_id}")
        print(f"Session B Guest User ID stored in context: {guest_b_id}")
        assert guest_a_id != guest_b_id, "Guest User IDs must be distinct!"

        # Query Cart A
        cart_a_res = await db.execute(select(Cart).where(Cart.user_id == uuid.UUID(guest_a_id)))
        cart_a = cart_a_res.scalars().first()

        # Query Cart B
        cart_b_res = await db.execute(select(Cart).where(Cart.user_id == uuid.UUID(guest_b_id)))
        cart_b = cart_b_res.scalars().first()

        print(f"\n--- CART READ-BACK FOR SESSION A (User ID: {guest_a_id}) ---")
        if cart_a:
            print(f"Cart ID: {cart_a.id}")
            print(f"Status: {cart_a.status}")
            print(f"Items count: {len(cart_a.items)}")
            for item in cart_a.items:
                print(f"  - Item ID: {item.id}, Listing ID: {item.listing_id}, Qty: {item.quantity}")

        print(f"\n--- CART READ-BACK FOR SESSION B (User ID: {guest_b_id}) ---")
        if cart_b:
            print(f"Cart ID: {cart_b.id}")
            print(f"Status: {cart_b.status}")
            print(f"Items count: {len(cart_b.items)}")
            for item in cart_b.items:
                print(f"  - Item ID: {item.id}, Listing ID: {item.listing_id}, Qty: {item.quantity}")

        # Verification Assertions
        assert cart_a is not None and cart_b is not None, "Both carts should exist separately"
        assert cart_a.id != cart_b.id, "Cart IDs must be distinct"
        assert cart_a.user_id != cart_b.user_id, "Cart User IDs must be distinct"
        assert len(cart_a.items) == 1 and str(cart_a.items[0].listing_id) == listing_a, "Cart A should contain only Listing A"
        assert len(cart_b.items) == 1 and str(cart_b.items[0].listing_id) == listing_b, "Cart B should contain only Listing B"

        print("\n" + "=" * 80)
        print("SUCCESS: Anonymous Guest Carts are 100% independent and isolated!")
        print("=" * 80)

if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run_item1_after_test())
