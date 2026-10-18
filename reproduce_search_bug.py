import asyncio
from agent_server.core.chroma_search import ChromaSearch

async def test_search():
    s = ChromaSearch()
    res = await s.hybrid_search('laptop', limit=10)
    print(f"SEARCH RESULTS COUNT: {len(res)}")
    for item in res:
        print(f"ID: {item.get('id')} | Title: {item.get('title')} | Type: {item.get('type')} | Price: ${item.get('base_price')} | Score: {item.get('score')} | Source: {item.get('source')}")

if __name__ == "__main__":
    asyncio.run(test_search())
