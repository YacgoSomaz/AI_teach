"""
OCR 任务记录模型

每次调用 PaddleOCR API 产生一条 OCRTask 记录。
存储原始 OCR 结果，供后续 AI 分析使用。
"""

from enum import Enum

from sqlalchemy import ForeignKey, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class OCRTaskStatus(str, Enum):
    """OCR 任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class OCRTask(Base):
    """
    OCR 任务记录

    对应技术文档中的 ocr_tasks 表。
    """
    __tablename__ = "ocr_tasks"

    # ── 关联 ──────────────────────────────────────────────
    assignment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignment: Mapped["Assignment"] = relationship(  # noqa: F821
        "Assignment",
        back_populates="ocr_tasks",
    )

    # ── 第三方任务信息 ────────────────────────────────────
    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="paddleocr-vl-1.5",
        comment="OCR 服务提供商",
    )
    external_job_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="PaddleOCR 返回的 jobId",
    )

    # ── 状态 ──────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=OCRTaskStatus.PENDING,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ── OCR 结果 ──────────────────────────────────────────
    raw_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="OCR 提取的纯文本",
    )
    markdown: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="OCR 提取的 Markdown（含图片引用）",
    )
    # images: {image_path: image_url} 映射
    images: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="OCR 提取的图片 URL 映射",
    )
    confidence: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="OCR 置信度 0-1",
    )
    total_pages: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
    )

    # ── 索引 ──────────────────────────────────────────────
    __table_args__ = (
        Index("ix_ocr_tasks_assignment_status", "assignment_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<OCRTask id={self.id} status={self.status} provider={self.provider}>"
