import asyncio
import sys
import json
import pathlib

project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agent_server"))

from agent_server.config import settings
from shared.db.session import init_db_engine, get_db_session
from agent_server.core.session_manager import SessionManager
from agent_server.core.orchestrator import AgentOrchestrator
from shared.auth.jwt_handler import JWTHandler
from agent_server.tools.commerce_tools import view_cart

async def test_journeys():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        
    jwt_h = JWTHandler(secret_key=settings.jwt_secret_key)
    user_token = jwt_h.create_access_token(user_id="905e50a3-80b9-4a96-a10c-56ef92989fe7", role="customer")
    engine = init_db_engine(settings.database_url)
    
    async with get_db_session() as db:
        session_mgr = SessionManager(db)
        orchestrator = AgentOrchestrator(session_mgr)
        
        print("=========================================")
        print("=== JOURNEY B — Comparison and indecision ===")
        print("=========================================")
        jb = await session_mgr.create_session()
        turns_b = [
            "show me laptops",
            "compare it with something cheaper",
            "actually show me something else instead",
            "never mind, add the first one to cart"
        ]
        for t in turns_b:
            print(f"\nUser: {t}")
            r = await orchestrator.process_message(jb["id"], t, user_token)
            print(f"Agent:\n{r['response']}")

        print("\n=========================================")
        print("=== JOURNEY C — Objection and recovery ===")
        print("=========================================")
        jc = await session_mgr.create_session()
        turns_c = [
            "show me a MacBook",
            "that's too expensive",
            "okay fine, add it anyway",
            "wait, remove it, I changed my mind"
        ]
        for t in turns_c:
            print(f"\nUser: {t}")
            r = await orchestrator.process_message(jc["id"], t, user_token)
            print(f"Agent:\n{r['response']}")
            
        cart_after_c = await view_cart(user_token=user_token)
        print(f"\n[INDEPENDENT CART READBACK JOURNEY C]: {cart_after_c}")

        print("\n=========================================")
        print("=== JOURNEY D — Ambiguous and broken references ===")
        print("=========================================")
        jd = await session_mgr.create_session()
        turns_d = [
            "tell me about reviews",
            "the second one"
        ]
        for t in turns_d:
            print(f"\nUser: {t}")
            r = await orchestrator.process_message(jd["id"], t, user_token)
            print(f"Agent:\n{r['response']}")

        print("\n=========================================")
        print("=== JOURNEY E — Repeated/contradicted requests ===")
        print("=========================================")
        je = await session_mgr.create_session()
        turns_e = [
            "show me laptops",
            "show me laptops",
            "add it to cart",
            "add it to cart"
        ]
        for t in turns_e:
            print(f"\nUser: {t}")
            r = await orchestrator.process_message(je["id"], t, user_token)
            print(f"Agent:\n{r['response']}")

        cart_after_e = await view_cart(user_token=user_token)
        print(f"\n[INDEPENDENT CART READBACK JOURNEY E]: {cart_after_e}")

        print("\n=========================================")
        print("=== JOURNEY F — Mid-conversation topic switch ===")
        print("=========================================")
        jf = await session_mgr.create_session()
        turns_f = [
            "show me laptops",
            "actually, do you have any monitors"
        ]
        for t in turns_f:
            print(f"\nUser: {t}")
            r = await orchestrator.process_message(jf["id"], t, user_token)
            print(f"Agent:\n{r['response']}")

if __name__ == "__main__":
    asyncio.run(test_journeys())
