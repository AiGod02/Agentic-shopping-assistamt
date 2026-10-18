"""Add payment_id to subscriptions.

Revision ID: 007
Revises: 006
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('subscriptions', sa.Column('payment_id', sa.String(255), nullable=True))
    op.create_index("idx_subscriptions_payment", "subscriptions", ["payment_id"])


def downgrade() -> None:
    op.drop_index("idx_subscriptions_payment")
    op.drop_column('subscriptions', 'payment_id')
