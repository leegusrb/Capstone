"""add document file hash

Revision ID: 2b7c4f8d1a3e
Revises: fa4393fa5a74
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2b7c4f8d1a3e'
down_revision: Union[str, Sequence[str], None] = 'fa4393fa5a74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS file_hash VARCHAR(64)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_file_hash ON documents (file_hash)")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_documents_file_hash'), table_name='documents')
    op.drop_column('documents', 'file_hash')
