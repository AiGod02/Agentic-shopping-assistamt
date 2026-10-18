import asyncio
from shared.db.session import init_db_engine, get_db_session
from sqlalchemy import text
from agent_server.config import settings

async def f():
    init_db_engine(settings.database_url)
    async with get_db_session() as db:
        r = await db.execute(text("SELECT id, business_name FROM merchants"))
        for row in r.fetchall():
            print(f"ID: {row[0]} | Name: {row[1]}")

if __name__ == "__main__":
    asyncio.run(f())
