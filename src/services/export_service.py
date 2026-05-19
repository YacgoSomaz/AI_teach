"""
导出服务

负责知识点、题目的数据查询、字段转换、序列化格式构建。
路由层只负责参数校验、权限校验、返回 Response。
"""

import csv
import io
from datetime import datetime, timezone
from typing import Generator

import openpyxl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.assignment import Assignment
from src.models.knowledge_point import KnowledgePoint
from src.models.question import Question
from src.models.student_profile import StudentKnowledgeProfile

KP_HEADERS = [
    "knowledge_point_id", "knowledge_point_name", "subject", "grade",
    "mastery_score", "mastery_level", "appear_count", "error_count",
    "error_rate", "review_priority", "last_reviewed_at",
]

QUESTION_HEADERS = [
    "question_id", "raw_text", "subject", "grade",
    "question_type", "difficulty", "review_priority", "need_review",
]


def _mastery_level(score: float) -> str:
    if score < 0.4:
        return "weak"
    if score < 0.7:
        return "medium"
    return "strong"


class ExportService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def fetch_knowledge_points(self, student_id: str) -> list[dict]:
        """查询学生所有知识点掌握记录，返回已组装的字段字典列表。"""
        stmt = (
            select(StudentKnowledgeProfile, KnowledgePoint)
            .join(KnowledgePoint, StudentKnowledgeProfile.knowledge_point_id == KnowledgePoint.id)
            .where(StudentKnowledgeProfile.student_id == student_id)
            .order_by(StudentKnowledgeProfile.mastery_score.asc())
        )
        rows = (await self._db.execute(stmt)).all()
        return [self._kp_row(p, kp) for p, kp in rows]

    async def fetch_questions(self, student_id: str) -> list[dict]:
        """查询学生所有题目记录（经由 Assignment 关联），返回已组装的字段字典列表。"""
        stmt = (
            select(Question)
            .join(Assignment, Question.assignment_id == Assignment.id)
            .where(Assignment.student_id == student_id)
            .order_by(Question.created_at.desc())
        )
        rows = (await self._db.execute(stmt)).all()
        return [self._question_row(r[0] if isinstance(r, tuple) else r) for r in rows]

    def json_envelope(self, student_id: str, key: str, rows: list[dict]) -> dict:
        """构建 JSON 导出 envelope。"""
        return {
            "student_id": student_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total": len(rows),
            key: rows,
        }

    @staticmethod
    def build_excel(headers: list[str], rows: list[dict]) -> bytes:
        """将字典列表序列化为 xlsx bytes。"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append([row.get(h, "") for h in headers])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    @staticmethod
    def build_csv_lines(headers: list[str], rows: list[dict]) -> Generator[str, None, None]:
        """逐行生成 CSV 文本，供 StreamingResponse 使用。"""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=headers)
        writer.writeheader()
        yield buf.getvalue()
        for row in rows:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=headers)
            writer.writerow(row)
            yield buf.getvalue()

    @staticmethod
    def _kp_row(profile: StudentKnowledgeProfile, kp: KnowledgePoint) -> dict:
        appear = profile.appear_count
        error = profile.error_count
        return {
            "knowledge_point_id": str(kp.id),
            "knowledge_point_name": kp.name,
            "subject": kp.subject,
            "grade": kp.grade or "",
            "mastery_score": profile.mastery_score,
            "mastery_level": _mastery_level(profile.mastery_score),
            "appear_count": appear,
            "error_count": error,
            "error_rate": round(error / appear, 4) if appear > 0 else 0.0,
            "review_priority": profile.review_priority,
            "last_reviewed_at": (
                profile.last_reviewed_at.isoformat() if profile.last_reviewed_at else ""
            ),
        }

    @staticmethod
    def _question_row(q: Question) -> dict:
        return {
            "question_id": str(q.id),
            "raw_text": q.raw_text or "",
            "subject": q.subject or "",
            "grade": q.grade or "",
            "question_type": q.question_type or "",
            "difficulty": q.difficulty if q.difficulty is not None else "",
            "review_priority": q.review_priority or "",
            "need_review": str(q.need_review) if q.need_review is not None else "",
        }
