"""
学习报告 API

路径：GET /api/reports/student/{student_id}
student_id 路径参数与鉴权 Header 做所有权校验（IDOR 防护）。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_ownership, get_current_student_id
from src.db.session import get_db
from src.services.report_service import (
    KnowledgePointDetail,
    LearningReport,
    ReportService,
    SubjectSummary,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


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


def _to_response(report: LearningReport) -> LearningReportResponse:
    return LearningReportResponse(
        student_id=report.student_id,
        generated_at=report.generated_at,
        total_knowledge_points=report.total_knowledge_points,
        overall_mastery=report.overall_mastery,
        weak_count=report.weak_count,
        medium_count=report.medium_count,
        strong_count=report.strong_count,
        subjects=[
            SubjectSummaryResponse(**s.__dict__) for s in report.subjects
        ],
        top_weak_points=[
            KnowledgePointDetailResponse(**d.__dict__) for d in report.top_weak_points
        ],
        top_strong_points=[
            KnowledgePointDetailResponse(**d.__dict__) for d in report.top_strong_points
        ],
    )


class ParentWeakPointItem(BaseModel):
    knowledge_point_name: str
    subject: str
    grade: Optional[str]
    mastery_score: float
    mastery_level: str
    review_priority: str


class ParentSubjectItem(BaseModel):
    subject: str
    total: int
    average_mastery: float


class ParentReportResponse(BaseModel):
    student_id: str
    generated_at: str
    total_knowledge_points: int
    overall_mastery: float
    weak_count: int
    subjects: list[ParentSubjectItem]
    top_weak_points: list[ParentWeakPointItem]


@router.get("/student/{student_id}", response_model=LearningReportResponse)
async def get_student_report(
    student_id: str,
    top_n: int = Query(default=5, ge=1, le=20),
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> LearningReportResponse:
    """获取学生学习报告，含各学科汇总与薄弱/优秀知识点。"""
    await check_ownership(student_id, current_student_id)
    service = ReportService(db=db)
    report = await service.generate_report(student_id=student_id, top_n=top_n)
    return _to_response(report)


@router.get("/parent/{student_id}", response_model=ParentReportResponse)
async def get_parent_report(
    student_id: str,
    top_n: int = Query(default=3, ge=1, le=10),
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> ParentReportResponse:
    """获取家长视角学习报告，只展示关键信息，不暴露内部分级细节。"""
    await check_ownership(student_id, current_student_id)
    service = ReportService(db=db)
    report = await service.generate_report(student_id=student_id, top_n=top_n)
    return ParentReportResponse(
        student_id=report.student_id,
        generated_at=report.generated_at,
        total_knowledge_points=report.total_knowledge_points,
        overall_mastery=report.overall_mastery,
        weak_count=report.weak_count,
        subjects=[
            ParentSubjectItem(
                subject=s.subject,
                total=s.total,
                average_mastery=s.average_mastery,
            )
            for s in report.subjects
        ],
        top_weak_points=[
            ParentWeakPointItem(
                knowledge_point_name=d.knowledge_point_name,
                subject=d.subject,
                grade=d.grade,
                mastery_score=d.mastery_score,
                mastery_level=d.mastery_level,
                review_priority=d.review_priority,
            )
            for d in report.top_weak_points
        ],
    )
