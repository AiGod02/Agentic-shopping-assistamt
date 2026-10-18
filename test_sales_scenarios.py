import sys
import asyncio
import uuid
import httpx

sys.stdout.reconfigure(encoding='utf-8')

AGENT_URL = "http://127.0.0.1:8001/api/v1/agent/chat"

async def run_scenario(name: str, messages: list[str]):
    print(f"\n=======================================================")
    print(f"  RUNNING SCENARIO: {name}")
    print(f"=======================================================")
    session_id = str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=120.0) as client:
        for msg in messages:
            print(f"\nUser: \"{msg}\"")
            res = await client.post(AGENT_URL, json={"session_id": session_id, "message": msg})
            if res.status_code == 200:
                data = res.json()
                print(f"Agent:\n{data.get('response')}")
            else:
                print(f"Error {res.status_code}: {res.text}")

async def main():
    # Transcript A — vague opening, discovery first
    await run_scenario("Transcript A - Discovery First", [
        "I need a laptop",
        "My budget is around $1500 and I need it for professional video editing and software engineering."
    ])

    # Transcript B — price objection handling
    await run_scenario("Transcript B - Price Objection", [
        "Find me a MacBook Pro",
        "That's a bit too expensive"
    ])

    # Transcript C — comparison paralysis
    await run_scenario("Transcript C - Comparison Paralysis", [
        "Find laptops",
        "I can't decide between these two"
    ])

    # Transcript D — ready to buy
    await run_scenario("Transcript D - Ready to Buy", [
        "Search for MacBook Pro 16",
        "Okay I'll take the first one"
    ])

    # Transcript E — honesty check
    await run_scenario("Transcript E - Honesty Check", [
        "Tell me about the LG C4 65 OLED TV",
        "I need something portable for high performance coding on flights, is this TV good for that?"
    ])

if __name__ == "__main__":
    asyncio.run(main())
