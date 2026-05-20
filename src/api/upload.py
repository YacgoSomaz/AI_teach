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

from src.api.deps import get_current_student_id
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

    # 5. 触发 OCR 异步任务（重复文件同样触发，每次上传独立处理）
    from src.tasks.ocr_tasks import process_ocr
    process_ocr.delay(str(assignment.id))

    # 6. 返回
    return UploadResponse(
        success=True,
        assignment_id=str(assignment.id),
        file_id=uploaded.file_id,
        status=assignment.status,
        is_duplicate=uploaded.is_duplicate,
        message="上传成功，正在处理中",
    )


@router.get("/assignments/{assignment_id}")
async def get_assignment_status(
    assignment_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
):
    """
    查询作业处理状态（需要身份校验）

    前端轮询此接口获取进度：
    - uploaded → ocr_queued → ocr_running → ocr_done → ai_queued → ai_running → ai_done

    只能查询属于当前学生的 assignment，否则返回 404（IDOR 防护）。
    
    返回字段：
    - assignment_id: 作业 ID
    - status: 当前状态
    - processing_status: 各环节处理状态（JSON）
    - error_message: 错误信息
    - created_at / updated_at: 时间戳
    - ocr_text: OCR 提取的纯文本（OCR 完成后可用）
    - ocr_markdown: OCR 提取的 Markdown（OCR 完成后可用）
    - image_url: 图片访问 URL（HTTP 可访问）
    - file_url: 文件存储路径（内部使用）
    - ai_error_message: AI 分析错误信息（从 processing_status 提取）
    """
    try:
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

    # 记录不存在 / 不属于当前学生，统一返回 404，不区分两种情况（防止枚举）
    if not assignment or assignment.student_id != current_student_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="作业记录不存在",
        )

    # 获取 OCR 结果（如果存在）
    from src.models.ocr_task import OCRTask
    ocr_result = await db.execute(
        select(OCRTask)
        .where(OCRTask.assignment_id == assignment.id)
        .order_by(OCRTask.created_at.desc())
    )
    latest_ocr = ocr_result.scalar_one_or_none()

    # 提取 AI 错误信息
    ai_error_message = None
    if assignment.processing_status and "ai" in assignment.processing_status:
        ai_status = assignment.processing_status["ai"]
        if ai_status.get("status") in ("failed", "error"):
            ai_error_message = ai_status.get("error")

    return {
        "assignment_id": str(assignment.id),
        "status": assignment.status,
        "processing_status": assignment.processing_status,
        "error_message": assignment.error_message,
        "created_at": assignment.created_at.isoformat(),
        "updated_at": assignment.updated_at.isoformat(),
        # OCR 结果（OCR 完成后可用，即使 AI 失败也返回）
        "ocr_text": latest_ocr.raw_text if latest_ocr else None,
        "ocr_markdown": latest_ocr.markdown if latest_ocr else None,
        # 图片 URL（HTTP 可访问）
        "image_url": f"/api/assignments/{assignment.id}/file",
        # 文件存储路径（内部使用）
        "file_url": assignment.storage_url,
        # AI 错误信息
        "ai_error_message": ai_error_message,
    }


@router.get("/assignments/{assignment_id}/file")
async def get_assignment_file(
    assignment_id: str,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
):
    """
    获取作业原始图片文件（需要身份校验）
    
    返回该 assignment 对应的原始上传图片。
    只能访问属于当前学生的 assignment，否则返回 404（IDOR 防护）。
    
    Args:
        assignment_id: 作业 ID
        current_student_id: 当前学生 ID（从认证中获取）
        db: 数据库会话
    
    Returns:
        FileResponse: 图片文件
    """
    try:
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

    # 记录不存在 / 不属于当前学生，统一返回 404，不区分两种情况（防止枚举）
    if not assignment or assignment.student_id != current_student_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="作业记录不存在",
        )

    # 获取文件路径
    storage_url = assignment.storage_url
    if not storage_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件路径不存在",
        )

    # 处理 file:// 前缀
    file_path = storage_url
    if file_path.startswith("file://"):
        file_path = file_path[7:]  # 去掉 "file://"

    # 路径安全检查（防止路径遍历攻击）
    import os
    
    # 解析真实路径
    try:
        real_path = os.path.realpath(file_path)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件路径无效",
        )
    
    # 检查文件是否存在且是文件
    if not os.path.exists(real_path) or not os.path.isfile(real_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )
    
    # 确认路径在 uploads 目录下（防止路径遍历）
    uploads_dir = os.path.realpath("uploads")
    if not real_path.startswith(uploads_dir):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该文件",
        )

    # 返回文件
    from fastapi.responses import FileResponse
    return FileResponse(
        path=real_path,
        media_type=assignment.mime_type or "image/jpeg",
        filename=assignment.original_filename,
    )
