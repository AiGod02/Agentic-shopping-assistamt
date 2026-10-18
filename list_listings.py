import asyncio
from shared.db.session import init_db_engine, get_db_session
from sqlalchemy import text
from agent_server.config import settings

async def main():
    init_db_engine(settings.database_url)
    async with get_db_session() as db:
        r = await db.execute(text("SELECT * FROM listings LIMIT 1"))
        row = r.fetchone()
        print(dict(row._mapping) if row else "No listing")

if __name__ == "__main__":
    asyncio.run(main())
