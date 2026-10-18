import asyncio
from agent_server.core.chroma_search import ChromaSearch

async def run_part4_verification():
    s = ChromaSearch()
    
    print("\n=======================================================")
    print(" 1. RE-RUN FAILING CASE: query='laptop'")
    print("=======================================================")
    res_laptop = await s.hybrid_search('laptop', limit=10)
    print(f"COUNT: {len(res_laptop)}")
    for item in res_laptop:
        print(f"• ID: {item.get('id')} | Title: {item.get('title')} | Type: {item.get('type')} | Price: ${item.get('base_price')} | Score: {item.get('score'):.4f}")

    print("\n=======================================================")
    print(" 2. CATEGORY TESTS: query='phone', 'TV', 'tablet'")
    print("=======================================================")
    for q in ["phone", "TV", "tablet"]:
        res = await s.hybrid_search(q, limit=10)
        print(f"\nQuery: '{q}' — COUNT: {len(res)}")
        for item in res:
            print(f"  - {item.get('title')} (${item.get('base_price')}) | Type: {item.get('type')} | Score: {item.get('score'):.4f}")

    print("\n=======================================================")
    print(" 3. BROAD / AMBIGUOUS QUERY: query='something for work'")
    print("=======================================================")
    res_broad = await s.hybrid_search('something for work', limit=5)
    print(f"COUNT: {len(res_broad)}")
    for item in res_broad:
        print(f"  - {item.get('title')} (${item.get('base_price')}) | Type: {item.get('type')} | Score: {item.get('score'):.4f}")

if __name__ == "__main__":
    asyncio.run(run_part4_verification())
