"""add document user id

Revision ID: 9a1d3f6b8c2e
Revises: 7d9f3a2c8b1e
Create Date: 2026-06-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a1d3f6b8c2e'
down_revision: Union[str, Sequence[str], None] = '7d9f3a2c8b1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_documents_user_id'), 'documents', ['user_id'], unique=False)
    op.create_foreign_key(
        'fk_documents_user_id_users',
        'documents',
        'users',
        ['user_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_documents_user_id_users', 'documents', type_='foreignkey')
    op.drop_index(op.f('ix_documents_user_id'), table_name='documents')
    op.drop_column('documents', 'user_id')
