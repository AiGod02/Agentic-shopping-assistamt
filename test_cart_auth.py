import httpx
import asyncio
from shared.auth.jwt_handler import JWTHandler
from agent_server.config import settings

async def main():
    jwt_h = JWTHandler(secret_key=settings.jwt_secret_key)
    token = jwt_h.create_access_token("00000000-0000-0000-0000-000000000001", "customer")
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        res = await client.get("http://127.0.0.1:8002/api/v1/cart", headers=headers)
        print("STATUS:", res.status_code)
        print("RESPONSE:", res.text)

if __name__ == "__main__":
    asyncio.run(main())
