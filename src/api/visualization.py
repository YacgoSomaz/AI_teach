"""
可视化数据 API

路由只负责：参数校验、权限校验、返回 Response。
数据查询与聚合由 VisualizationService 负责。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_ownership, get_current_student_id
from src.db.session import get_db
from src.services.visualization_service import VisualizationService

router = APIRouter(prefix="/api/visualization", tags=["visualization"])


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
    await check_ownership(student_id, current_student_id)
    labels, values = await VisualizationService(db).get_radar_data(student_id)
    return RadarResponse(labels=labels, values=values)


@router.get("/student/{student_id}/heatmap", response_model=HeatmapResponse)
async def get_heatmap(
    student_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> HeatmapResponse:
    """按日期统计复习次数，用于热力图展示。"""
    await check_ownership(student_id, current_student_id)
    dates, counts = await VisualizationService(db).get_heatmap_data(student_id)
    return HeatmapResponse(dates=dates, counts=counts)


@router.get("/student/{student_id}/progress-line", response_model=ProgressLineResponse)
async def get_progress_line(
    student_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> ProgressLineResponse:
    """按日期聚合平均掌握度，用于进度折线图展示。"""
    await check_ownership(student_id, current_student_id)
    dates, scores = await VisualizationService(db).get_progress_line_data(student_id)
    return ProgressLineResponse(dates=dates, mastery_scores=scores)
