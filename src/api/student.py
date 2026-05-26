"""
学生画像查询 API

提供学生知识点掌握情况的只读查询接口。
student_id 通过鉴权依赖注入，不接受调用方直接传入（IDOR 防护）。
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import Pagination, check_ownership, get_current_student_id
from src.db.session import get_db
from src.models.assignment import Assignment, AssignmentStatus
from src.models.grading import AssignmentAnalysis, GradingResult
from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile

router = APIRouter(prefix="/api/students", tags=["students"])

MASTERY_WEAK_THRESHOLD = 0.6

# 中文科目名 → 前端 subjectId
SUBJECT_FROM_CHINESE: dict[str, str] = {
    "物理": "phys", "数学": "math", "语文": "cn",
    "英语": "en", "化学": "chem", "生物": "bio",
}

# 这些状态表示批改仍在进行中
GRADING_IN_PROGRESS: frozenset[str] = frozenset({
    AssignmentStatus.UPLOADED, AssignmentStatus.OCR_QUEUED,
    AssignmentStatus.OCR_RUNNING, AssignmentStatus.OCR_DONE,
    AssignmentStatus.AI_QUEUED, AssignmentStatus.AI_RUNNING,
})


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


class AssignmentSummary(BaseModel):
    assignment_id: str
    status: str              # grading | graded | failed
    created_at: str          # ISO 8601 时间戳
    time_display: str        # 人性化相对时间，如"刚刚"、"3 分钟前"
    subject_id: Optional[str]   # 前端科目 ID（phys / math / …）
    title: str               # 作业标题（原始文件名去扩展名）
    question_count: int      # 题目数量
    verdict: Optional[str]   # correct | partial | wrong
    score: Optional[float]
    total_score: Optional[float]


class AssignmentListResponse(BaseModel):
    student_id: str
    total: int
    items: list[AssignmentSummary]


# ─── Helpers ────────────────────────────────────────────────────────────────




def _time_display(created_at: datetime) -> str:
    """将 created_at 转换为中文相对时间字符串。"""
    now = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    delta = now - created_at
    minutes = int(delta.total_seconds() / 60)
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes} 分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时前"
    days = hours // 24
    if days == 1:
        return "昨天"
    return f"{days} 天前"


def _derive_verdict(
    is_correct: Optional[bool],
    score: object,
    max_score: object,
) -> Optional[str]:
    """根据批改结果推导 verdict（correct / partial / wrong）。"""
    if is_correct is None:
        return None
    if is_correct:
        return "correct"
    try:
        ratio = float(score) / float(max_score) if max_score else 0.0
    except (TypeError, ZeroDivisionError):
        ratio = 0.0
    return "partial" if ratio > 0 else "wrong"


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


@router.get("/{student_id}/assignments", response_model=AssignmentListResponse)
async def list_student_assignments(
    student_id: str,
    limit: int = 50,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> AssignmentListResponse:
    """获取学生历史作业列表，含批改状态和摘要。

    LEFT JOIN assignment_analyses 和 grading_results，按上传时间倒序返回。
    """
    await check_ownership(student_id, current_student_id)

    stmt = (
        select(Assignment, AssignmentAnalysis, GradingResult)
        .outerjoin(AssignmentAnalysis, Assignment.id == AssignmentAnalysis.assignment_id)
        .outerjoin(GradingResult, Assignment.id == GradingResult.assignment_id)
        .where(Assignment.student_id == student_id)
        .order_by(Assignment.created_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()

    items: list[AssignmentSummary] = []
    for assignment, analysis, grading in rows:
        # 映射前端状态
        asgn_status: str = assignment.status
        if asgn_status == AssignmentStatus.AI_DONE:
            fe_status = "graded"
        elif asgn_status in GRADING_IN_PROGRESS:
            fe_status = "grading"
        else:
            fe_status = "failed"

        # 科目映射
        subject_id: Optional[str] = None
        if analysis and analysis.detected_subject:
            subject_id = SUBJECT_FROM_CHINESE.get(analysis.detected_subject)

        # 标题：去除文件扩展名
        title: str = assignment.original_filename
        if "." in title:
            title = title.rsplit(".", 1)[0]

        # 题目数量：从 question_struct 推断
        question_count = 1
        if analysis and analysis.question_struct:
            qs = analysis.question_struct
            if isinstance(qs, dict):
                questions_list = qs.get("questions", [])
                if isinstance(questions_list, list) and questions_list:
                    question_count = len(questions_list)

        # 判题结果
        verdict: Optional[str] = None
        score: Optional[float] = None
        total_score: Optional[float] = None
        if grading:
            verdict = _derive_verdict(grading.is_correct, grading.score, grading.max_score)
            score = float(grading.score) if grading.score is not None else None
            total_score = float(grading.max_score) if grading.max_score is not None else 1.0

        items.append(
            AssignmentSummary(
                assignment_id=str(assignment.id),
                status=fe_status,
                created_at=assignment.created_at.isoformat(),
                time_display=_time_display(assignment.created_at),
                subject_id=subject_id,
                title=title,
                question_count=question_count,
                verdict=verdict,
                score=score,
                total_score=total_score,
            )
        )

    return AssignmentListResponse(
        student_id=student_id,
        total=len(items),
        items=items,
    )
