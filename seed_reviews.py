import uuid
import asyncio
from datetime import datetime
from sqlalchemy import select
from shared.db.session import get_db_session
from merchant_server.domain.models.listing import Listing
from merchant_server.domain.models.review import Review
from merchant_server.domain.models.user import User

async def seed_reviews():
    async with get_db_session() as db:
        # Get first listing and user
        listing = (await db.execute(select(Listing).limit(1))).scalar()
        user = (await db.execute(select(User).limit(1))).scalar()

        if not listing or not user:
            print("No listing or user found. Please create one first!")
            return

        reviews = [
            Review(
                user_id=user.id,
                listing_id=listing.id,
                rating=5,
                title="Amazing Experience!",
                body=f"I absolutely loved the {listing.title}. The quality is top-notch and it arrived much faster than expected. Highly recommend!",
                status="approved",
                is_verified=True,
            ),
            Review(
                user_id=user.id,
                listing_id=listing.id,
                rating=4,
                title="Pretty good, but room for improvement",
                body=f"The {listing.title} is overall great. My only minor issue was the packaging could have been sturdier. But the item itself is perfect.",
                status="approved",
                is_verified=True,
            ),
            Review(
                user_id=user.id,
                listing_id=listing.id,
                rating=2,
                title="Not what I expected",
                body=f"Honestly, some parts of the {listing.title} felt a bit cheap. It works, but I expected more for the price.",
                status="approved",
                is_verified=True,
            )
        ]

        db.add_all(reviews)
        await db.commit()
        print(f"Seeded {len(reviews)} reviews for '{listing.title}'!")

if __name__ == "__main__":
    asyncio.run(seed_reviews())
