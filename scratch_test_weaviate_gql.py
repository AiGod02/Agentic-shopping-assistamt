import asyncio
import httpx
from agent_server.config import settings
from agent_server.core.search import WeaviateSearch

async def test():
    search = WeaviateSearch()
    print("Base URL:", search.base_url)
    print("Headers:", search.headers)
    gql = search._build_graphql(query="laptop", where_filter=None, limit=5, alpha=0.8)
    print("GraphQL Query:\n", gql)
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(f"{search.base_url}/v1/graphql", json={"query": gql}, headers=search.headers)
            print("Status Code:", res.status_code)
            print("Response:", res.text)
        except Exception as e:
            print("HTTP Exception:", type(e).__name__, str(e))

if __name__ == '__main__':
    asyncio.run(test())
