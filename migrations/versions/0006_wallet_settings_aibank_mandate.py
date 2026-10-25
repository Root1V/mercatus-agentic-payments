"""wallet settings aibank mandate (modelo B)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: str | Sequence[str] | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('wallet_settings', sa.Column('aibank_model', sa.String(length=16), nullable=True))
    op.add_column('wallet_settings', sa.Column('aibank_mandate_id', sa.String(length=64), nullable=True))
    op.add_column('wallet_settings', sa.Column('aibank_mandate_account_id', sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('wallet_settings', 'aibank_mandate_account_id')
    op.drop_column('wallet_settings', 'aibank_mandate_id')
    op.drop_column('wallet_settings', 'aibank_model')
