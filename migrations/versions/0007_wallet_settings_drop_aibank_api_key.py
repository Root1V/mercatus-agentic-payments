"""wallet settings: drop aibank_api_key

La API real de AIBank/Aerarium no tiene una clave por cuenta: se autentica la
integración (un token OAuth2 por plataforma), no cada agente -- AE-02 del
canal compartido. La columna solo guardaba claves del mock, sin valor real.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-25 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: str | Sequence[str] | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('wallet_settings', 'aibank_api_key')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('wallet_settings', sa.Column('aibank_api_key', sa.String(length=500), nullable=True))
