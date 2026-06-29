"""Knowledge graph extension models.

Two new tables on top of the existing grading_taxonomy + student_knowledge_points:
- CurriculumKPRelation: directed edges between taxonomy nodes (for graph visualisation)
- StudentReport: cached AI-generated student profile reports
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class CurriculumKPRelation(Base):
    """Directed edge between two GradingTaxonomy nodes.

    relation_type:
      "direct"        – same-chapter prerequisite dependency
      "cross_chapter" – cross-chapter conceptual link
    """

    __tablename__ = "curriculum_kp_relations"

    source_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("grading_taxonomy.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("grading_taxonomy.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="direct",
        comment="direct | cross_chapter",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", name="uq_curriculum_kp_relation"),
        Index("ix_ckpr_source", "source_id"),
        Index("ix_ckpr_target", "target_id"),
    )


class StudentReport(Base):
    """Cached AI-generated student profile report.

    Generated on demand, cached until expires_at or manually invalidated.
    """

    __tablename__ = "student_reports"

    student_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Student identifier",
    )
    subject: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="物理",
        comment="Subject this report covers",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="AI-generated report text (markdown-lite)",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Cache expiry; regenerate after this timestamp",
    )
    meta: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Snapshot stats used during generation (weak_count, total, etc.)",
    )

    __table_args__ = (
        Index("ix_student_reports_student_subject", "student_id", "subject"),
    )
