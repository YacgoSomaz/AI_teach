"""
数据导出 API

支持将学生知识点掌握数据导出为 JSON 或 CSV 格式。
student_id 通过鉴权依赖注入（IDOR 防护）。
"""

import csv
import io
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_student_id
from src.db.session import get_db
from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile

router = APIRouter(prefix="/api/export", tags=["export"])

CSV_HEADERS = [
    "knowledge_point_id",
    "knowledge_point_name",
    "subject",
    "grade",
    "mastery_score",
    "mastery_level",
    "appear_count",
    "error_count",
    "error_rate",
    "review_priority",
    "last_reviewed_at",
]


def _mastery_level(score: float) -> str:
    if score < 0.4:
        return "weak"
    if score < 0.7:
        return "medium"
    return "strong"


def _row_dict(profile: StudentKnowledgeProfile, kp: KnowledgePoint) -> dict:
    appear = profile.appear_count
    error = profile.error_count
    error_rate = round(error / appear, 4) if appear > 0 else 0.0
    reviewed = (
        profile.last_reviewed_at.isoformat() if profile.last_reviewed_at else ""
    )
    return {
        "knowledge_point_id": str(kp.id),
        "knowledge_point_name": kp.name,
        "subject": kp.subject,
        "grade": kp.grade or "",
        "mastery_score": profile.mastery_score,
        "mastery_level": _mastery_level(profile.mastery_score),
        "appear_count": appear,
        "error_count": error,
        "error_rate": error_rate,
        "review_priority": profile.review_priority,
        "last_reviewed_at": reviewed,
    }


async def _fetch_rows(student_id: str, db: AsyncSession) -> list[tuple]:
    stmt = (
        select(StudentKnowledgeProfile, KnowledgePoint)
        .join(KnowledgePoint, StudentKnowledgeProfile.knowledge_point_id == KnowledgePoint.id)
        .where(StudentKnowledgeProfile.student_id == student_id)
        .order_by(StudentKnowledgeProfile.mastery_score.asc())
    )
    result = await db.execute(stmt)
    return result.all()


@router.get("/knowledge-points/json")
async def export_knowledge_points_json(
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """将学生知识点掌握数据导出为 JSON 文件。"""
    rows = await _fetch_rows(current_student_id, db)
    payload = {
        "student_id": current_student_id,
        "exported_at": datetime.utcnow().isoformat(),
        "total": len(rows),
        "knowledge_points": [_row_dict(p, kp) for p, kp in rows],
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    filename = f"knowledge_points_{current_student_id}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/knowledge-points/csv")
async def export_knowledge_points_csv(
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """将学生知识点掌握数据导出为 CSV 文件。"""
    rows = await _fetch_rows(current_student_id, db)

    def generate():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=CSV_HEADERS)
        writer.writeheader()
        yield buf.getvalue()

        for profile, kp in rows:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=CSV_HEADERS)
            writer.writerow(_row_dict(profile, kp))
            yield buf.getvalue()

    filename = f"knowledge_points_{current_student_id}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
