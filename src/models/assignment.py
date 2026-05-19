"""
作业上传记录模型

学生每次拍照上传产生一条 Assignment 记录。
一张图片可能包含多道题目（多题同页）。

状态机：
  uploaded → ocr_queued → ocr_running → ocr_done
                                       → ai_queued → ai_running → ai_done
  任意阶段 → failed / manual_required
"""

import uuid
from enum import Enum

from sqlalchemy import BigInteger, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class AssignmentStatus(str, Enum):
    """作业处理状态机"""
    UPLOADED = "uploaded"           # 图片已上传，等待处理
    OCR_QUEUED = "ocr_queued"       # 已进入 OCR 队列
    OCR_RUNNING = "ocr_running"     # OCR 处理中
    OCR_DONE = "ocr_done"           # OCR 完成，等待 AI 分析
    OCR_FAILED = "ocr_failed"       # OCR 失败（但不影响其他环节）
    AI_QUEUED = "ai_queued"         # 已进入 AI 分析队列
    AI_RUNNING = "ai_running"       # AI 分析中
    AI_DONE = "ai_done"             # 全流程完成
    AI_FAILED = "ai_failed"         # AI 失败（但 OCR 结果可用）
    FAILED = "failed"               # 处理失败（可重试）
    MANUAL_REQUIRED = "manual_required"  # 需要人工介入


class Assignment(Base):
    """
    作业上传记录

    对应技术文档中的 assignments 表。
    """
    __tablename__ = "assignments"

    # ── 关联 ──────────────────────────────────────────────
    # 暂时用字符串存 student_id，后续接入用户系统后改为 FK
    student_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="学生 ID（预留，后续改为 FK）",
    )

    # ── 文件信息 ──────────────────────────────────────────
    file_id: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        comment="文件唯一 ID（UUID）",
    )
    file_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="文件内容 SHA-256，用于去重",
    )
    original_filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="原始文件名",
    )
    file_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="文件大小（字节）",
    )
    mime_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="MIME 类型，如 image/jpeg",
    )
    storage_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="对象存储 URL（私有桶，访问需生成临时 URL）",
    )

    # ── 处理状态 ──────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AssignmentStatus.UPLOADED,
        index=True,
        comment="处理状态",
    )
    
    # 错误隔离：记录各环节的独立状态
    processing_status: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="各环节处理状态（JSON），如 {'ocr': {'status': 'done', 'confidence': 0.95}, 'ai': {'status': 'failed', 'error': '...'}}",
    )
    
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="失败原因",
    )
    retry_count: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
        comment="重试次数",
    )

    # ── 关联子记录 ────────────────────────────────────────
    ocr_tasks: Mapped[list["OCRTask"]] = relationship(  # noqa: F821
        "OCRTask",
        back_populates="assignment",
        cascade="all, delete-orphan",
    )
    questions: Mapped[list["Question"]] = relationship(  # noqa: F821
        "Question",
        back_populates="assignment",
        cascade="all, delete-orphan",
    )

    # ── 索引 ──────────────────────────────────────────────
    __table_args__ = (
        # 按学生 + 状态查询（学生查看自己的任务列表）
        Index("ix_assignments_student_status", "student_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Assignment id={self.id} student={self.student_id} status={self.status}>"
