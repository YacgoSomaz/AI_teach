"""
学习报告 API

提供学生学习报告的查询接口。
student_id 通过鉴权依赖注入（IDOR 防护）。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_student_id
from src.db.session import get_db
from src.services.report_service import (
    KnowledgePointDetail,
    LearningReport,
    ReportService,
    SubjectSummary,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


# ─── Response Models ────────────────────────────────────────────────────────


class SubjectSummaryResponse(BaseModel):
    subject: str
    total: int
    weak_count: int
    medium_count: int
    strong_count: int
    average_mastery: float
    average_error_rate: float


class KnowledgePointDetailResponse(BaseModel):
    knowledge_point_id: str
    knowledge_point_name: str
    subject: str
    grade: Optional[str]
    mastery_score: float
    mastery_level: str
    appear_count: int
    error_count: int
    error_rate: float
    review_priority: str
    last_reviewed_at: Optional[datetime]


class LearningReportResponse(BaseModel):
    student_id: str
    generated_at: str
    total_knowledge_points: int
    overall_mastery: float
    weak_count: int
    medium_count: int
    strong_count: int
    subjects: list[SubjectSummaryResponse]
    top_weak_points: list[KnowledgePointDetailResponse]
    top_strong_points: list[KnowledgePointDetailResponse]


# ─── Converters ─────────────────────────────────────────────────────────────


def _subject_to_response(s: SubjectSummary) -> SubjectSummaryResponse:
    return SubjectSummaryResponse(
        subject=s.subject,
        total=s.total,
        weak_count=s.weak_count,
        medium_count=s.medium_count,
        strong_count=s.strong_count,
        average_mastery=s.average_mastery,
        average_error_rate=s.average_error_rate,
    )


def _detail_to_response(d: KnowledgePointDetail) -> KnowledgePointDetailResponse:
    return KnowledgePointDetailResponse(
        knowledge_point_id=d.knowledge_point_id,
        knowledge_point_name=d.knowledge_point_name,
        subject=d.subject,
        grade=d.grade,
        mastery_score=d.mastery_score,
        mastery_level=d.mastery_level,
        appear_count=d.appear_count,
        error_count=d.error_count,
        error_rate=d.error_rate,
        review_priority=d.review_priority,
        last_reviewed_at=d.last_reviewed_at,
    )


def _report_to_response(report: LearningReport) -> LearningReportResponse:
    return LearningReportResponse(
        student_id=report.student_id,
        generated_at=report.generated_at,
        total_knowledge_points=report.total_knowledge_points,
        overall_mastery=report.overall_mastery,
        weak_count=report.weak_count,
        medium_count=report.medium_count,
        strong_count=report.strong_count,
        subjects=[_subject_to_response(s) for s in report.subjects],
        top_weak_points=[_detail_to_response(d) for d in report.top_weak_points],
        top_strong_points=[_detail_to_response(d) for d in report.top_strong_points],
    )


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/learning", response_model=LearningReportResponse)
async def get_learning_report(
    top_n: int = Query(default=5, ge=1, le=20, description="薄弱/优秀知识点各展示前 N 条"),
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> LearningReportResponse:
    """获取当前学生的学习报告，包含各学科汇总和薄弱/优秀知识点。"""
    service = ReportService(db=db)
    report = await service.generate_report(
        student_id=current_student_id,
        top_n=top_n,
    )
    return _report_to_response(report)
