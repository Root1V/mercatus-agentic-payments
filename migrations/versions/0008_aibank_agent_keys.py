"""aibank agent keys

Los agentes de Mercatus ante AIBank/Aerarium y su clave de firma Ed25519,
cifrada (contrato 1.1, M-15 del canal compartido).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31 23:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: str | Sequence[str] | None = '0007'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'aibank_agent_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=300), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False),
        sa.Column('agent_id', sa.String(length=64), nullable=False),
        sa.Column('agent_name', sa.String(length=200), nullable=False),
        sa.Column('key_id', sa.String(length=64), nullable=False),
        sa.Column('encrypted_private_key', sa.Text(), nullable=False),
        sa.Column('account_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scope', 'label', name='uq_aibank_agent_keys_scope_label'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('aibank_agent_keys')
