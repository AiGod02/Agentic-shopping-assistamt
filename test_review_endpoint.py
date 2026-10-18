import asyncio
import uuid
from shared.db.session import init_db_engine, get_db_session
from merchant_server.api.v1.listings import list_reviews, ReviewResponse

async def main():
    engine = init_db_engine('postgresql+asyncpg://commerce:commerce_secret@localhost:5432/commerce_platform')
    async with get_db_session() as db:
        res = await list_reviews(listing_id=uuid.UUID('e2d20295-dc7b-4f06-87e8-98d359e82d0d'), page=1, page_size=20, db=db)
        print("Success:", res)

if __name__ == "__main__":
    asyncio.run(main())
