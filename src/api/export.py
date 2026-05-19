"""
数据导出 API

路径：GET /api/export/student/{student_id}/knowledge-points?format=json|csv
student_id 路径参数与鉴权 Header 做所有权校验（IDOR 防护）。
"""

import csv
import io
import json
from datetime import datetime
from typing import Literal

import openpyxl

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_student_id
from src.db.session import get_db
from src.models.assignment import Assignment
from src.models.knowledge_point import KnowledgePoint
from src.models.question import Question
from src.models.student_profile import StudentKnowledgeProfile

router = APIRouter(prefix="/api/export", tags=["export"])

CSV_HEADERS = [
    "knowledge_point_id", "knowledge_point_name", "subject", "grade",
    "mastery_score", "mastery_level", "appear_count", "error_count",
    "error_rate", "review_priority", "last_reviewed_at",
]


async def _check_ownership(path_student_id: str, current_student_id: str) -> None:
    if path_student_id != current_student_id:
        raise HTTPException(status_code=404, detail="未找到该学生的数据")


def _mastery_level(score: float) -> str:
    if score < 0.4:
        return "weak"
    if score < 0.7:
        return "medium"
    return "strong"


def _row_dict(profile: StudentKnowledgeProfile, kp: KnowledgePoint) -> dict:
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
        "last_reviewed_at": profile.last_reviewed_at.isoformat() if profile.last_reviewed_at else "",
    }


async def _fetch_rows(student_id: str, db: AsyncSession) -> list[tuple]:
    stmt = (
        select(StudentKnowledgeProfile, KnowledgePoint)
        .join(KnowledgePoint, StudentKnowledgeProfile.knowledge_point_id == KnowledgePoint.id)
        .where(StudentKnowledgeProfile.student_id == student_id)
        .order_by(StudentKnowledgeProfile.mastery_score.asc())
    )
    return (await db.execute(stmt)).all()


def _build_excel(headers: list[str], rows_data: list[dict]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows_data:
        ws.append([row.get(h, "") for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.get("/student/{student_id}/knowledge-points")
async def export_knowledge_points(
    student_id: str,
    format: Literal["json", "csv", "excel"] = Query(default="json", description="导出格式"),
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
):
    """将学生知识点掌握数据导出为 JSON 或 CSV 文件。"""
    await _check_ownership(student_id, current_student_id)
    rows = await _fetch_rows(student_id, db)

    if format == "json":
        payload = {
            "student_id": student_id,
            "exported_at": datetime.utcnow().isoformat(),
            "total": len(rows),
            "knowledge_points": [_row_dict(p, kp) for p, kp in rows],
        }
        filename = f"knowledge_points_{student_id}.json"
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if format == "csv":
        filename = f"knowledge_points_{student_id}.csv"

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

        return StreamingResponse(
            generate(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Excel
    filename = f"knowledge_points_{student_id}.xlsx"
    data = _build_excel(CSV_HEADERS, [_row_dict(p, kp) for p, kp in rows])
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


QUESTIONS_CSV_HEADERS = [
    "question_id", "raw_text", "subject", "grade",
    "question_type", "difficulty", "review_priority", "need_review",
]


def _question_dict(q: Question) -> dict:
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


async def _fetch_questions(student_id: str, db: AsyncSession) -> list[Question]:
    stmt = (
        select(Question)
        .join(Assignment, Question.assignment_id == Assignment.id)
        .where(Assignment.student_id == student_id)
        .order_by(Question.created_at.desc())
    )
    return (await db.execute(stmt)).all()


@router.get("/student/{student_id}/questions")
async def export_questions(
    student_id: str,
    format: Literal["json", "csv", "excel"] = Query(default="json", description="导出格式"),
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
):
    """将学生题目记录导出为 JSON、CSV 或 Excel 文件。"""
    await _check_ownership(student_id, current_student_id)
    rows = await _fetch_questions(student_id, db)
    questions_data = [_question_dict(r[0] if isinstance(r, tuple) else r) for r in rows]

    if format == "json":
        payload = {
            "student_id": student_id,
            "exported_at": datetime.utcnow().isoformat(),
            "total": len(questions_data),
            "questions": questions_data,
        }
        filename = f"questions_{student_id}.json"
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if format == "csv":
        filename = f"questions_{student_id}.csv"

        def generate():
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=QUESTIONS_CSV_HEADERS)
            writer.writeheader()
            yield buf.getvalue()
            for d in questions_data:
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=QUESTIONS_CSV_HEADERS)
                writer.writerow(d)
                yield buf.getvalue()

        return StreamingResponse(
            generate(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Excel
    filename = f"questions_{student_id}.xlsx"
    data = _build_excel(QUESTIONS_CSV_HEADERS, questions_data)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
