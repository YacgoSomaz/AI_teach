"""
学生知识点画像模型

每个学生对每个知识点维护一条掌握度记录。
掌握度 = 正确率 × 时间衰减 × 最近复习表现（第一版用规则，后续可换模型）。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class StudentKnowledgeProfile(Base):
    """
    学生知识点掌握度画像

    对应技术文档中的 student_knowledge_profiles 表。
    这是复习任务生成的核心数据源。
    """
    __tablename__ = "student_knowledge_profiles"

    # ── 关联 ──────────────────────────────────────────────
    student_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="学生 ID",
    )
    knowledge_point_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False,
    )
    knowledge_point: Mapped["KnowledgePoint"] = relationship(  # noqa: F821
        "KnowledgePoint",
        back_populates="student_profiles",
    )

    # ── 出现统计 ──────────────────────────────────────────
    appear_count: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
        comment="该知识点出现次数",
    )
    error_count: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
        comment="做错次数",
    )
    last_error_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次做错时间",
    )
    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次复习时间",
    )

    # ── 掌握度（规则计算，0-1） ───────────────────────────
    mastery_score: Mapped[float] = mapped_column(
        default=0.5,
        nullable=False,
        comment="掌握度分数 0-1，越高越熟练",
    )
    review_priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="medium",
        comment="复习优先级：high/medium/low",
    )
    next_review_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="下次建议复习时间（间隔重复算法）",
    )

    # ── 索引 ──────────────────────────────────────────────
    __table_args__ = (
        # 唯一约束：每个学生对每个知识点只有一条记录
        Index(
            "uq_student_knowledge",
            "student_id",
            "knowledge_point_id",
            unique=True,
        ),
        # 按学生 + 优先级查询（生成今日复习任务）
        Index("ix_profile_student_priority", "student_id", "review_priority"),
        # 按下次复习时间排序
        Index("ix_profile_next_review", "student_id", "next_review_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<StudentKnowledgeProfile "
            f"student={self.student_id} "
            f"kp={self.knowledge_point_id} "
            f"mastery={self.mastery_score:.2f}>"
        )
