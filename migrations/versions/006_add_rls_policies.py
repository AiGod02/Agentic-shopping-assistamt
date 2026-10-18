"""Add PostgreSQL Row-Level Security (RLS) policies for tenant isolation.

Revision ID: 006
Revises: 005
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable Row-Level Security on listings and orders
    op.execute("ALTER TABLE listings ENABLE ROW LEVEL SECURITY;")
    
    # Create Listings policy:
    # 1. Anyone (including customers) can SELECT active listings.
    # 2. Merchants can perform CRUD operations on their own listings if their tenant ID matches app.current_merchant_id
    op.execute("""
        CREATE POLICY listings_tenant_policy ON listings 
        FOR ALL 
        USING (
            status = 'active' 
            OR merchant_id = NULLIF(current_setting('app.current_merchant_id', true), '')::uuid
        )
        WITH CHECK (
            merchant_id = NULLIF(current_setting('app.current_merchant_id', true), '')::uuid
        );
    """)

    # Enable RLS on order_items
    op.execute("ALTER TABLE order_items ENABLE ROW LEVEL SECURITY;")

    # Create Order Items policy:
    # Merchants can only view order items belonging to listings they own
    op.execute("""
        CREATE POLICY order_items_tenant_policy ON order_items
        FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM listings 
                WHERE listings.id = order_items.listing_id 
                AND listings.merchant_id = NULLIF(current_setting('app.current_merchant_id', true), '')::uuid
            )
        );
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS order_items_tenant_policy ON order_items;")
    op.execute("ALTER TABLE order_items DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS listings_tenant_policy ON listings;")
    op.execute("ALTER TABLE listings DISABLE ROW LEVEL SECURITY;")
