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
    GradingTaxonomy,
    GradingResult,
    QuestionKnowledgePoint,
    StudentKnowledgeEvent,
    StudentKnowledgePoint,
)
from src.services.ai_grading_service import rebuild_student_knowledge_point
from src.tasks.grading_tasks import process_ai_grading


router = APIRouter(prefix="/api/grading", tags=["ai-grading"])


MISTAKE_TYPE_LABELS = {
    "correct": "已掌握",
    "concept_error": "概念理解偏差",
    "calculation_error": "计算过程错误",
    "graph_reading_error": "图像信息读取错误",
    "experiment_design_error": "实验设计理解偏差",
    "formula_error": "公式使用错误",
    "no_answer": "未作答",
    "partial": "部分掌握",
}


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
    knowledge_review: dict = {}


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
    analysis_result = await db.execute(
        select(AssignmentAnalysis).where(AssignmentAnalysis.assignment_id == assignment.id)
    )
    analysis = analysis_result.scalar_one_or_none()
    grading_result = await db.execute(
        select(GradingResult).where(GradingResult.assignment_id == assignment.id)
    )
    grading = grading_result.scalar_one_or_none()

    grading_status = ((assignment.processing_status or {}).get("grading") or {}).get("status")
    has_complete_grading = analysis is not None and grading is not None
    if grading_status in ("running", "retrying") or has_complete_grading:
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
    knowledge_point_ids = [qkp.knowledge_point_id for qkp in qkps]
    taxonomy_by_id: dict[str, GradingTaxonomy] = {}
    mastery_by_id: dict[str, StudentKnowledgePoint] = {}
    if knowledge_point_ids:
        taxonomy_result = await db.execute(
            select(GradingTaxonomy).where(GradingTaxonomy.id.in_(knowledge_point_ids))
        )
        taxonomy_by_id = {kp.id: kp for kp in taxonomy_result.scalars().all()}

        mastery_result = await db.execute(
            select(StudentKnowledgePoint).where(
                StudentKnowledgePoint.student_id == current_student_id,
                StudentKnowledgePoint.knowledge_point_id.in_(knowledge_point_ids),
            )
        )
        mastery_by_id = {
            point.knowledge_point_id: point for point in mastery_result.scalars().all()
        }

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
                "taxonomy_name": taxonomy_by_id.get(qkp.knowledge_point_id).name
                if taxonomy_by_id.get(qkp.knowledge_point_id)
                else qkp.knowledge_point_id,
                "chapter": taxonomy_by_id.get(qkp.knowledge_point_id).chapter
                if taxonomy_by_id.get(qkp.knowledge_point_id)
                else None,
                "role": qkp.role,
                "confidence": float(qkp.confidence),
                "match_method": qkp.match_method,
                "mastery": float(mastery_by_id[qkp.knowledge_point_id].mastery)
                if qkp.knowledge_point_id in mastery_by_id
                and mastery_by_id[qkp.knowledge_point_id].mastery is not None
                else None,
                "attempts": mastery_by_id[qkp.knowledge_point_id].attempts
                if qkp.knowledge_point_id in mastery_by_id
                else 0,
            }
            for qkp in qkps
        ],
        knowledge_review=build_knowledge_review(
            qkps=qkps,
            taxonomy_by_id=taxonomy_by_id,
            mastery_by_id=mastery_by_id,
            grading=grading,
            analysis=analysis,
        ),
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
    # Pull richer data from the raw AI response stored at grading time
    raw: dict = analysis.call1_raw or {}
    solution_raw: dict = raw.get("solution", {})
    grading_raw: dict = raw.get("grading", {})
    return {
        "detected_subject": analysis.detected_subject,
        "detected_grade": analysis.grade,
        "support_status": analysis.support_status,
        "review_required": analysis.review_required,
        "review_reasons": analysis.review_reasons or [],
        # Solution data (full steps, answer, summary) — used as fallback on frontend
        "solution_steps": solution_raw.get("solution_steps") or [],
        "solution_answer": solution_raw.get("answer"),
        "reasoning_summary": solution_raw.get("reasoning_summary"),
        "question_struct": raw.get("question_struct") or {},
        # Raw grading fields — fallback when GradingResult DB columns are empty
        "raw_correct_answer": grading_raw.get("correct_answer"),
        "raw_feedback": grading_raw.get("feedback"),
        "raw_mistake_reason": grading_raw.get("mistake_reason"),
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


def build_knowledge_review(
    *,
    qkps: list[QuestionKnowledgePoint],
    taxonomy_by_id: dict[str, GradingTaxonomy],
    mastery_by_id: dict[str, StudentKnowledgePoint],
    grading: GradingResult | None,
    analysis: AssignmentAnalysis | None = None,
) -> dict:
    """Build a small, frontend-friendly study review block from persisted data."""
    knowledge_points = []
    for qkp in qkps:
        taxonomy = taxonomy_by_id.get(qkp.knowledge_point_id)
        mastery = mastery_by_id.get(qkp.knowledge_point_id)
        knowledge_points.append(
            {
                "id": qkp.knowledge_point_id,
                "name": taxonomy.name if taxonomy else qkp.knowledge_point_id,
                "chapter": taxonomy.chapter if taxonomy else None,
                "role": qkp.role,
                "confidence": float(qkp.confidence),
                "source": "taxonomy",
                "mastery": float(mastery.mastery)
                if mastery and mastery.mastery is not None
                else None,
                "attempts": mastery.attempts if mastery else 0,
            }
        )
    if not knowledge_points:
        knowledge_points = fallback_knowledge_points_from_analysis(analysis)

    weak_points = choose_weak_points(knowledge_points, grading)
    mistake_type = grading.mistake_type if grading else None
    mistake_label = MISTAKE_TYPE_LABELS.get(mistake_type or "", "") if mistake_type else ""
    recommended_actions = build_recommended_actions(
        knowledge_points=knowledge_points,
        weak_points=weak_points,
        grading=grading,
    )

    return {
        "knowledge_points": [point["name"] for point in knowledge_points],
        "knowledge_point_details": knowledge_points,
        "weak_points": [point["name"] for point in weak_points],
        "mistake_type": mistake_type,
        "mistake_type_label": mistake_label,
        "mistake_reason": grading.mistake_reason if grading else None,
        "recommended_actions": recommended_actions,
    }


def fallback_knowledge_points_from_analysis(
    analysis: AssignmentAnalysis | None,
) -> list[dict]:
    if analysis is None:
        return []

    raw: dict = analysis.call1_raw or {}
    candidates = [
        {
            "id": None,
            "name": name,
            "chapter": None,
            "role": "candidate",
            "confidence": confidence,
            "source": "knowledge_candidate",
            "mastery": None,
            "attempts": 0,
        }
        for name, confidence in extract_knowledge_candidates(raw)
    ]
    if candidates:
        return candidates[:5]

    return [
        {
            "id": None,
            "name": name,
            "chapter": None,
            "role": "candidate",
            "confidence": None,
            "source": "solution_step",
            "mastery": None,
            "attempts": 0,
        }
        for name in extract_used_knowledge(raw)
    ][:5]


def extract_knowledge_candidates(raw: dict) -> list[tuple[str, float | None]]:
    seen: set[str] = set()
    extracted: list[tuple[str, float | None]] = []
    for item in raw.get("knowledge_candidates") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("raw_name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        confidence = item.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None
        extracted.append((name, confidence_value))
    return extracted


def extract_used_knowledge(raw: dict) -> list[str]:
    seen: set[str] = set()
    extracted: list[str] = []
    solution = raw.get("solution") or {}
    for step in solution.get("solution_steps") or []:
        if not isinstance(step, dict):
            continue
        for name in step.get("used_knowledge") or []:
            name = str(name).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            extracted.append(name)
    return extracted


def choose_weak_points(
    knowledge_points: list[dict],
    grading: GradingResult | None,
) -> list[dict]:
    if not knowledge_points:
        return []

    weak = [
        point
        for point in knowledge_points
        if point["mastery"] is not None and point["mastery"] < 0.75
    ]
    if weak:
        return sorted(weak, key=lambda point: point["mastery"])[:2]

    score = float(grading.score) if grading and grading.score is not None else None
    answer_is_weak = grading and (
        grading.is_correct is False
        or (score is not None and score < 0.8)
        or grading.mistake_type
        in {
            "concept_error",
            "calculation_error",
            "graph_reading_error",
            "experiment_design_error",
            "formula_error",
            "no_answer",
            "partial",
        }
    )
    if answer_is_weak:
        return knowledge_points[:1]
    return []


def build_recommended_actions(
    *,
    knowledge_points: list[dict],
    weak_points: list[dict],
    grading: GradingResult | None,
) -> list[str]:
    actions: list[str] = []
    weak_name = weak_points[0]["name"] if weak_points else None
    primary_name = knowledge_points[0]["name"] if knowledge_points else None

    if weak_name:
        actions.append(f"先回看「{weak_name}」的基本概念，再重新解释本题关键一步。")
    elif primary_name:
        actions.append(f"把「{primary_name}」的解题条件和适用场景复述一遍。")

    mistake_type = grading.mistake_type if grading else None
    if mistake_type == "graph_reading_error":
        actions.append("读图时先标出横纵轴、单位和关键交点，再代入关系式。")
    elif mistake_type == "calculation_error":
        actions.append("把每一步公式和代入数值分开写，最后检查单位。")
    elif mistake_type == "formula_error":
        actions.append("先判断公式适用条件，再代入题目中的已知量。")
    elif mistake_type == "concept_error":
        actions.append("先圈出研究对象，区分题目问的是整体还是局部。")
    elif mistake_type == "experiment_design_error":
        actions.append("按实验目的、器材作用、变量控制三步重新梳理。")
    elif mistake_type == "no_answer":
        actions.append("先写出已知量和要求量，再尝试列出第一条物理关系。")
    elif mistake_type == "partial":
        actions.append("保留已做对的步骤，只补齐缺失条件或最后判断。")

    if primary_name:
        actions.append(f"再做 1-2 道「{primary_name}」同类题，确认不是偶然做对。")

    deduped = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped[:3]
