"""agents: aibank mandate per playground agent

Desde el contrato 1.1 de Aerarium un permiso del titular es de UN agente:
cada agente del playground guarda el suyo.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-01 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: str | Sequence[str] | None = '0008'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('agents', sa.Column('aibank_mandate_id', sa.String(length=64), nullable=True))
    op.add_column('agents', sa.Column('aibank_mandate_account_id', sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('agents', 'aibank_mandate_account_id')
    op.drop_column('agents', 'aibank_mandate_id')
