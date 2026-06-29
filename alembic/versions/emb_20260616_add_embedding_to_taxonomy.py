"""add embedding vector column to grading_taxonomy

Revision ID: emb_20260616
Revises: kg_20260616
Create Date: 2026-06-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "emb_20260616"
down_revision: Union[str, Sequence[str], None] = "kg_20260616"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Add nullable embedding column (filled later via /vectorize endpoint)
    op.execute(
        "ALTER TABLE grading_taxonomy "
        "ADD COLUMN IF NOT EXISTS embedding vector(1024)"
    )

    # HNSW index for fast approximate cosine search
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_taxonomy_embedding_hnsw "
        "ON grading_taxonomy "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_taxonomy_embedding_hnsw")
    op.execute("ALTER TABLE grading_taxonomy DROP COLUMN IF EXISTS embedding")
