"""add session kg snapshots

Revision ID: 7d9f3a2c8b1e
Revises: 2b7c4f8d1a3e
Create Date: 2026-06-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d9f3a2c8b1e'
down_revision: Union[str, Sequence[str], None] = '2b7c4f8d1a3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('session_records', sa.Column('scores', sa.JSON(), nullable=True))
    op.add_column('session_records', sa.Column('user_kg_before', sa.JSON(), nullable=True))
    op.add_column('session_records', sa.Column('user_kg_after', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('session_records', 'user_kg_after')
    op.drop_column('session_records', 'user_kg_before')
    op.drop_column('session_records', 'scores')
