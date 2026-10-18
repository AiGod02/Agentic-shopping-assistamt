"""Add saga_instances and outbox_events tables.

Revision ID: 005
Revises: 004
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # saga_instances
    op.create_table(
        'saga_instances',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('idempotency_key', sa.String(255), unique=True, nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='started'),
        sa.Column('context_data', postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_saga_idempotency", "saga_instances", ["idempotency_key"])
    op.create_index("idx_saga_status", "saga_instances", ["status"])

    # outbox_events
    op.create_table(
        'outbox_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column('topic', sa.String(100), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('source', sa.String(100), nullable=False),
        sa.Column('key', sa.String(255), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_outbox_status", "outbox_events", ["status"])
    op.create_index("idx_outbox_created", "outbox_events", ["created_at"])


def downgrade() -> None:
    op.drop_table('outbox_events')
    op.drop_table('saga_instances')
