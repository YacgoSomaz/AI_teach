"""
题目记录模型

OCR + AI 分析后，每道题目存为一条 Question 记录。
一张作业图片可能切分出多道题目。
"""

from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class Question(Base):
    """
    题目记录

    对应技术文档中的 questions 表。
    这是核心产品闭环的起点：题目 → 知识点 → 学生画像 → 复习任务。
    """
    __tablename__ = "questions"

    # ── 关联 ──────────────────────────────────────────────
    assignment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignment: Mapped["Assignment"] = relationship(  # noqa: F821
        "Assignment",
        back_populates="questions",
    )

    # ── OCR 内容 ──────────────────────────────────────────
    raw_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="题目纯文本（OCR 提取）",
    )
    markdown: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="题目 Markdown（含图片引用）",
    )
    # OCR 提取的图片 URL 列表
    image_urls: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        comment="题目相关图片 URL 列表",
    )
    # 豆包 Seed1.8 对图片的语义描述
    image_semantics: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        comment="题图语义描述（DoubaoSeed 分析结果）",
    )

    # ── AI 分析结果 ───────────────────────────────────────
    subject: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="学科",
    )
    grade: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="年级",
    )
    question_type: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="题型",
    )
    # 知识点列表（JSON 数组）
    knowledge_points: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        comment="AI 识别的知识点列表",
    )
    # 前置知识列表
    prerequisites: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )
    difficulty: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="难度 1-5",
    )
    # 可能错因列表
    likely_error_causes: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
    )
    review_priority: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="复习优先级：high/medium/low",
    )
    need_review: Mapped[bool | None] = mapped_column(
        nullable=True,
        comment="是否需要进入复习库",
    )
    ai_confidence: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="AI 分析置信度 0-1",
    )

    # ── 人工校正 ──────────────────────────────────────────
    is_confirmed: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="用户是否已确认 AI 分析结果",
    )
    confirmed_knowledge_points: Mapped[list | None] = mapped_column(
        JSON,
        nullable=True,
        comment="用户确认/修正后的知识点列表",
    )

    # ── 索引 ──────────────────────────────────────────────
    __table_args__ = (
        Index("ix_questions_assignment", "assignment_id"),
        Index("ix_questions_subject_grade", "subject", "grade"),
        Index("ix_questions_review_priority", "review_priority"),
    )

    def __repr__(self) -> str:
        return f"<Question id={self.id} subject={self.subject} priority={self.review_priority}>"
