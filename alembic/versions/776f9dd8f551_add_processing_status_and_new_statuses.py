"""add_processing_status_and_new_statuses

Revision ID: 776f9dd8f551
Revises: 
Create Date: 2026-05-19 11:13:55.246540

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '776f9dd8f551'
down_revision: Union[str, Sequence[str], None] = 'e3a1f2b4c8d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add processing_status column to assignments table
    op.add_column(
        'assignments',
        sa.Column('processing_status', sa.JSON(), nullable=True, comment='各环节处理状态（JSON）')
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove processing_status column
    op.drop_column('assignments', 'processing_status')
