import asyncio
import httpx
from agent_server.config import settings
from agent_server.core.search import WeaviateSearch

async def test():
    search = WeaviateSearch()
    where_filter = search._build_filter(None, None, None, None, None)
    gql = search._build_graphql("laptop", where_filter, 5, 0.8)
    print("GQL QUERY:\n", gql)
    async with httpx.AsyncClient() as client:
        res = await client.post(f"{search.base_url}/v1/graphql", json={"query": gql}, headers=search.headers)
        print("STATUS:", res.status_code)
        print("JSON BODY:", res.json())

if __name__ == '__main__':
    asyncio.run(test())
