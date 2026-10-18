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

async def run_item2_tests():
    init_db_engine(settings.database_url)
    
    async with get_db_session() as db:
        session_mgr = SessionManager(db)
        orchestrator = AgentOrchestrator(session_mgr)
        
        # Get a valid merchant ID from DB
        res = await db.execute(text("SELECT id FROM merchants LIMIT 1"))
        merchant_id = str(res.scalar_one())

        print("=" * 70)
        print("ITEM 2 — MERCHANT_INFO INTENT TESTS")
        print("=" * 70)

        session = await session_mgr.create_session()
        state = await session_mgr.get_dialogue_state(session["id"])
        state.merchant_id = merchant_id
        await session_mgr.update_dialogue_state(session["id"], state)

        queries = [
            ("Configured: Business Hours", "What are your store business hours?"),
            ("Configured: Shipping Policy", "What is your shipping policy?"),
            ("Configured: Contact Info & Location", "How can I contact support and where are you located?"),
            ("Unconfigured: Return Policy", "What is your return policy?"), # return_policy was intentionally unconfigured!
        ]

        for label, q in queries:
            print(f"\n--- [{label}] ---")
            print(f"USER: {q}")
            resp = await orchestrator.process_message(session["id"], q)
            print(f"AGENT: {resp['response']}")
            print(f"TOOL CALLS: {resp.get('tool_calls', [])}")

if __name__ == "__main__":
    asyncio.run(run_item2_tests())
