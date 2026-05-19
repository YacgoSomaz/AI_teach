"""
数据导出 API

路由只负责：参数校验、权限校验、返回 Response。
业务查询与格式组装由 ExportService 负责。
"""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import check_ownership, get_current_student_id
from src.db.session import get_db
from src.services.export_service import ExportService, KP_HEADERS, QUESTION_HEADERS

router = APIRouter(prefix="/api/export", tags=["export"])

_EXCEL_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/student/{student_id}/knowledge-points")
async def export_knowledge_points(
    student_id: str,
    format: Literal["json", "csv", "excel"] = Query(default="json", description="导出格式"),
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
):
    """将学生知识点掌握数据导出为 JSON、CSV 或 Excel 文件。"""
    await check_ownership(student_id, current_student_id)
    svc = ExportService(db)
    rows = await svc.fetch_knowledge_points(student_id)

    if format == "json":
        payload = svc.json_envelope(student_id, "knowledge_points", rows)
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="knowledge_points_{student_id}.json"'},
        )

    if format == "csv":
        return StreamingResponse(
            ExportService.build_csv_lines(KP_HEADERS, rows),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="knowledge_points_{student_id}.csv"'},
        )

    return Response(
        content=ExportService.build_excel(KP_HEADERS, rows),
        media_type=_EXCEL_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="knowledge_points_{student_id}.xlsx"'},
    )


@router.get("/student/{student_id}/questions")
async def export_questions(
    student_id: str,
    format: Literal["json", "csv", "excel"] = Query(default="json", description="导出格式"),
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
):
    """将学生题目记录导出为 JSON、CSV 或 Excel 文件。"""
    await check_ownership(student_id, current_student_id)
    svc = ExportService(db)
    rows = await svc.fetch_questions(student_id)

    if format == "json":
        payload = svc.json_envelope(student_id, "questions", rows)
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="questions_{student_id}.json"'},
        )

    if format == "csv":
        return StreamingResponse(
            ExportService.build_csv_lines(QUESTION_HEADERS, rows),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="questions_{student_id}.csv"'},
        )

    return Response(
        content=ExportService.build_excel(QUESTION_HEADERS, rows),
        media_type=_EXCEL_MEDIA,
        headers={"Content-Disposition": f'attachment; filename="questions_{student_id}.xlsx"'},
    )
