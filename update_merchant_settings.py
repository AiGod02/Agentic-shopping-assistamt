import asyncio
import sys
import pathlib

project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agent_server"))
sys.path.insert(0, str(project_root / "merchant_server"))

from agent_server.config import settings
from shared.db.session import init_db_engine, get_db_session
from sqlalchemy import text
import json

async def update_settings():
    init_db_engine(settings.database_url)
    default_settings = {
        "business_hours": "Mon-Fri: 9:00 AM - 6:00 PM EST, Sat: 10:00 AM - 4:00 PM EST",
        "shipping_policy": "Free standard shipping on orders over $50. Standard delivery takes 3-5 business days.",
        "contact_info": {
            "email": "support@techmerchant.com",
            "phone": "+1-800-555-0199",
            "address": "100 Tech Plaza, Suite 400, San Francisco, CA"
        },
        "location": "San Francisco, CA"
    }
    async with get_db_session() as db:
        res = await db.execute(text("SELECT id, business_name FROM merchants"))
        rows = res.fetchall()
        for row in rows:
            m_id = str(row[0])
            await db.execute(
                text("UPDATE merchants SET settings = :settings WHERE id = :id"),
                {"settings": json.dumps(default_settings), "id": row[0]}
            )
            print(f"Updated merchant {m_id} ({row[1]}) settings.")
        await db.commit()
    print("All merchant settings updated successfully!")

if __name__ == "__main__":
    asyncio.run(update_settings())
