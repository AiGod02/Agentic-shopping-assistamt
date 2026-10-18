import asyncio
import httpx
from agent_server.config import settings
from agent_server.core.search import WeaviateSearch

async def test():
    search = WeaviateSearch()
    print("Executing Weaviate hybrid_search directly...")
    try:
        results = await search.hybrid_search(query="laptop", limit=5)
        print("Hybrid Search Results Count:", len(results))
        for r in results:
            print(" - Result:", r)
    except Exception as e:
        print("Hybrid Search Error:", type(e).__name__, str(e))

if __name__ == '__main__':
    asyncio.run(test())
