"""Initial database schema — all core tables for the commerce platform.

Revision ID: 001_initial_schema
Create Date: 2026-02-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Users ─────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50)),
        sa.Column("role", sa.String(50), nullable=False, server_default="customer"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("TRUE")),
        sa.Column("email_verified", sa.Boolean(), server_default=sa.text("FALSE")),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_users_email", "users", ["email"])
    op.create_index("idx_users_role", "users", ["role"])

    # ── Merchants ─────────────────────────────────────────────────
    op.create_table(
        "merchants",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("business_name", sa.String(255), nullable=False),
        sa.Column("business_type", sa.String(100), nullable=False),
        sa.Column("tax_id", sa.String(100)),
        sa.Column("verification_status", sa.String(50), server_default="pending"),
        sa.Column("commission_rate", sa.Numeric(5, 4), server_default="0.0"),
        sa.Column("payout_account", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("settings", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_merchants_user", "merchants", ["user_id"])

    # ── Listings (Polymorphic) ────────────────────────────────────
    op.create_table(
        "listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("status", sa.String(50), server_default="draft"),
        sa.Column("location", postgresql.JSONB()),
        sa.Column("media", postgresql.JSONB(), server_default=sa.text("'[]'")),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'")),
        sa.Column("rating_avg", sa.Numeric(3, 2), server_default="0"),
        sa.Column("rating_count", sa.Integer(), server_default="0"),
        sa.Column("search_vector", postgresql.TSVECTOR()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_listings_merchant", "listings", ["merchant_id"])
    op.create_index("idx_listings_type", "listings", ["type"])
    op.create_index("idx_listings_status", "listings", ["status"])
    op.create_index("idx_listings_price", "listings", ["base_price"])
    op.create_index("idx_listings_search", "listings", ["search_vector"], postgresql_using="gin")
    op.create_index("idx_listings_metadata", "listings", ["metadata"], postgresql_using="gin")
    op.create_index("idx_listings_tags", "listings", ["tags"], postgresql_using="gin")

    # ── Variants ──────────────────────────────────────────────────
    op.create_table(
        "variants",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("listings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku", sa.String(100)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("price_override", sa.Numeric(12, 2)),
        sa.Column("inventory_count", sa.Integer(), server_default="0"),
        sa.Column("attributes", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_variants_listing", "variants", ["listing_id"])
    op.create_index("idx_variants_sku", "variants", ["sku"])

    # ── Availability Blocks ───────────────────────────────────────
    op.create_table(
        "availability_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("listings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("variants.id", ondelete="CASCADE")),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time()),
        sa.Column("end_time", sa.Time()),
        sa.Column("capacity", sa.Integer(), server_default="1"),
        sa.Column("booked_count", sa.Integer(), server_default="0"),
        sa.Column("price_override", sa.Numeric(12, 2)),
        sa.Column("status", sa.String(50), server_default="available"),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("end_date >= start_date", name="chk_dates"),
        sa.CheckConstraint("booked_count <= capacity", name="chk_capacity"),
    )
    op.create_index("idx_avail_listing", "availability_blocks", ["listing_id"])
    op.create_index("idx_avail_dates", "availability_blocks", ["start_date", "end_date"])
    op.create_index("idx_avail_status", "availability_blocks", ["status"])

    # ── Carts ─────────────────────────────────────────────────────
    op.create_table(
        "carts",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(50), server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "idx_carts_active_user", "carts", ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    # ── Cart Items ────────────────────────────────────────────────
    op.create_table(
        "cart_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("cart_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("variants.id")),
        sa.Column("item_type", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("check_in", sa.Date()),
        sa.Column("check_out", sa.Date()),
        sa.Column("time_slot_start", sa.DateTime(timezone=True)),
        sa.Column("time_slot_end", sa.DateTime(timezone=True)),
        sa.Column("guests", sa.Integer()),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_cart_items_cart", "cart_items", ["cart_id"])

    # ── Orders ────────────────────────────────────────────────────
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("order_number", sa.String(50), unique=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("discount_amount", sa.Numeric(12, 2), server_default="0"),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("shipping_address", postgresql.JSONB()),
        sa.Column("billing_address", postgresql.JSONB()),
        sa.Column("notes", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("idempotency_key", sa.String(255), unique=True),
        sa.Column("saga_state", sa.String(50), server_default="initiated"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_orders_user", "orders", ["user_id"])
    op.create_index("idx_orders_status", "orders", ["status"])
    op.create_index("idx_orders_number", "orders", ["order_number"])
    op.create_index("idx_orders_idempotency", "orders", ["idempotency_key"])

    # ── Order Items ───────────────────────────────────────────────
    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("variants.id")),
        sa.Column("item_type", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_order_items_order", "order_items", ["order_id"])

    # ── Bookings ──────────────────────────────────────────────────
    op.create_table(
        "bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("variant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("variants.id")),
        sa.Column("availability_block_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("availability_blocks.id")),
        sa.Column("booking_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("check_in", sa.Date()),
        sa.Column("check_out", sa.Date()),
        sa.Column("time_slot_start", sa.DateTime(timezone=True)),
        sa.Column("time_slot_end", sa.DateTime(timezone=True)),
        sa.Column("guests", sa.Integer(), server_default="1"),
        sa.Column("total_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("special_requests", sa.Text()),
        sa.Column("cancellation_policy", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_bookings_user", "bookings", ["user_id"])
    op.create_index("idx_bookings_listing", "bookings", ["listing_id"])
    op.create_index("idx_bookings_status", "bookings", ["status"])
    op.create_index("idx_bookings_dates", "bookings", ["check_in", "check_out"])

    # ── Payments ──────────────────────────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("gateway", sa.String(50), nullable=False),
        sa.Column("gateway_payment_id", sa.String(255)),
        sa.Column("gateway_order_id", sa.String(255)),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("payment_method_type", sa.String(50)),
        sa.Column("idempotency_key", sa.String(255), unique=True, nullable=False),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_payments_order", "payments", ["order_id"])
    op.create_index("idx_payments_gateway_id", "payments", ["gateway_payment_id"])
    op.create_index("idx_payments_status", "payments", ["status"])
    op.create_index("idx_payments_idempotency", "payments", ["idempotency_key"])

    # ── Refunds ───────────────────────────────────────────────────
    op.create_table(
        "refunds",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("gateway_refund_id", sa.String(255)),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("initiated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_refunds_payment", "refunds", ["payment_id"])

    # ── Escrow Holds ──────────────────────────────────────────────
    op.create_table(
        "escrow_holds",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("status", sa.String(50), server_default="held"),
        sa.Column("release_conditions", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("release_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_escrow_payment", "escrow_holds", ["payment_id"])
    op.create_index("idx_escrow_status", "escrow_holds", ["status"])

    # ── Ledger Entries ────────────────────────────────────────────
    op.create_table(
        "ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payments.id")),
        sa.Column("refund_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("refunds.id")),
        sa.Column("escrow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("escrow_holds.id")),
        sa.Column("entry_type", sa.String(50), nullable=False),
        sa.Column("debit_account", sa.String(100), nullable=False),
        sa.Column("credit_account", sa.String(100), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("description", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_ledger_payment", "ledger_entries", ["payment_id"])
    op.create_index("idx_ledger_type", "ledger_entries", ["entry_type"])
    op.create_index("idx_ledger_created", "ledger_entries", ["created_at"])

    # ── Reviews ───────────────────────────────────────────────────
    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("listing_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id")),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bookings.id")),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("body", sa.Text()),
        sa.Column("media", postgresql.JSONB(), server_default=sa.text("'[]'")),
        sa.Column("is_verified", sa.Boolean(), server_default=sa.text("FALSE")),
        sa.Column("status", sa.String(50), server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="chk_rating"),
    )
    op.create_index("idx_reviews_listing", "reviews", ["listing_id"])
    op.create_index("idx_reviews_user", "reviews", ["user_id"])

    # ── Agent Sessions ────────────────────────────────────────────
    op.create_table(
        "agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("state", sa.String(50), server_default="active"),
        sa.Column("context", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("tool_history", postgresql.JSONB(), server_default=sa.text("'[]'")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_sessions_user", "agent_sessions", ["user_id"])
    op.create_index("idx_sessions_state", "agent_sessions", ["state"])

    # ── Audit Log ─────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("changes", postgresql.JSONB(), server_default=sa.text("'{}'")),
        sa.Column("ip_address", postgresql.INET()),
        sa.Column("user_agent", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_audit_entity", "audit_log", ["entity_type", "entity_id"])
    op.create_index("idx_audit_user", "audit_log", ["user_id"])
    op.create_index("idx_audit_created", "audit_log", ["created_at"])

    # ── Merchant Webhooks ─────────────────────────────────────────
    op.create_table(
        "merchant_webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("merchant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("merchants.id"), nullable=False),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("events", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("secret", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("TRUE")),
        sa.Column("failure_count", sa.Integer(), server_default="0"),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_webhooks_merchant", "merchant_webhooks", ["merchant_id"])

    # ── Triggers: updated_at auto-update ──────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    for table in [
        "users", "merchants", "listings", "variants", "carts", "cart_items",
        "orders", "bookings", "payments", "reviews", "agent_sessions",
    ]:
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at();
        """)

    # ── Trigger: search vector auto-update ────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_listing_search_vector()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector = to_tsvector('english',
                COALESCE(NEW.title, '') || ' ' ||
                COALESCE(NEW.description, '') || ' ' ||
                COALESCE(array_to_string(NEW.tags, ' '), '')
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_listings_search
        BEFORE INSERT OR UPDATE ON listings
        FOR EACH ROW EXECUTE FUNCTION update_listing_search_vector();
    """)


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    for table in [
        "merchant_webhooks", "audit_log", "agent_sessions", "reviews",
        "ledger_entries", "escrow_holds", "refunds", "payments",
        "bookings", "order_items", "orders", "cart_items", "carts",
        "availability_blocks", "variants", "listings", "merchants", "users",
    ]:
        op.drop_table(table)

    op.execute("DROP FUNCTION IF EXISTS update_updated_at() CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS update_listing_search_vector() CASCADE;")
