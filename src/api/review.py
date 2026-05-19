"""
复习任务查询 API

暴露 ReviewPlanService 生成的今日复习计划，以及历史任务查询。
student_id 通过鉴权依赖注入（IDOR 防护）。
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_student_id
from src.db.session import get_db
from src.services.review_plan_service import DailyReviewPlan, ReviewPlanService, ReviewTaskItem

router = APIRouter(prefix="/api/review", tags=["review"])


# ─── Response Models ────────────────────────────────────────────────────────


class ReviewTaskResponse(BaseModel):
    knowledge_point_id: str
    knowledge_point_name: str
    subject: str
    grade: Optional[str]
    mastery_score: float
    priority: str
    reason: str
    recommended_count: int
    estimated_minutes: int


class TodayReviewPlanResponse(BaseModel):
    student_id: str
    date: str
    total_minutes: int
    task_count: int
    tasks: list[ReviewTaskResponse]


# ─── Converters ─────────────────────────────────────────────────────────────


def _task_to_response(item: ReviewTaskItem) -> ReviewTaskResponse:
    return ReviewTaskResponse(
        knowledge_point_id=item.knowledge_point_id,
        knowledge_point_name=item.knowledge_point_name,
        subject=item.subject,
        grade=item.grade,
        mastery_score=item.mastery_score,
        priority=item.priority,
        reason=item.reason,
        recommended_count=item.recommended_count,
        estimated_minutes=item.estimated_minutes,
    )


def _plan_to_response(plan: DailyReviewPlan) -> TodayReviewPlanResponse:
    return TodayReviewPlanResponse(
        student_id=plan.student_id,
        date=plan.date,
        total_minutes=plan.total_minutes,
        task_count=len(plan.tasks),
        tasks=[_task_to_response(t) for t in plan.tasks],
    )


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/plans/today", response_model=TodayReviewPlanResponse)
async def get_today_review_plan(
    max_tasks: int = Query(default=5, ge=1, le=20, description="最多返回任务数"),
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> TodayReviewPlanResponse:
    """获取当前学生的今日复习计划，按优先级排序。"""
    service = ReviewPlanService(db=db)
    plan = await service.generate_today_plan(
        student_id=current_student_id,
        max_tasks=max_tasks,
    )
    return _plan_to_response(plan)
