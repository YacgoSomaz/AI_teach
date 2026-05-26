"""add_steps_review_suggestions_error_type_grade_to_grading_models

Revision ID: c063c0c8419f
Revises: grading_20260525
Create Date: 2026-05-26 17:06:18.386025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c063c0c8419f'
down_revision: Union[str, Sequence[str], None] = 'grading_20260525'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add grade field to assignment_analyses table
    op.add_column('assignment_analyses', sa.Column('grade', sa.String(length=64), nullable=True))
    
    # Add new fields to grading_results table
    op.add_column('grading_results', sa.Column('steps', sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'))
    op.add_column('grading_results', sa.Column('review_suggestions', sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'))
    op.add_column('grading_results', sa.Column('error_type', sa.String(length=64), nullable=True))
    op.add_column('grading_results', sa.Column('grade', sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove new fields from grading_results table
    op.drop_column('grading_results', 'grade')
    op.drop_column('grading_results', 'error_type')
    op.drop_column('grading_results', 'review_suggestions')
    op.drop_column('grading_results', 'steps')
    
    # Remove grade field from assignment_analyses table
    op.drop_column('assignment_analyses', 'grade')
