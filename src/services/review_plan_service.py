"""
复习计划生成服务

根据学生知识点掌握度生成每日复习任务清单。

算法（规则引擎 v1）：
  priority_score = (1 - mastery_score) × recency_weight
  recency_weight = min(days_since_last_review / 30, 1.0) + 1.0  → 范围 [1.0, 2.0]
  未复习过时 recency_weight = 2.0（最大紧迫度）

优先级映射：
  score ≥ 1.0 → high
  score ≥ 0.5 → medium
  score <  0.5 → low
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile

# ─── 公开常量 ────────────────────────────────────────────────────────────────

MASTERY_WEAK_THRESHOLD = 0.6
PRIORITY_HIGH_THRESHOLD = 1.0
PRIORITY_MEDIUM_THRESHOLD = 0.5
RECENCY_DAYS_CAP = 30.0


# ─── 纯函数（可单独单元测试） ──────────────────────────────────────────────


def calculate_priority_score(
    mastery_score: float,
    last_reviewed_at: Optional[datetime],
) -> float:
    """
    计算单个知识点的复习优先级分数。

    Args:
        mastery_score: 掌握度 0-1，越低越需要复习
        last_reviewed_at: 上次复习时间，None 表示从未复习

    Returns:
        float: 优先级分数，越高越优先
    """
    if last_reviewed_at is None:
        recency_weight = 2.0
    else:
        now = datetime.now(timezone.utc)
        if last_reviewed_at.tzinfo is None:
            last_reviewed_at = last_reviewed_at.replace(tzinfo=timezone.utc)
        days_elapsed = max((now - last_reviewed_at).total_seconds() / 86400, 0.0)
        normalized = min(days_elapsed / RECENCY_DAYS_CAP, 1.0)
        recency_weight = normalized + 1.0  # 范围 [1.0, 2.0]

    return (1.0 - mastery_score) * recency_weight


def determine_priority(score: float) -> str:
    """将数值分数映射为 high / medium / low。"""
    if score >= PRIORITY_HIGH_THRESHOLD:
        return "high"
    if score >= PRIORITY_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def estimate_recommended_count(mastery_score: float) -> int:
    """根据掌握度估算建议练习题目数。"""
    if mastery_score < 0.3:
        return 5
    if mastery_score < 0.6:
        return 3
    return 2


def build_reason(
    mastery_score: float,
    appear_count: int,
    error_count: int,
    last_reviewed_at: Optional[datetime],
) -> str:
    """生成人类可读的复习原因说明。"""
    parts = []

    if mastery_score < 0.3:
        parts.append(f"掌握度仅 {mastery_score:.0%}，需要重点强化")
    elif mastery_score < 0.6:
        parts.append(f"掌握度 {mastery_score:.0%}，尚未巩固")

    if appear_count > 0:
        error_rate = error_count / appear_count
        if error_rate > 0.5:
            parts.append(f"历史错误率 {error_rate:.0%}")

    if last_reviewed_at is None:
        parts.append("从未复习")
    else:
        now = datetime.now(timezone.utc)
        if last_reviewed_at.tzinfo is None:
            last_reviewed_at = last_reviewed_at.replace(tzinfo=timezone.utc)
        days = (now - last_reviewed_at).days
        if days >= 7:
            parts.append(f"距上次复习已 {days} 天")

    return "；".join(parts) if parts else "建议适量练习巩固"


# ─── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass
class ReviewTaskItem:
    """单条复习任务"""
    knowledge_point_id: str
    knowledge_point_name: str
    subject: str
    mastery_score: float
    priority: str
    reason: str
    recommended_count: int
    estimated_minutes: int
    grade: Optional[str] = None


@dataclass
class DailyReviewPlan:
    """今日复习计划"""
    student_id: str
    date: str
    tasks: list = field(default_factory=list)
    total_minutes: int = 0


# ─── 服务类 ──────────────────────────────────────────────────────────────────


class ReviewPlanService:
    """
    复习计划生成服务

    只读操作，不写入任何数据。
    由 FastAPI Depends 注入 AsyncSession。
    """

    def __init__(self, db: AsyncSession):
        self._db = db

    async def generate_today_plan(
        self,
        student_id: str,
        max_tasks: int = 5,
    ) -> DailyReviewPlan:
        """
        生成今日复习计划，返回按优先级排序的前 max_tasks 条任务。
        """
        rows = await self._fetch_profiles_with_kp(student_id)

        scored: list[tuple[float, ReviewTaskItem]] = []
        for profile, kp in rows:
            score = calculate_priority_score(
                mastery_score=profile.mastery_score,
                last_reviewed_at=profile.last_reviewed_at,
            )
            count = estimate_recommended_count(profile.mastery_score)
            item = ReviewTaskItem(
                knowledge_point_id=str(kp.id),
                knowledge_point_name=kp.name,
                subject=kp.subject,
                grade=kp.grade,
                mastery_score=profile.mastery_score,
                priority=determine_priority(score),
                reason=build_reason(
                    profile.mastery_score,
                    profile.appear_count,
                    profile.error_count,
                    profile.last_reviewed_at,
                ),
                recommended_count=count,
                estimated_minutes=count * 5,
            )
            scored.append((score, item))

        scored.sort(key=lambda t: t[0], reverse=True)
        tasks = [item for _, item in scored[:max_tasks]]

        return DailyReviewPlan(
            student_id=student_id,
            date=date.today().isoformat(),
            tasks=tasks,
            total_minutes=sum(t.estimated_minutes for t in tasks),
        )

    async def _fetch_profiles_with_kp(self, student_id: str) -> list[tuple]:
        stmt = (
            select(StudentKnowledgeProfile, KnowledgePoint)
            .join(
                KnowledgePoint,
                StudentKnowledgeProfile.knowledge_point_id == KnowledgePoint.id,
            )
            .where(StudentKnowledgeProfile.student_id == student_id)
        )
        result = await self._db.execute(stmt)
        return result.all()
