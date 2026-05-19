"""
可视化服务

负责雷达图、热力图、进度折线图的数据查询与聚合。
路由层只负责参数校验、权限校验、返回 Response。
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile


class VisualizationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_radar_data(self, student_id: str) -> tuple[list[str], list[float]]:
        """按学科聚合平均掌握度。返回 (labels, values)。"""
        stmt = (
            select(KnowledgePoint.subject, func.avg(StudentKnowledgeProfile.mastery_score))
            .join(KnowledgePoint, StudentKnowledgeProfile.knowledge_point_id == KnowledgePoint.id)
            .where(StudentKnowledgeProfile.student_id == student_id)
            .group_by(KnowledgePoint.subject)
            .order_by(KnowledgePoint.subject)
        )
        rows = (await self._db.execute(stmt)).all()
        return [r[0] for r in rows], [round(r[1], 4) for r in rows]

    async def get_heatmap_data(self, student_id: str) -> tuple[list[str], list[int]]:
        """按日期统计复习次数。返回 (dates, counts)。"""
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
        rows = (await self._db.execute(stmt)).all()
        return [str(r[0]) for r in rows], [int(r[1]) for r in rows]

    async def get_progress_line_data(self, student_id: str) -> tuple[list[str], list[float]]:
        """按日期聚合平均掌握度。返回 (dates, mastery_scores)。"""
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
        rows = (await self._db.execute(stmt)).all()
        return [str(r[0]) for r in rows], [round(r[1], 4) for r in rows]
