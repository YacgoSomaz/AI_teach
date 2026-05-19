"""
可视化数据 API

提供雷达图、热力图、进度折线图所需的聚合数据。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_student_id
from src.db.session import get_db
from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile

router = APIRouter(prefix="/api/visualization", tags=["visualization"])


async def _check_ownership(path_student_id: str, current_student_id: str) -> None:
    if path_student_id != current_student_id:
        raise HTTPException(status_code=404, detail="未找到该学生的数据")


class RadarResponse(BaseModel):
    labels: list[str]
    values: list[float]


class HeatmapResponse(BaseModel):
    dates: list[str]
    counts: list[int]


class ProgressLineResponse(BaseModel):
    dates: list[str]
    mastery_scores: list[float]


@router.get("/student/{student_id}/radar", response_model=RadarResponse)
async def get_radar(
    student_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> RadarResponse:
    """按学科聚合平均掌握度，用于雷达图展示。"""
    await _check_ownership(student_id, current_student_id)
    stmt = (
        select(KnowledgePoint.subject, func.avg(StudentKnowledgeProfile.mastery_score))
        .join(KnowledgePoint, StudentKnowledgeProfile.knowledge_point_id == KnowledgePoint.id)
        .where(StudentKnowledgeProfile.student_id == student_id)
        .group_by(KnowledgePoint.subject)
        .order_by(KnowledgePoint.subject)
    )
    rows = (await db.execute(stmt)).all()
    labels = [r[0] for r in rows]
    values = [round(r[1], 4) for r in rows]
    return RadarResponse(labels=labels, values=values)


@router.get("/student/{student_id}/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    student_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> HeatmapResponse:
    """按日期统计复习次数，用于热力图展示。"""
    await _check_ownership(student_id, current_student_id)
    stmt = (
        select(
            func.date(StudentKnowledgeProfile.last_reviewed_at).label("date"),
            func.count().label("cnt"),
        )
        .where(
            StudentKnowledgeProfile.student_id == student_id,
            StudentKnowledgeProfile.last_reviewed_at.isnot(None),
        )
        .group_by(func.date(StudentKnowledgeProfile.last_reviewed_at))
        .order_by(func.date(StudentKnowledgeProfile.last_reviewed_at))
    )
    rows = (await db.execute(stmt)).all()
    dates = [str(r[0]) for r in rows]
    counts = [int(r[1]) for r in rows]
    return HeatmapResponse(dates=dates, counts=counts)


@router.get("/student/{student_id}/progress-line", response_model=ProgressLineResponse)
async def get_progress_line(
    student_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> ProgressLineResponse:
    """按日期聚合平均掌握度，用于进度折线图展示。"""
    await _check_ownership(student_id, current_student_id)
    stmt = (
        select(
            func.date(StudentKnowledgeProfile.last_reviewed_at).label("date"),
            func.avg(StudentKnowledgeProfile.mastery_score).label("avg_mastery"),
        )
        .where(
            StudentKnowledgeProfile.student_id == student_id,
            StudentKnowledgeProfile.last_reviewed_at.isnot(None),
        )
        .group_by(func.date(StudentKnowledgeProfile.last_reviewed_at))
        .order_by(func.date(StudentKnowledgeProfile.last_reviewed_at))
    )
    rows = (await db.execute(stmt)).all()
    dates = [str(r[0]) for r in rows]
    mastery_scores = [round(r[1], 4) for r in rows]
    return ProgressLineResponse(dates=dates, mastery_scores=mastery_scores)
