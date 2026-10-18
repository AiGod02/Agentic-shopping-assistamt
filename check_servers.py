import httpx
import asyncio

async def check():
    for port in [8001, 8002, 8003]:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                res = await client.get(f"http://localhost:{port}/health")
                print(f"Port {port}: {res.status_code}")
        except Exception as e:
            print(f"Port {port}: Down ({e})")

if __name__ == "__main__":
    asyncio.run(check())
