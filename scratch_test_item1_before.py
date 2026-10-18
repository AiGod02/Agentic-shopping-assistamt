"""
Item 1 BEFORE Fix Test: Guest Cart Collision Test
"""

import asyncio
import os
import sys
import pathlib

project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agent_server"))

from agent_server.config import settings
from shared.db.session import init_db_engine, get_db_session
from agent_server.core.session_manager import SessionManager
from agent_server.core.orchestrator import AgentOrchestrator
from merchant_server.domain.services.cart_service import CartService
from merchant_server.domain.models.listing import Listing
from sqlalchemy import select


async def run_item1_before_test():
    print("=" * 80)
    print("ITEM 1 — BEFORE FIX GUEST CART COLLISION LIVE TEST")
    print("=" * 80)

    engine = init_db_engine(settings.database_url)

    async with get_db_session() as db:
        # Get 2 real listing IDs from DB
        stmt = select(Listing).limit(2)
        res = await db.execute(stmt)
        listings = res.scalars().all()
        if len(listings) < 2:
            print("Error: Less than 2 listings in database!")
            return

        listing_a = str(listings[0].id)
        listing_b = str(listings[1].id)
        print(f"Listing A: {listings[0].title} ({listing_a})")
        print(f"Listing B: {listings[1].title} ({listing_b})")

        session_mgr = SessionManager(db)

        # Create Session A and Session B anonymously (user_id=None)
        session_a = await session_mgr.create_session()
        session_b = await session_mgr.create_session()
        session_a_id = session_a["id"]
        session_b_id = session_b["id"]
        print(f"\nCreated Session A ID: {session_a_id}")
        print(f"Created Session B ID: {session_b_id}")

        orchestrator_a = AgentOrchestrator(session_mgr)
        orchestrator_b = AgentOrchestrator(session_mgr)

        # Process message in Session A: "add listing_a to cart"
        print("\n--- Session A Request: Add Listing A to cart ---")
        # Anonymous user: user_token=""
        res_a = await orchestrator_a.process_message(
            session_id=session_a_id,
            user_message=f"add listing {listing_a} to cart",
            user_token="",
        )
        print(f"Session A Response:\n{res_a['response']}")
        print(f"Session A Tool Calls: {[t['tool'] for t in res_a.get('tool_calls', [])]}")

        # Process message in Session B: "add listing_b to cart"
        print("\n--- Session B Request: Add Listing B to cart ---")
        res_b = await orchestrator_b.process_message(
            session_id=session_b_id,
            user_message=f"add listing {listing_b} to cart",
            user_token="",
        )
        print(f"Session B Response:\n{res_b['response']}")
        print(f"Session B Tool Calls: {[t['tool'] for t in res_b.get('tool_calls', [])]}")

        # Query Cart directly from Merchant Server CartService
        cart_service = CartService(db)

        # What customer_id was used for Session A and Session B?
        # Let's inspect carts in DB!
        from merchant_server.domain.models.cart import Cart
        carts_stmt = select(Cart)
        carts_res = await db.execute(carts_stmt)
        carts = carts_res.scalars().all()

        print("\n" + "=" * 80)
        print("DIRECT DB/API READ-BACK RESULT (BEFORE FIX)")
        print("=" * 80)
        print(f"Total Cart records in DB: {len(carts)}")
        for c in carts:
            print(f"\nCart ID: {c.id}")
            print(f"User ID: {c.user_id}")
            print(f"Status: {c.status}")
            print(f"Items count: {len(c.items)}")
            for item in c.items:
                print(f"  - Item ID: {item.id}, Listing ID: {item.listing_id}, Qty: {item.quantity}")

if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run_item1_before_test())
