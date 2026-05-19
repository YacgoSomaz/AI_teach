"""
学习报告生成服务

汇总学生的知识点掌握情况、复习历史和错题分布，生成结构化报告。
纯读操作，不写入任何数据。
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile

MASTERY_WEAK = 0.4
MASTERY_MEDIUM = 0.7


# ─── 纯函数 ──────────────────────────────────────────────────────────────────


def classify_mastery(score: float) -> str:
    """将 0-1 掌握度分为 weak / medium / strong 三档。"""
    if score < MASTERY_WEAK:
        return "weak"
    if score < MASTERY_MEDIUM:
        return "medium"
    return "strong"


def compute_error_rate(appear_count: int, error_count: int) -> float:
    """计算错误率，当 appear_count == 0 时返回 0.0。"""
    if appear_count == 0:
        return 0.0
    return round(error_count / appear_count, 4)


def compute_overall_mastery(scores: list[float]) -> float:
    """计算平均掌握度，空列表返回 0.0。"""
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


# ─── 数据结构 ────────────────────────────────────────────────────────────────


@dataclass
class SubjectSummary:
    """单学科汇总"""
    subject: str
    total: int
    weak_count: int
    medium_count: int
    strong_count: int
    average_mastery: float
    average_error_rate: float


@dataclass
class KnowledgePointDetail:
    """单知识点详情（用于报告展示）"""
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


@dataclass
class LearningReport:
    """完整学习报告"""
    student_id: str
    generated_at: str
    total_knowledge_points: int
    overall_mastery: float
    weak_count: int
    medium_count: int
    strong_count: int
    subjects: list[SubjectSummary] = field(default_factory=list)
    top_weak_points: list[KnowledgePointDetail] = field(default_factory=list)
    top_strong_points: list[KnowledgePointDetail] = field(default_factory=list)


# ─── 服务类 ──────────────────────────────────────────────────────────────────


class ReportService:
    """
    学习报告生成服务。
    只读操作，由 FastAPI Depends 注入 AsyncSession。
    """

    def __init__(self, db: AsyncSession):
        self._db = db

    async def generate_report(
        self,
        student_id: str,
        top_n: int = 5,
    ) -> LearningReport:
        """
        生成学生学习报告。

        Args:
            student_id: 学生 ID
            top_n: 薄弱/优秀知识点各展示前 N 条

        Returns:
            LearningReport 数据结构
        """
        rows = await self._fetch_all(student_id)

        if not rows:
            return LearningReport(
                student_id=student_id,
                generated_at=datetime.utcnow().isoformat(),
                total_knowledge_points=0,
                overall_mastery=0.0,
                weak_count=0,
                medium_count=0,
                strong_count=0,
            )

        details = [self._to_detail(profile, kp) for profile, kp in rows]

        overall_mastery = compute_overall_mastery([d.mastery_score for d in details])
        weak_count = sum(1 for d in details if d.mastery_level == "weak")
        medium_count = sum(1 for d in details if d.mastery_level == "medium")
        strong_count = sum(1 for d in details if d.mastery_level == "strong")

        subjects = self._build_subject_summaries(details)

        sorted_by_mastery = sorted(details, key=lambda d: d.mastery_score)
        top_weak = sorted_by_mastery[:top_n]
        top_strong = sorted(details, key=lambda d: d.mastery_score, reverse=True)[:top_n]

        return LearningReport(
            student_id=student_id,
            generated_at=datetime.utcnow().isoformat(),
            total_knowledge_points=len(details),
            overall_mastery=overall_mastery,
            weak_count=weak_count,
            medium_count=medium_count,
            strong_count=strong_count,
            subjects=subjects,
            top_weak_points=top_weak,
            top_strong_points=top_strong,
        )

    def _to_detail(
        self,
        profile: StudentKnowledgeProfile,
        kp: KnowledgePoint,
    ) -> KnowledgePointDetail:
        return KnowledgePointDetail(
            knowledge_point_id=str(kp.id),
            knowledge_point_name=kp.name,
            subject=kp.subject,
            grade=kp.grade,
            mastery_score=profile.mastery_score,
            mastery_level=classify_mastery(profile.mastery_score),
            appear_count=profile.appear_count,
            error_count=profile.error_count,
            error_rate=compute_error_rate(profile.appear_count, profile.error_count),
            review_priority=profile.review_priority,
            last_reviewed_at=profile.last_reviewed_at,
        )

    def _build_subject_summaries(
        self,
        details: list[KnowledgePointDetail],
    ) -> list[SubjectSummary]:
        subject_groups: dict[str, list[KnowledgePointDetail]] = {}
        for d in details:
            subject_groups.setdefault(d.subject, []).append(d)

        summaries = []
        for subject, items in subject_groups.items():
            avg_mastery = compute_overall_mastery([i.mastery_score for i in items])
            avg_error_rate = compute_overall_mastery([i.error_rate for i in items])
            summaries.append(SubjectSummary(
                subject=subject,
                total=len(items),
                weak_count=sum(1 for i in items if i.mastery_level == "weak"),
                medium_count=sum(1 for i in items if i.mastery_level == "medium"),
                strong_count=sum(1 for i in items if i.mastery_level == "strong"),
                average_mastery=avg_mastery,
                average_error_rate=avg_error_rate,
            ))

        return sorted(summaries, key=lambda s: s.average_mastery)

    async def _fetch_all(self, student_id: str) -> list[tuple]:
        stmt = (
            select(StudentKnowledgeProfile, KnowledgePoint)
            .join(KnowledgePoint, StudentKnowledgeProfile.knowledge_point_id == KnowledgePoint.id)
            .where(StudentKnowledgeProfile.student_id == student_id)
        )
        result = await self._db.execute(stmt)
        return result.all()
