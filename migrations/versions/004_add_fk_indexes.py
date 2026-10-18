"""Add indexes to foreign keys to optimize PostgreSQL join performance.

Revision ID: 004
Revises: 003
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # availability_blocks
    op.create_index("idx_avail_variant", "availability_blocks", ["variant_id"])

    # cart_items
    op.create_index("idx_cart_items_listing", "cart_items", ["listing_id"])
    op.create_index("idx_cart_items_variant", "cart_items", ["variant_id"])

    # order_items
    op.create_index("idx_order_items_listing", "order_items", ["listing_id"])
    op.create_index("idx_order_items_variant", "order_items", ["variant_id"])

    # bookings
    op.create_index("idx_bookings_order", "bookings", ["order_id"])
    op.create_index("idx_bookings_variant", "bookings", ["variant_id"])
    op.create_index("idx_bookings_block", "bookings", ["availability_block_id"])

    # payments
    op.create_index("idx_payments_user", "payments", ["user_id"])

    # refunds
    op.create_index("idx_refunds_initiator", "refunds", ["initiated_by"])

    # escrow_holds
    op.create_index("idx_escrow_order", "escrow_holds", ["order_id"])

    # ledger_entries
    op.create_index("idx_ledger_refund", "ledger_entries", ["refund_id"])
    op.create_index("idx_ledger_escrow", "ledger_entries", ["escrow_id"])

    # reviews
    op.create_index("idx_reviews_order", "reviews", ["order_id"])
    op.create_index("idx_reviews_booking", "reviews", ["booking_id"])


def downgrade() -> None:
    op.drop_index("idx_reviews_booking")
    op.drop_index("idx_reviews_order")
    op.drop_index("idx_ledger_escrow")
    op.drop_index("idx_ledger_refund")
    op.drop_index("idx_escrow_order")
    op.drop_index("idx_refunds_initiator")
    op.drop_index("idx_payments_user")
    op.drop_index("idx_bookings_block")
    op.drop_index("idx_bookings_variant")
    op.drop_index("idx_bookings_order")
    op.drop_index("idx_order_items_variant")
    op.drop_index("idx_order_items_listing")
    op.drop_index("idx_cart_items_variant")
    op.drop_index("idx_cart_items_listing")
    op.drop_index("idx_avail_variant")
