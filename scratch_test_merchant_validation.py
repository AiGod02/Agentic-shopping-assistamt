"""
Test script for ChatRequest.merchant_id database validation
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

from shared.db.session import init_db_engine, get_db_session
from agent_server.main import app as agent_app
from merchant_server.domain.models.merchant import Merchant
from sqlalchemy import select


async def run_validation_test():
    print("=" * 80)
    print("TESTING CHATREQUEST.MERCHANT_ID DATABASE VALIDATION")
    print("=" * 80)

    engine = init_db_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/commerce_platform")

    async with get_db_session() as db:
        res = await db.execute(select(Merchant).where(Merchant.status == "active").limit(1))
        active_merchant = res.scalars().first()
        valid_merchant_id = str(active_merchant.id)
        print(f"Valid Active Merchant ID from DB: {valid_merchant_id}")

    async with AsyncClient(transport=ASGITransport(app=agent_app), base_url="http://test") as client:
        # Test 1: Invalid UUID format
        print("\n--- Test 1: Invalid UUID format ('invalid-uuid-format') ---")
        resp1 = await client.post("/api/v1/agent/chat", json={"message": "hello", "merchant_id": "invalid-uuid-format"})
        print(f"Status Code: {resp1.status_code}")
        print(f"Payload: {resp1.json()}")
        assert resp1.status_code == 400, f"Expected 400, got {resp1.status_code}"

        # Test 2: Non-existent Merchant ID
        fake_id = str(uuid.uuid4())
        print(f"\n--- Test 2: Non-existent Merchant ID ('{fake_id}') ---")
        resp2 = await client.post("/api/v1/agent/chat", json={"message": "hello", "merchant_id": fake_id})
        print(f"Status Code: {resp2.status_code}")
        print(f"Payload: {resp2.json()}")
        assert resp2.status_code == 404, f"Expected 404, got {resp2.status_code}"

        # Test 3: Valid Active Merchant ID
        print(f"\n--- Test 3: Valid Active Merchant ID ('{valid_merchant_id}') ---")
        resp3 = await client.post("/api/v1/agent/chat", json={"message": "hello", "merchant_id": valid_merchant_id})
        print(f"Status Code: {resp3.status_code}")
        print(f"Response: {resp3.json().get('response')[:100]}...")
        assert resp3.status_code == 200, f"Expected 200, got {resp3.status_code}"

        print("\n" + "=" * 80)
        print("SUCCESS: ChatRequest.merchant_id Database Validation 100% Verified!")
        print("=" * 80)

if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(run_validation_test())
