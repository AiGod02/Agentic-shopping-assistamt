"""Add page_views table for analytics tracking.

Revision ID: 002
Revises: 001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'page_views',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('merchant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('merchants.id'), nullable=False, index=True),
        sa.Column('listing_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('listings.id'), nullable=True, index=True),
        sa.Column('visitor_id', sa.String(64), nullable=False, index=True),
        sa.Column('page_type', sa.String(50), nullable=False, server_default='storefront'),
        sa.Column('referrer', sa.String(500), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table('page_views')
