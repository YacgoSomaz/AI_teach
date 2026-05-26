"""AI grading API endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_student_id
from src.db.session import get_db
from src.models.assignment import Assignment, AssignmentStatus
from src.models.grading import (
    AssignmentAnalysis,
    GradingResult,
    QuestionKnowledgePoint,
    StudentKnowledgeEvent,
)
from src.services.ai_grading_service import rebuild_student_knowledge_point
from src.tasks.grading_tasks import process_ai_grading


router = APIRouter(prefix="/api/grading", tags=["ai-grading"])


class StartGradingResponse(BaseModel):
    success: bool
    assignment_id: str
    status: str
    message: str


class GradingStatusResponse(BaseModel):
    assignment_id: str
    status: str | None
    support_status: str | None = None
    review_required: bool | None = None
    review_reasons: list[str] = []
    analysis: dict | None = None
    grading: dict | None = None
    knowledge_points: list[dict] = []


class DisputeResponse(BaseModel):
    success: bool
    assignment_id: str
    status: str


@router.post("/{assignment_id}/start", response_model=StartGradingResponse)
async def start_ai_grading(
    assignment_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> StartGradingResponse:
    assignment = await get_owned_assignment(db, assignment_id, current_student_id)
    if assignment.status in (AssignmentStatus.AI_RUNNING, AssignmentStatus.AI_DONE):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="批改任务已存在，请勿重复提交",
        )

    process_ai_grading.delay(str(assignment.id))
    return StartGradingResponse(
        success=True,
        assignment_id=str(assignment.id),
        status="queued",
        message="AI 批改已进入队列",
    )


@router.get("/{assignment_id}", response_model=GradingStatusResponse)
async def get_ai_grading_result(
    assignment_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> GradingStatusResponse:
    assignment = await get_owned_assignment(db, assignment_id, current_student_id)

    analysis_result = await db.execute(
        select(AssignmentAnalysis).where(AssignmentAnalysis.assignment_id == assignment.id)
    )
    analysis = analysis_result.scalar_one_or_none()

    grading_result = await db.execute(
        select(GradingResult).where(GradingResult.assignment_id == assignment.id)
    )
    grading = grading_result.scalar_one_or_none()

    qkp_result = await db.execute(
        select(QuestionKnowledgePoint).where(
            QuestionKnowledgePoint.assignment_id == assignment.id
        )
    )
    qkps = qkp_result.scalars().all()

    return GradingStatusResponse(
        assignment_id=str(assignment.id),
        status=assignment.status,
        support_status=analysis.support_status if analysis else None,
        review_required=analysis.review_required if analysis else None,
        review_reasons=analysis.review_reasons if analysis else [],
        analysis=serialize_analysis(analysis) if analysis else None,
        grading=serialize_grading_result(grading) if grading else None,
        knowledge_points=[
            {
                "knowledge_point_id": qkp.knowledge_point_id,
                "role": qkp.role,
                "confidence": float(qkp.confidence),
                "match_method": qkp.match_method,
            }
            for qkp in qkps
        ],
    )


@router.post("/{assignment_id}/dispute", response_model=DisputeResponse)
async def dispute_ai_grading(
    assignment_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> DisputeResponse:
    assignment = await get_owned_assignment(db, assignment_id, current_student_id)

    grading_result = await db.execute(
        select(GradingResult).where(GradingResult.assignment_id == assignment.id)
    )
    grading = grading_result.scalar_one_or_none()
    if grading is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="批改结果不存在",
        )
    if grading.status != "ai_final":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"当前状态 '{grading.status}' 不允许申请复议",
        )

    grading.status = "disputed"
    event_result = await db.execute(
        select(StudentKnowledgeEvent).where(
            StudentKnowledgeEvent.assignment_id == assignment.id
        )
    )
    events = event_result.scalars().all()
    changed_knowledge_point_ids = set()
    for event in events:
        event.grading_status = "disputed"
        changed_knowledge_point_ids.add(event.knowledge_point_id)

    await db.flush()
    for knowledge_point_id in changed_knowledge_point_ids:
        await rebuild_student_knowledge_point(
            db,
            student_id=current_student_id,
            knowledge_point_id=knowledge_point_id,
        )
    await db.commit()

    return DisputeResponse(
        success=True,
        assignment_id=str(assignment.id),
        status="disputed",
    )


async def get_owned_assignment(
    db: AsyncSession,
    assignment_id: str,
    student_id: str,
) -> Assignment:
    try:
        assignment_uuid = UUID(assignment_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的 assignment_id 格式",
        )

    result = await db.execute(select(Assignment).where(Assignment.id == assignment_uuid))
    assignment = result.scalar_one_or_none()
    if assignment is None or assignment.student_id != student_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="作业记录不存在",
        )
    return assignment


def serialize_analysis(analysis: AssignmentAnalysis) -> dict:
    return {
        "detected_subject": analysis.detected_subject,
        "detected_grade": analysis.grade,
        "support_status": analysis.support_status,
        "review_required": analysis.review_required,
        "review_reasons": analysis.review_reasons or [],
    }


def serialize_grading_result(grading: GradingResult) -> dict:
    return {
        "student_answer": grading.student_answer,
        "correct_answer": grading.correct_answer,
        "is_correct": grading.is_correct,
        "score": float(grading.score) if grading.score is not None else None,
        "max_score": float(grading.max_score),
        "mistake_type": grading.mistake_type,
        "mistake_reason": grading.mistake_reason,
        "feedback": grading.feedback,
        "status": grading.status,
        "steps": grading.steps or [],
        "review_suggestions": grading.review_suggestions or [],
        "error_type": grading.error_type,
        "grade": grading.grade,
    }
