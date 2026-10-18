"""
Part 4 Regression Test Script for Cart Fix
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


async def run_part4_test():
    engine = init_db_engine(settings.database_url)
    async with get_db_session() as db:
        session_mgr = SessionManager(db)
        session = await session_mgr.create_session()
        session_id = session["id"]

        orchestrator = AgentOrchestrator(session_mgr)

        turns = [
            "i am looking for a laptop",
            "show me MacBook Pro 16",
            "what do users say about this",
            "compare it",
            "give me more details",
            "add it to cart",
            "checkout",
        ]

        print("================================================================================")
        print("PART 4 — REAL CONVERSATION TRANSCRIPT")
        print("================================================================================\n")

        from shared.auth.jwt_handler import JWTHandler
        jwt_h = JWTHandler(secret_key=settings.jwt_secret_key)
        user_token = jwt_h.create_access_token(
            user_id="905e50a3-80b9-4a96-a10c-56ef92989fe7",
            role="customer",
        )

        for i, text in enumerate(turns, 1):
            print(f"Turn {i}: User: \"{text}\"")
            res = await orchestrator.process_message(session_id=session_id, user_message=text, user_token=user_token)
            tools = [tc["tool"] for tc in res.get("tool_calls", [])]
            print(f"Tool Calls: {tools}")
            print(f"Agent Response:\n{res['response']}\n")

            if text == "add it to cart":
                print("--- [DB LEVEL CART PERSISTENCE CHECK] ---")
                ds = await session_mgr.get_dialogue_state(session_id)
                print(f"DialogueState Focused Listing ID: {ds.focused_listing_id}")
                print("--- End DB Check ---\n")

if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run_part4_test())
