"""initial_schema

Revision ID: e3a1f2b4c8d0
Revises:
Create Date: 2026-05-19 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e3a1f2b4c8d0'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all base tables."""

    # ── knowledge_points ─────────────────────────────────────────────────────
    op.create_table(
        'knowledge_points',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('name', sa.String(128), nullable=False, comment='知识点名称'),
        sa.Column('subject', sa.String(32), nullable=False, comment='学科'),
        sa.Column('grade', sa.String(32), nullable=True, comment='适用年级'),
        sa.Column('chapter', sa.String(128), nullable=True, comment='章节'),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('knowledge_points.id', ondelete='SET NULL'), nullable=True, comment='父知识点'),
        sa.Column('prerequisites', sa.Text, nullable=True, comment='前置知识'),
        sa.Column('common_errors', sa.Text, nullable=True, comment='常见错因'),
        sa.Column('description', sa.Text, nullable=True, comment='知识点描述'),
        sa.Column('textbook_version', sa.String(64), nullable=True, comment='教材版本'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('true')),
    )
    op.create_index('ix_knowledge_points_subject_grade', 'knowledge_points', ['subject', 'grade'])
    op.create_index('ix_knowledge_points_name', 'knowledge_points', ['name'])

    # ── assignments ──────────────────────────────────────────────────────────
    op.create_table(
        'assignments',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('student_id', sa.String(64), nullable=False, comment='学生 ID'),
        sa.Column('file_id', sa.String(128), nullable=False, unique=True, comment='文件唯一 ID'),
        sa.Column('file_hash', sa.String(64), nullable=False, comment='SHA-256'),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('file_size', sa.BigInteger, nullable=False),
        sa.Column('mime_type', sa.String(64), nullable=False),
        sa.Column('storage_url', sa.Text, nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='uploaded', comment='处理状态'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('retry_count', sa.Integer, nullable=False, server_default='0'),
    )
    op.create_index('ix_assignments_file_hash', 'assignments', ['file_hash'])
    op.create_index('ix_assignments_status', 'assignments', ['status'])
    op.create_index('ix_assignments_student_status', 'assignments', ['student_id', 'status'])

    # ── ocr_tasks ────────────────────────────────────────────────────────────
    op.create_table(
        'ocr_tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('assignment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('assignments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider', sa.String(64), nullable=False, server_default='paddleocr-vl-1.5'),
        sa.Column('external_job_id', sa.String(128), nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('raw_text', sa.Text, nullable=True),
        sa.Column('markdown', sa.Text, nullable=True),
        sa.Column('images', postgresql.JSON, nullable=True),
        sa.Column('confidence', sa.Float, nullable=True),
        sa.Column('total_pages', sa.Integer, nullable=False, server_default='0'),
    )
    op.create_index('ix_ocr_tasks_assignment_id', 'ocr_tasks', ['assignment_id'])
    op.create_index('ix_ocr_tasks_status', 'ocr_tasks', ['status'])
    op.create_index('ix_ocr_tasks_assignment_status', 'ocr_tasks', ['assignment_id', 'status'])

    # ── questions ────────────────────────────────────────────────────────────
    op.create_table(
        'questions',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('assignment_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('assignments.id', ondelete='CASCADE'), nullable=False),
        sa.Column('raw_text', sa.Text, nullable=True),
        sa.Column('markdown', sa.Text, nullable=True),
        sa.Column('image_urls', postgresql.JSON, nullable=True),
        sa.Column('image_semantics', postgresql.JSON, nullable=True),
        sa.Column('subject', sa.String(32), nullable=True),
        sa.Column('grade', sa.String(32), nullable=True),
        sa.Column('question_type', sa.String(32), nullable=True),
        sa.Column('knowledge_points', postgresql.JSON, nullable=True),
        sa.Column('prerequisites', postgresql.JSON, nullable=True),
        sa.Column('difficulty', sa.Integer, nullable=True),
        sa.Column('likely_error_causes', postgresql.JSON, nullable=True),
        sa.Column('review_priority', sa.String(16), nullable=True),
        sa.Column('need_review', sa.Boolean, nullable=True),
        sa.Column('ai_confidence', sa.Float, nullable=True),
        sa.Column('is_confirmed', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('confirmed_knowledge_points', postgresql.JSON, nullable=True),
    )
    op.create_index('ix_questions_assignment', 'questions', ['assignment_id'])
    op.create_index('ix_questions_subject_grade', 'questions', ['subject', 'grade'])
    op.create_index('ix_questions_review_priority', 'questions', ['review_priority'])

    # ── student_knowledge_profiles ───────────────────────────────────────────
    op.create_table(
        'student_knowledge_profiles',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('student_id', sa.String(64), nullable=False),
        sa.Column('knowledge_point_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('knowledge_points.id', ondelete='CASCADE'), nullable=False),
        sa.Column('appear_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('error_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('mastery_score', sa.Float, nullable=False, server_default='0.5'),
        sa.Column('review_priority', sa.String(16), nullable=False, server_default='medium'),
        sa.Column('next_review_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('uq_student_knowledge', 'student_knowledge_profiles', ['student_id', 'knowledge_point_id'], unique=True)
    op.create_index('ix_profile_student_priority', 'student_knowledge_profiles', ['student_id', 'review_priority'])
    op.create_index('ix_profile_next_review', 'student_knowledge_profiles', ['student_id', 'next_review_at'])


def downgrade() -> None:
    """Drop all base tables."""
    op.drop_table('student_knowledge_profiles')
    op.drop_table('questions')
    op.drop_table('ocr_tasks')
    op.drop_table('assignments')
    op.drop_table('knowledge_points')
