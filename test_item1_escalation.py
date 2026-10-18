import asyncio
import sys
import pathlib

sys.stdout.reconfigure(encoding='utf-8')

project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agent_server"))
sys.path.insert(0, str(project_root / "merchant_server"))

from agent_server.config import settings
from shared.db.session import init_db_engine, get_db_session
from agent_server.core.session_manager import SessionManager
from agent_server.core.orchestrator import AgentOrchestrator
from sqlalchemy import text

async def run_item1_tests():
    init_db_engine(settings.database_url)
    
    async with get_db_session() as db:
        session_mgr = SessionManager(db)
        orchestrator = AgentOrchestrator(session_mgr)
        
        # Get a valid merchant ID from DB
        res = await db.execute(text("SELECT id FROM merchants LIMIT 1"))
        merchant_id = str(res.scalar_one())

        print("=" * 70)
        print("ITEM 1 — ESCALATE_TO_HUMAN INTENT TESTS")
        print("=" * 70)

        # -------------------------------------------------------------
        # PATH A: Explicit Request for Human Support
        # -------------------------------------------------------------
        session_a = await session_mgr.create_session()
        state_a = await session_mgr.get_dialogue_state(session_a["id"])
        state_a.merchant_id = merchant_id
        await session_mgr.update_dialogue_state(session_a["id"], state_a)

        user_msg_a = "I want to speak to a human support agent please"
        resp_a = await orchestrator.process_message(session_a["id"], user_msg_a)

        print("\n--- [PATH A: Explicit Support Request Transcript] ---")
        print(f"USER: {user_msg_a}")
        print(f"AGENT: {resp_a['response']}")
        print(f"TOOL CALLS: {resp_a.get('tool_calls', [])}")

        # -------------------------------------------------------------
        # PATH B: Repeated Unclear / Unresolved Turns (2+ in a row)
        # -------------------------------------------------------------
        session_b = await session_mgr.create_session()
        state_b = await session_mgr.get_dialogue_state(session_b["id"])
        state_b.merchant_id = merchant_id
        await session_mgr.update_dialogue_state(session_b["id"], state_b)

        print("\n--- [PATH B: Repeated Unclear Turns Transcript] ---")
        unclear_msgs = [
            "asdfghjkl zxcvbnm",   # Turn 1: Unclear
            "qwerty uiop 12345",   # Turn 2: Unclear -> triggers auto-escalation!
        ]

        for i, msg in enumerate(unclear_msgs, 1):
            resp = await orchestrator.process_message(session_b["id"], msg)
            state_curr = await session_mgr.get_dialogue_state(session_b["id"])
            print(f"\nTurn {i}:")
            print(f"USER: {msg}")
            print(f"AGENT: {resp['response']}")
            print(f"STATE consecutive_unclear_turns: {state_curr.consecutive_unclear_turns}")

if __name__ == "__main__":
    asyncio.run(run_item1_tests())
