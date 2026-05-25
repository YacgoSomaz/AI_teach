"""create AI grading tables

Revision ID: grading_20260525
Revises: 776f9dd8f551
Create Date: 2026-05-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "grading_20260525"
down_revision: Union[str, Sequence[str], None] = "776f9dd8f551"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "grading_taxonomy",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("subject", sa.String(length=64), nullable=False),
        sa.Column("grade", sa.String(length=64), nullable=False),
        sa.Column("chapter", sa.String(length=128), nullable=False),
        sa.Column(
            "parent_id",
            sa.String(length=128),
            sa.ForeignKey("grading_taxonomy.id"),
            nullable=True,
        ),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_grading_taxonomy_subject_grade", "grading_taxonomy", ["subject", "grade"])
    op.create_index("ix_grading_taxonomy_parent", "grading_taxonomy", ["parent_id"])
    op.create_index("ix_grading_taxonomy_active", "grading_taxonomy", ["is_active"])

    op.create_table(
        "assignment_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("student_id", sa.String(length=128), nullable=False),
        sa.Column("detected_subject", sa.String(length=64), nullable=True),
        sa.Column("detected_grade", sa.String(length=64), nullable=True),
        sa.Column("support_status", sa.String(length=32), nullable=True),
        sa.Column("question_struct", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "review_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "quality_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("call1_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_assignment_analyses_assignment_id", "assignment_analyses", ["assignment_id"])
    op.create_index("ix_assignment_analyses_student_id", "assignment_analyses", ["student_id"])

    op.create_table(
        "grading_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("student_id", sa.String(length=128), nullable=False),
        sa.Column("correct_answer", sa.Text(), nullable=False),
        sa.Column("student_answer", sa.Text(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Numeric(4, 3), nullable=True),
        sa.Column("max_score", sa.Numeric(4, 3), nullable=False, server_default="1.0"),
        sa.Column("mistake_type", sa.String(length=64), nullable=True),
        sa.Column("mistake_reason", sa.Text(), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ai_final"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("assignment_id", name="uq_grading_results_assignment"),
    )
    op.create_index("ix_grading_results_student", "grading_results", ["student_id"])
    op.create_index("ix_grading_results_status", "grading_results", ["status"])

    op.create_table(
        "question_knowledge_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_point_id",
            sa.String(length=128),
            sa.ForeignKey("grading_taxonomy.id"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="primary"),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("match_method", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_qkp_assignment", "question_knowledge_points", ["assignment_id"])
    op.create_index("ix_qkp_knowledge_point", "question_knowledge_points", ["knowledge_point_id"])

    op.create_table(
        "student_knowledge_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("student_id", sa.String(length=128), nullable=False),
        sa.Column(
            "assignment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_point_id",
            sa.String(length=128),
            sa.ForeignKey("grading_taxonomy.id"),
            nullable=False,
        ),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Numeric(4, 3), nullable=False),
        sa.Column("max_score", sa.Numeric(4, 3), nullable=False, server_default="1.0"),
        sa.Column("mistake_type", sa.String(length=64), nullable=True),
        sa.Column("grading_status", sa.String(length=32), nullable=False, server_default="ai_final"),
        sa.Column("excluded_from_mastery", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "assignment_id",
            "knowledge_point_id",
            name="uq_student_knowledge_event_assignment_kp",
        ),
    )
    op.create_index("ix_student_knowledge_events_student_id", "student_knowledge_events", ["student_id"])
    op.create_index("ix_ske_student_kp", "student_knowledge_events", ["student_id", "knowledge_point_id"])

    op.create_table(
        "student_knowledge_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.func.gen_random_uuid()),
        sa.Column("student_id", sa.String(length=128), nullable=False),
        sa.Column(
            "knowledge_point_id",
            sa.String(length=128),
            sa.ForeignKey("grading_taxonomy.id"),
            nullable=False,
        ),
        sa.Column("mastery", sa.Numeric(5, 4), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("student_id", "knowledge_point_id", name="uq_student_knowledge_point"),
    )
    op.create_index("ix_skp_student", "student_knowledge_points", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_skp_student", table_name="student_knowledge_points")
    op.drop_table("student_knowledge_points")

    op.drop_index("ix_ske_student_kp", table_name="student_knowledge_events")
    op.drop_index("ix_student_knowledge_events_student_id", table_name="student_knowledge_events")
    op.drop_table("student_knowledge_events")

    op.drop_index("ix_qkp_knowledge_point", table_name="question_knowledge_points")
    op.drop_index("ix_qkp_assignment", table_name="question_knowledge_points")
    op.drop_table("question_knowledge_points")

    op.drop_index("ix_grading_results_status", table_name="grading_results")
    op.drop_index("ix_grading_results_student", table_name="grading_results")
    op.drop_table("grading_results")

    op.drop_index("ix_assignment_analyses_student_id", table_name="assignment_analyses")
    op.drop_index("ix_assignment_analyses_assignment_id", table_name="assignment_analyses")
    op.drop_table("assignment_analyses")

    op.drop_index("ix_grading_taxonomy_active", table_name="grading_taxonomy")
    op.drop_index("ix_grading_taxonomy_parent", table_name="grading_taxonomy")
    op.drop_index("ix_grading_taxonomy_subject_grade", table_name="grading_taxonomy")
    op.drop_table("grading_taxonomy")
