"""
学生画像查询 API

提供学生知识点掌握情况的只读查询接口。
student_id 通过鉴权依赖注入，不接受调用方直接传入（IDOR 防护）。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import Pagination, check_ownership, get_current_student_id
from src.db.session import get_db
from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile

router = APIRouter(prefix="/api/students", tags=["students"])

MASTERY_WEAK_THRESHOLD = 0.6


# ─── Response Models ────────────────────────────────────────────────────────


class KnowledgePointSummary(BaseModel):
    knowledge_point_id: str
    knowledge_point_name: str
    subject: str
    grade: Optional[str]
    mastery_score: float
    review_priority: str
    appear_count: int
    error_count: int
    last_reviewed_at: Optional[datetime]


class StudentProfileResponse(BaseModel):
    student_id: str
    total_knowledge_points: int
    overall_mastery: float
    weak_count: int
    knowledge_points: list[KnowledgePointSummary]


class WeakPointsResponse(BaseModel):
    student_id: str
    total: int
    page: int
    page_size: int
    items: list[KnowledgePointSummary]


class ProgressResponse(BaseModel):
    student_id: str
    total_knowledge_points: int
    overall_mastery: float
    weak_count: int
    medium_count: int
    strong_count: int
    priority_high_count: int
    priority_medium_count: int
    priority_low_count: int


# ─── Helpers ────────────────────────────────────────────────────────────────




def _to_summary(profile: StudentKnowledgeProfile, kp: KnowledgePoint) -> KnowledgePointSummary:
    return KnowledgePointSummary(
        knowledge_point_id=str(kp.id),
        knowledge_point_name=kp.name,
        subject=kp.subject,
        grade=kp.grade,
        mastery_score=profile.mastery_score,
        review_priority=profile.review_priority,
        appear_count=profile.appear_count,
        error_count=profile.error_count,
        last_reviewed_at=profile.last_reviewed_at,
    )


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/{student_id}/profile", response_model=StudentProfileResponse)
async def get_student_profile(
    student_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> StudentProfileResponse:
    """获取学生完整知识点画像。"""
    await check_ownership(student_id, current_student_id)

    stmt = (
        select(StudentKnowledgeProfile, KnowledgePoint)
        .join(KnowledgePoint, StudentKnowledgeProfile.knowledge_point_id == KnowledgePoint.id)
        .where(StudentKnowledgeProfile.student_id == student_id)
    )
    result = await db.execute(stmt)
    rows = result.all()

    if not rows:
        return StudentProfileResponse(
            student_id=student_id,
            total_knowledge_points=0,
            overall_mastery=0.0,
            weak_count=0,
            knowledge_points=[],
        )

    kp_summaries = [_to_summary(p, kp) for p, kp in rows]
    overall_mastery = sum(s.mastery_score for s in kp_summaries) / len(kp_summaries)
    weak_count = sum(1 for s in kp_summaries if s.mastery_score < MASTERY_WEAK_THRESHOLD)

    return StudentProfileResponse(
        student_id=student_id,
        total_knowledge_points=len(kp_summaries),
        overall_mastery=round(overall_mastery, 4),
        weak_count=weak_count,
        knowledge_points=kp_summaries,
    )


@router.get("/{student_id}/weak-points", response_model=WeakPointsResponse)
async def get_weak_points(
    student_id: str,
    current_student_id: str = Depends(get_current_student_id),
    pagination: Pagination = Depends(),
    db: AsyncSession = Depends(get_db),
) -> WeakPointsResponse:
    """获取学生薄弱知识点列表（掌握度 < 0.6），按掌握度升序排列。"""
    await check_ownership(student_id, current_student_id)

    count_stmt = (
        select(func.count())
        .select_from(StudentKnowledgeProfile)
        .where(
            StudentKnowledgeProfile.student_id == student_id,
            StudentKnowledgeProfile.mastery_score < MASTERY_WEAK_THRESHOLD,
        )
    )
    total: int = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        select(StudentKnowledgeProfile, KnowledgePoint)
        .join(KnowledgePoint, StudentKnowledgeProfile.knowledge_point_id == KnowledgePoint.id)
        .where(
            StudentKnowledgeProfile.student_id == student_id,
            StudentKnowledgeProfile.mastery_score < MASTERY_WEAK_THRESHOLD,
        )
        .order_by(StudentKnowledgeProfile.mastery_score.asc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    )
    result = await db.execute(stmt)
    rows = result.all()

    return WeakPointsResponse(
        student_id=student_id,
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        items=[_to_summary(p, kp) for p, kp in rows],
    )


@router.get("/{student_id}/progress", response_model=ProgressResponse)
async def get_student_progress(
    student_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> ProgressResponse:
    """获取学生整体掌握度进度统计。"""
    await check_ownership(student_id, current_student_id)

    stmt = (
        select(StudentKnowledgeProfile)
        .where(StudentKnowledgeProfile.student_id == student_id)
    )
    result = await db.execute(stmt)
    profiles = result.scalars().all()

    if not profiles:
        return ProgressResponse(
            student_id=student_id,
            total_knowledge_points=0,
            overall_mastery=0.0,
            weak_count=0,
            medium_count=0,
            strong_count=0,
            priority_high_count=0,
            priority_medium_count=0,
            priority_low_count=0,
        )

    overall_mastery = sum(p.mastery_score for p in profiles) / len(profiles)

    weak_count = sum(1 for p in profiles if p.mastery_score < 0.4)
    medium_count = sum(1 for p in profiles if 0.4 <= p.mastery_score < 0.7)
    strong_count = sum(1 for p in profiles if p.mastery_score >= 0.7)

    priority_high_count = sum(1 for p in profiles if p.review_priority == "high")
    priority_medium_count = sum(1 for p in profiles if p.review_priority == "medium")
    priority_low_count = sum(1 for p in profiles if p.review_priority == "low")

    return ProgressResponse(
        student_id=student_id,
        total_knowledge_points=len(profiles),
        overall_mastery=round(overall_mastery, 4),
        weak_count=weak_count,
        medium_count=medium_count,
        strong_count=strong_count,
        priority_high_count=priority_high_count,
        priority_medium_count=priority_medium_count,
        priority_low_count=priority_low_count,
    )
