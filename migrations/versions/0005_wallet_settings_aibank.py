"""wallet settings aibank

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-30 07:03:51.337825

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: str | Sequence[str] | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('wallet_settings', sa.Column('aibank_account_id', sa.String(length=200), nullable=True))
    op.add_column('wallet_settings', sa.Column('aibank_api_key', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('wallet_settings', 'aibank_api_key')
    op.drop_column('wallet_settings', 'aibank_account_id')
