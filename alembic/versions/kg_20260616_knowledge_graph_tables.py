"""add knowledge graph tables: curriculum_kp_relations, student_reports

Revision ID: kg_20260616
Revises: c063c0c8419f
Create Date: 2026-06-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "kg_20260616"
down_revision: Union[str, Sequence[str], None] = "c063c0c8419f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "curriculum_kp_relations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.func.gen_random_uuid(),
        ),
        sa.Column(
            "source_id",
            sa.String(128),
            sa.ForeignKey("grading_taxonomy.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.String(128),
            sa.ForeignKey("grading_taxonomy.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(32), nullable=False, server_default="direct"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_id", "target_id", name="uq_curriculum_kp_relation"),
    )
    op.create_index("ix_ckpr_source", "curriculum_kp_relations", ["source_id"])
    op.create_index("ix_ckpr_target", "curriculum_kp_relations", ["target_id"])

    op.create_table(
        "student_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.func.gen_random_uuid(),
        ),
        sa.Column("student_id", sa.String(128), nullable=False),
        sa.Column("subject", sa.String(64), nullable=False, server_default="物理"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_student_reports_student_subject", "student_reports", ["student_id", "subject"])


def downgrade() -> None:
    op.drop_index("ix_student_reports_student_subject", table_name="student_reports")
    op.drop_table("student_reports")

    op.drop_index("ix_ckpr_target", table_name="curriculum_kp_relations")
    op.drop_index("ix_ckpr_source", table_name="curriculum_kp_relations")
    op.drop_table("curriculum_kp_relations")
