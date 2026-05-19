"""
知识点标签模型

统一知识点命名，避免 AI 用多种叫法打散同一知识点。
支持层级结构：学科 → 年级 → 章节 → 知识点。
"""

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class KnowledgePoint(Base):
    """
    知识点标签

    对应技术文档中的 knowledge_points 表。
    """
    __tablename__ = "knowledge_points"

    # ── 基本信息 ──────────────────────────────────────────
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="知识点名称，如「浮力」「阿基米德原理」",
    )
    subject: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="学科，如「物理」「数学」",
    )
    grade: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="适用年级，如「八年级」",
    )
    chapter: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="章节，如「第十章 浮力」",
    )

    # ── 层级关系（父知识点） ──────────────────────────────
    parent_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_points.id", ondelete="SET NULL"),
        nullable=True,
        comment="父知识点 ID，支持层级结构",
    )
    parent: Mapped["KnowledgePoint | None"] = relationship(
        "KnowledgePoint",
        remote_side="KnowledgePoint.id",
        back_populates="children",
    )
    children: Mapped[list["KnowledgePoint"]] = relationship(
        "KnowledgePoint",
        back_populates="parent",
    )

    # ── 教学辅助信息 ──────────────────────────────────────
    prerequisites: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="前置知识（JSON 数组字符串）",
    )
    common_errors: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="常见错因（JSON 数组字符串）",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="知识点描述",
    )

    # ── 版本管理 ──────────────────────────────────────────
    textbook_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="教材版本，如「人教版」「北师大版」",
    )
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
        comment="是否启用",
    )

    # ── 关联 ──────────────────────────────────────────────
    student_profiles: Mapped[list["StudentKnowledgeProfile"]] = relationship(  # noqa: F821
        "StudentKnowledgeProfile",
        back_populates="knowledge_point",
    )

    # ── 索引 ──────────────────────────────────────────────
    __table_args__ = (
        # 按学科 + 年级查询知识点列表
        Index("ix_knowledge_points_subject_grade", "subject", "grade"),
        # 按名称搜索（精确匹配）
        Index("ix_knowledge_points_name", "name"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgePoint {self.subject}/{self.name}>"
