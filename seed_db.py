import json
import asyncio
import sys
import os
import uuid
from decimal import Decimal
from passlib.hash import bcrypt

import pathlib

# Add paths to python system path dynamically
project_root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "agent_server"))
sys.path.insert(0, str(project_root / "merchant_server"))

from agent_server.config import settings
from shared.db.session import init_db_engine, get_db_session
from merchant_server.domain.models.user import User
from merchant_server.domain.models.merchant import Merchant
from merchant_server.domain.models.listing import Listing
from merchant_server.domain.models.variant import Variant
from merchant_server.domain.models.cart import Cart
from merchant_server.domain.models.booking import Booking
from merchant_server.domain.models.order import Order
from merchant_server.domain.models.review import Review
from merchant_server.domain.models.webhook import MerchantWebhook
from merchant_server.domain.models.availability import AvailabilityBlock
from agent_server.core.chroma_search import ChromaSearch

async def seed():
    # Load products mock data
    products_path = project_root / "frontend" / "src" / "data" / "products.json"
    with open(products_path, "r", encoding="utf-8") as f:
        products = json.load(f)
        
    print(f"Loaded {len(products)} products from products.json")

    # Ensure database exists and create tables if missing
    from shared.db.session import ensure_db_and_tables
    await ensure_db_and_tables(settings.database_url)
    print("Database and tables created/verified!")
    
    async with get_db_session() as db:
        # Check if users already exist or create them
        from sqlalchemy import select
        
        # 1. Create Merchant User
        merchant_email = "merchant@example.com"
        result = await db.execute(select(User).where(User.email == merchant_email))
        merchant_user = result.scalar_one_or_none()
        
        if not merchant_user:
            merchant_user = User(
                email=merchant_email,
                password_hash=bcrypt.hash("password"),
                full_name="Default Merchant User",
                role="merchant",
                is_active=True,
                email_verified=True,
            )
            db.add(merchant_user)
            await db.flush()  # to get ID
            print("Created merchant user.")
        else:
            merchant_user.password_hash = bcrypt.hash("password")
            db.add(merchant_user)
            print("Merchant user already exists. Password updated/verified.")
            
        # 2. Create Merchant
        result = await db.execute(select(Merchant).where(Merchant.user_id == merchant_user.id))
        merchant = result.scalar_one_or_none()
        
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

        if not merchant:
            merchant = Merchant(
                user_id=merchant_user.id,
                business_name="Default Merchant Business",
                business_type="Retail",
                verification_status="verified",
                is_active=True,
                settings=default_settings,
            )
            db.add(merchant)
            await db.flush()
            print(f"Created merchant profile with ID: {merchant.id}")
        else:
            merchant.settings = default_settings
            db.add(merchant)
            print(f"Merchant profile already exists with ID: {merchant.id}. Settings updated.")
            
        # Associate merchant_id with merchant_user metadata
        merchant_user.metadata = {"merchant_id": str(merchant.id)}
        db.add(merchant_user)
            
        # 3. Create Customer User
        customer_email = "customer@example.com"
        result = await db.execute(select(User).where(User.email == customer_email))
        customer_user = result.scalar_one_or_none()
        
        if not customer_user:
            customer_user = User(
                email=customer_email,
                password_hash=bcrypt.hash("password"),
                full_name="John Doe",
                role="customer",
                is_active=True,
                email_verified=True,
            )
            db.add(customer_user)
            await db.flush()
            print("Created customer user.")
        else:
            customer_user.password_hash = bcrypt.hash("password")
            db.add(customer_user)
            print("Customer user already exists. Password updated/verified.")

        # 3.5. Create Admin User
        admin_email = "admin@example.com"
        result = await db.execute(select(User).where(User.email == admin_email))
        admin_user = result.scalar_one_or_none()
        
        if not admin_user:
            admin_user = User(
                email=admin_email,
                password_hash=bcrypt.hash("password"),
                full_name="Platform Administrator",
                role="admin",
                is_active=True,
                email_verified=True,
            )
            db.add(admin_user)
            await db.flush()
            print("Created admin user.")
        else:
            admin_user.password_hash = bcrypt.hash("password")
            db.add(admin_user)
            print("Admin user already exists. Password updated/verified.")

        # 4. Create Listings & Variants
        chroma = ChromaSearch()
        
        # Clear or verify collection first
        await chroma.create_schema()
        
        for p in products:
            # Check if listing already exists by title
            result = await db.execute(select(Listing).where(Listing.title == p["name"]))
            existing_listing = result.scalars().first()
            
            if existing_listing:
                print(f"Listing '{p['name']}' already exists in database. Syncing to ChromaDB...")
                # Sync existing to ChromaDB
                payload = {
                    "id": str(existing_listing.id),
                    "title": existing_listing.title,
                    "description": existing_listing.description or "",
                    "type": existing_listing.type,
                    "base_price": float(existing_listing.base_price),
                    "currency": existing_listing.currency,
                    "tags": existing_listing.tags or [],
                    "rating_avg": float(existing_listing.rating_avg),
                    "merchant_id": str(existing_listing.merchant_id),
                    "status": existing_listing.status,
                }
                await chroma.create_listing_object(payload)
                continue
                
            listing = Listing(
                merchant_id=merchant.id,
                type=p["type"],
                title=p["name"],
                description=p["description"],
                base_price=Decimal(str(p["price"])),
                currency=p["currency"],
                status="active",
                tags=p["tags"],
                rating_avg=Decimal(str(p["rating"])),
                rating_count=p["reviews_count"],
                location=p.get("location", {}),
                media=[{"url": p.get("image", "📦")}],
            )
            db.add(listing)
            await db.flush()
            
            # Add variants if any
            for v in p.get("variants", []):
                variant = Variant(
                    listing_id=listing.id,
                    name=v["name"],
                    price_override=Decimal(str(v["price"])),
                    inventory_count=100,
                    is_active=True,
                )
                db.add(variant)
                
            # Sync to ChromaDB
            payload = {
                "id": str(listing.id),
                "title": listing.title,
                "description": listing.description or "",
                "type": listing.type,
                "base_price": float(listing.base_price),
                "currency": listing.currency,
                "tags": listing.tags or [],
                "rating_avg": float(listing.rating_avg),
                "merchant_id": str(listing.merchant_id),
                "status": listing.status,
            }
            success = await chroma.create_listing_object(payload)
            if success:
                print(f"Indexed: {listing.title} -> ChromaDB")
            else:
                print(f"Failed to index: {listing.title} to ChromaDB")
                
        await db.commit()
        print("Seeding complete!")

if __name__ == "__main__":
    asyncio.run(seed())
