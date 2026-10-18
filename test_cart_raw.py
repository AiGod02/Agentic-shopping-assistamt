import httpx
import asyncio

async def main():
    async with httpx.AsyncClient() as client:
        res = await client.get("http://127.0.0.1:8002/api/v1/cart")
        print("STATUS:", res.status_code)
        print("RESPONSE:", res.text)

if __name__ == "__main__":
    asyncio.run(main())
