import asyncio
from shared.db.session import init_db_engine, get_db_session
from sqlalchemy import text
from agent_server.config import settings

async def main():
    engine = init_db_engine(settings.database_url)
    async with get_db_session() as db:
        res = await db.execute(text("SELECT id, email, role FROM users LIMIT 5"))
        rows = res.fetchall()
        print("USERS:", rows)

if __name__ == "__main__":
    asyncio.run(main())
