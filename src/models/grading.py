"""AI grading pipeline database models.

These tables are owned by Codex and intentionally live beside, not inside,
Kiro's existing knowledge point/profile models.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class GradingTaxonomy(Base):
    """AI grading taxonomy with stable string IDs."""

    __tablename__ = "grading_taxonomy"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    subject: Mapped[str] = mapped_column(String(64), nullable=False)
    grade: Mapped[str] = mapped_column(String(64), nullable=False)
    chapter: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("grading_taxonomy.id"),
        nullable=True,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_grading_taxonomy_subject_grade", "subject", "grade"),
        Index("ix_grading_taxonomy_parent", "parent_id"),
        Index("ix_grading_taxonomy_active", "is_active"),
    )


class AssignmentAnalysis(Base):
    """Stored Call 1 output and quality gates for an assignment."""

    __tablename__ = "assignment_analyses"

    assignment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    detected_subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_grade: Mapped[str | None] = mapped_column(String(64), nullable=True)
    support_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    question_struct: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    quality_flags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    call1_raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class GradingResult(Base):
    """AI grading result and dispute status for one assignment."""

    __tablename__ = "grading_results"

    assignment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)
    student_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    max_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=1.0)
    mistake_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mistake_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ai_final")

    __table_args__ = (
        UniqueConstraint("assignment_id", name="uq_grading_results_assignment"),
        Index("ix_grading_results_student", "student_id"),
        Index("ix_grading_results_status", "status"),
    )


class QuestionKnowledgePoint(Base):
    """Mapping between an assignment's question and grading taxonomy entries."""

    __tablename__ = "question_knowledge_points"

    assignment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_point_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("grading_taxonomy.id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="primary")
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    match_method: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        Index("ix_qkp_assignment", "assignment_id"),
        Index("ix_qkp_knowledge_point", "knowledge_point_id"),
    )


class StudentKnowledgeEvent(Base):
    """Immutable-ish fact source for student mastery aggregation."""

    __tablename__ = "student_knowledge_events"

    student_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    assignment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_point_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("grading_taxonomy.id"),
        nullable=False,
    )
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=1.0)
    mistake_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    grading_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ai_final",
    )
    excluded_from_mastery: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "assignment_id",
            "knowledge_point_id",
            name="uq_student_knowledge_event_assignment_kp",
        ),
        Index("ix_ske_student_kp", "student_id", "knowledge_point_id"),
    )


class StudentKnowledgePoint(Base):
    """Derived mastery aggregate for the AI grading taxonomy."""

    __tablename__ = "student_knowledge_points"

    student_id: Mapped[str] = mapped_column(String(128), nullable=False)
    knowledge_point_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("grading_taxonomy.id"),
        nullable=False,
    )
    mastery: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "student_id",
            "knowledge_point_id",
            name="uq_student_knowledge_point",
        ),
        Index("ix_skp_student", "student_id"),
    )
