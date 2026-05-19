"""
OCR 异步任务

负责：
1. 从对象存储获取图片
2. 调用 PaddleOCR API
3. 保存 OCR 结果到数据库
4. 发布 OCR 完成事件（解耦）

设计改进：
- 使用统一数据库连接（共享引擎）
- 使用统一配置管理
- 错误隔离：OCR 失败不影响其他环节
- 事件驱动：发布事件而非直接调用下游任务
"""

import asyncio
from uuid import UUID

from celery import Task
from sqlalchemy import select

from src.adapters.ocr import OCRException, PaddleOCRAdapter
from src.celery_app import app
from src.config import settings
from src.db.session import get_celery_session
from src.models.assignment import Assignment, AssignmentStatus
from src.models.ocr_task import OCRTask as OCRTaskModel, OCRTaskStatus


class OCRTask(Task):
    """OCR 任务基类"""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """任务失败回调"""
        print(f"OCR 任务失败: {task_id}, 错误: {exc}")


@app.task(base=OCRTask, bind=True, max_retries=settings.celery_max_retries)
def process_ocr(self, assignment_id: str):
    """
    处理 OCR 任务
    
    Args:
        assignment_id: 作业 ID
    
    流程：
    1. 更新 Assignment 状态为 ocr_running
    2. 创建 OCRTask 记录
    3. 调用 PaddleOCR API
    4. 保存 OCR 结果
    5. 更新状态为 ocr_done
    6. 发布 OCR 完成事件（解耦）
    """
    # Celery 任务中运行异步代码
    return asyncio.run(_process_ocr_async(self, assignment_id))


async def _process_ocr_async(task, assignment_id: str):
    """异步 OCR 处理逻辑"""
    assignment = None  # 初始化 assignment 变量
    async with get_celery_session() as db:
        try:
            # 1. 查询 Assignment
            result = await db.execute(
                select(Assignment).where(Assignment.id == UUID(assignment_id))
            )
            assignment = result.scalar_one_or_none()
            
            if not assignment:
                raise ValueError(f"Assignment {assignment_id} 不存在")
            
            # 2. 更新状态为 ocr_running
            assignment.status = AssignmentStatus.OCR_RUNNING
            await db.commit()
            
            # 3. 创建 OCRTask 记录
            ocr_task = OCRTaskModel(
                assignment_id=assignment.id,
                provider="paddleocr-vl-1.5",
                status=OCRTaskStatus.RUNNING,
            )
            db.add(ocr_task)
            await db.commit()
            await db.refresh(ocr_task)
            
            # 4. 调用 PaddleOCR API
            settings.validate_required_for_ocr()  # 校验配置
            adapter = PaddleOCRAdapter(token=settings.paddleocr_token)
            
            # 从 storage_url 获取文件路径
            file_path = assignment.storage_url.replace("file://", "")
            
            try:
                ocr_result = adapter.process_file(
                    file_path=file_path,
                    file_id=assignment.file_id,
                )
                
                # 5. 保存 OCR 结果
                ocr_task.status = OCRTaskStatus.DONE
                ocr_task.raw_text = ocr_result.raw_text
                ocr_task.markdown = ocr_result.markdown
                ocr_task.images = ocr_result.images
                ocr_task.confidence = ocr_result.confidence
                ocr_task.total_pages = ocr_result.total_pages
                ocr_task.external_job_id = ocr_result.job_id
                
                # 6. 更新 Assignment 状态（部分成功）
                assignment.status = AssignmentStatus.OCR_DONE
                # 使用 processing_status 记录各环节状态（错误隔离）
                if not assignment.processing_status:
                    assignment.processing_status = {}
                assignment.processing_status["ocr"] = {
                    "status": "done",
                    "confidence": ocr_result.confidence,
                    "ocr_task_id": str(ocr_task.id),
                }
                
                await db.commit()
                
                # 7. 发布 OCR 完成事件（解耦）
                from src.tasks.ai_tasks import process_ai_analysis
                process_ai_analysis.delay(assignment_id)
                
                return {
                    "success": True,
                    "assignment_id": assignment_id,
                    "ocr_task_id": str(ocr_task.id),
                    "confidence": ocr_result.confidence,
                }
                
            except OCRException as e:
                # OCR 失败（错误隔离：只标记 OCR 环节失败）
                ocr_task.status = OCRTaskStatus.FAILED
                ocr_task.error_message = str(e)
                
                # 更新 processing_status（不直接标记整个 Assignment 失败）
                if not assignment.processing_status:
                    assignment.processing_status = {}
                assignment.processing_status["ocr"] = {
                    "status": "failed",
                    "error": str(e),
                    "retry_count": task.request.retries,
                }
                assignment.status = AssignmentStatus.OCR_FAILED
                
                await db.commit()
                
                # 重试
                if task.request.retries < task.max_retries:
                    raise task.retry(exc=e, countdown=60)  # 1分钟后重试
                
                raise
        
        except Exception as e:
            # 其他错误
            if assignment:
                if not assignment.processing_status:
                    assignment.processing_status = {}
                assignment.processing_status["ocr"] = {
                    "status": "error",
                    "error": str(e),
                }
                assignment.status = AssignmentStatus.OCR_FAILED
                assignment.retry_count += 1
                await db.commit()
            
            raise


@app.task
def check_ocr_status(assignment_id: str):
    """
    检查 OCR 任务状态（用于轮询）
    
    Args:
        assignment_id: 作业 ID
    
    Returns:
        dict: 状态信息
    """
    return asyncio.run(_check_ocr_status_async(assignment_id))


async def _check_ocr_status_async(assignment_id: str):
    """异步检查 OCR 状态"""
    async with get_celery_session() as db:
        result = await db.execute(
            select(Assignment).where(Assignment.id == UUID(assignment_id))
        )
        assignment = result.scalar_one_or_none()
        
        if not assignment:
            return {"error": "Assignment 不存在"}
        
        return {
            "assignment_id": assignment_id,
            "status": assignment.status,
            "processing_status": assignment.processing_status,
            "error_message": assignment.error_message,
        }
