"""
Run multi-turn verification test transcript for the 7 specified turns in intent.md Part 4.
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


async def run_test():
    engine = init_db_engine(settings.database_url)
    async with get_db_session() as db:
        session_mgr = SessionManager(db)
        session = await session_mgr.create_session()
        session_id = session["id"]

        orchestrator = AgentOrchestrator(session_mgr)

        turns = [
            "Show me running shoes under $100",
            "Tell me about the second one",
            "What do people say about it?",
            "Show me other options",
            "Compare the first two",
            "Add the cheaper one to my cart",
            "Actually never mind, show me something in blue instead",
        ]

        print("================================================================================")
        print("PART 4 — MULTI-TURN TEST TRANSCRIPT (7 TURNS END-TO-END)")
        print("================================================================================\n")

        for i, text in enumerate(turns, 1):
            print(f"--- TURN {i}: \"{text}\" ---")
            res = await orchestrator.process_message(session_id=session_id, user_message=text)
            
            # Retrieve updated dialogue state
            ds = await session_mgr.get_dialogue_state(session_id)
            
            tools_used = [tc["tool"] for tc in res.get("tool_calls", [])]
            print(f"User Request : \"{text}\"")
            print(f"Tool Executed: {tools_used}")
            print(f"Focused ID   : {ds.focused_listing_id}")
            print(f"Shown Count  : {len(ds.last_shown_listings)}")
            safe_resp = res['response'][:250].encode('ascii', 'ignore').decode('ascii')
            print(f"Response Snippet:\n{safe_resp}...\n")

if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run_test())
