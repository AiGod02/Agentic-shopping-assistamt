import asyncio
import httpx

async def inspect_db():
    async with httpx.AsyncClient() as client:
        res = await client.get("http://localhost:8002/api/v1/listings?page_size=100")
        items = res.json().get("items", [])
        print(f"TOTAL LISTINGS IN DB: {len(items)}")
        for i in items:
            print(f"DB ID: {i['id']} | Title: {i['title']} | Type: {i['type']} | Price: ${i['base_price']} | Tags: {i.get('tags')}")

if __name__ == "__main__":
    asyncio.run(inspect_db())
