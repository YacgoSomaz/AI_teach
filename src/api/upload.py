"""
文件上传 API

POST /api/upload
- 接收图片文件
- 校验、计算 hash、存储
- 创建 Assignment 记录
- 返回 file_id 和任务状态

设计原则（来自 fastapi-patterns skill）：
- 立即返回，不阻塞请求
- OCR 和 AI 分析异步处理
- 前端轮询 /api/assignments/{id} 获取进度
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rate_limit import upload_rate_limit
from src.db.session import get_db
from src.models.assignment import Assignment, AssignmentStatus
from src.services.file_service import (
    FileService,
    FileValidationError,
    LocalFileStorage,
)

router = APIRouter(prefix="/api", tags=["upload"])


class UploadResponse(BaseModel):
    """上传响应"""
    success: bool
    assignment_id: str
    file_id: str
    status: str
    is_duplicate: bool
    message: str


@router.post("/upload", response_model=UploadResponse)
async def upload_assignment(
    file: UploadFile = File(...),
    student_id: str = Depends(upload_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    """
    上传作业图片

    流程：
    1. 校验文件
    2. 计算 hash，检查是否重复
    3. 存储文件
    4. 创建 Assignment 记录
    5. 返回 assignment_id（前端用于轮询状态）

    后续：
    - Celery 任务监听 Assignment 创建事件
    - 自动触发 OCR → AI 分析流程
    """
    # 1. 读取文件内容
    try:
        file_content = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件读取失败：{e}",
        )

    # 2. 查询已存在的 hash（去重）
    result = await db.execute(select(Assignment.file_hash))
    existing_hashes = {row[0] for row in result.fetchall()}

    # 3. 文件服务：校验 + 存储
    file_service = FileService(storage=LocalFileStorage())
    try:
        uploaded = file_service.upload(
            filename=file.filename or "unknown.jpg",
            mime_type=file.content_type or "image/jpeg",
            file_content=file_content,
            existing_hashes=existing_hashes,
        )
    except FileValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # 4. 创建 Assignment 记录
    assignment = Assignment(
        student_id=student_id,
        file_id=uploaded.file_id,
        file_hash=uploaded.file_hash,
        original_filename=uploaded.original_filename,
        file_size=uploaded.file_size,
        mime_type=uploaded.mime_type,
        storage_url=uploaded.storage_url,
        status=AssignmentStatus.UPLOADED,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)

    # 5. 触发 OCR 异步任务
    if not uploaded.is_duplicate:
        from src.tasks.ocr_tasks import process_ocr
        process_ocr.delay(str(assignment.id))
    
    # 6. 返回
    return UploadResponse(
        success=True,
        assignment_id=str(assignment.id),
        file_id=uploaded.file_id,
        status=assignment.status,
        is_duplicate=uploaded.is_duplicate,
        message="上传成功，正在处理中" if not uploaded.is_duplicate else "文件已存在，跳过 OCR",
    )


@router.get("/assignments/{assignment_id}")
async def get_assignment_status(
    assignment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    查询作业处理状态

    前端轮询此接口获取进度：
    - uploaded → ocr_queued → ocr_running → ocr_done → ai_queued → ai_running → ai_done
    """
    try:
        # 将字符串转换为 UUID（如果是 UUID 格式）
        import uuid
        assignment_uuid = uuid.UUID(assignment_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的 assignment_id 格式",
        )
    
    result = await db.execute(
        select(Assignment).where(Assignment.id == assignment_uuid)
    )
    assignment = result.scalar_one_or_none()

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="作业记录不存在",
        )

    return {
        "assignment_id": str(assignment.id),
        "status": assignment.status,
        "error_message": assignment.error_message,
        "created_at": assignment.created_at.isoformat(),
        "updated_at": assignment.updated_at.isoformat(),
    }
