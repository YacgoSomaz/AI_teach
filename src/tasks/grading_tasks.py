"""Celery task wrapper for the AI grading MVP pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from celery import Task
from sqlalchemy import select

from src.celery_app import app
from src.config import settings
from src.db.session import get_celery_session
from src.models.assignment import Assignment, AssignmentStatus
from src.services.ai_grading_service import (
    AIGradingService,
    ImagePreflightError,
    create_default_grading_ai_client,
)


class AIGradingTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        print(f"AI 批改任务失败: {task_id}, 错误: {exc}")


@app.task(base=AIGradingTask, bind=True, max_retries=settings.celery_max_retries)
def process_ai_grading(self, assignment_id: str):
    """Run AI grading for one uploaded assignment."""

    return asyncio.run(_process_ai_grading_async(self, assignment_id))


async def _process_ai_grading_async(task, assignment_id: str):
    assignment = None
    async with get_celery_session() as db:
        try:
            result = await db.execute(
                select(Assignment).where(Assignment.id == UUID(assignment_id))
            )
            assignment = result.scalar_one_or_none()
            if assignment is None:
                raise ValueError(f"Assignment {assignment_id} 不存在")

            assignment.status = AssignmentStatus.AI_RUNNING
            assignment.processing_status = {
                **(assignment.processing_status or {}),
                "grading": {"status": "running"},
            }
            await db.commit()

            image_bytes, mime_type = read_assignment_image(assignment)
            service = AIGradingService(ai_client=create_default_grading_ai_client())
            pipeline_result = await service.analyze_and_persist(
                db=db,
                assignment_id=str(assignment.id),
                student_id=assignment.student_id,
                image_bytes=image_bytes,
                mime_type=mime_type,
            )

            assignment.status = AssignmentStatus.AI_DONE
            assignment.processing_status = {
                **(assignment.processing_status or {}),
                "grading": {
                    "status": "done",
                    "support_status": pipeline_result.call1_result.support_status,
                    "review_required": pipeline_result.call1_result.review_required,
                    "mapped_count": (
                        len(pipeline_result.mapping_result.primary_knowledge_points)
                        if pipeline_result.mapping_result
                        else 0
                    ),
                },
            }
            await db.commit()
            return {
                "success": True,
                "assignment_id": assignment_id,
                "support_status": pipeline_result.call1_result.support_status,
                "review_required": pipeline_result.call1_result.review_required,
            }

        except ImagePreflightError as exc:
            if assignment is not None:
                assignment.status = AssignmentStatus.MANUAL_REQUIRED
                assignment.processing_status = {
                    **(assignment.processing_status or {}),
                    "grading": {"status": "rejected", "reason": exc.reason},
                }
                assignment.error_message = str(exc)
                await db.commit()
            return {
                "success": False,
                "assignment_id": assignment_id,
                "reason": exc.reason,
                "message": str(exc),
            }

        except Exception as exc:
            if assignment is not None:
                assignment.status = AssignmentStatus.AI_FAILED
                assignment.processing_status = {
                    **(assignment.processing_status or {}),
                    "grading": {
                        "status": "failed",
                        "error": str(exc),
                        "retry_count": task.request.retries,
                    },
                }
                assignment.retry_count += 1
                await db.commit()

            if task.request.retries < task.max_retries:
                raise task.retry(exc=exc, countdown=120)
            raise


def read_assignment_image(assignment) -> tuple[bytes, str]:
    """Load the local uploaded image for a grading task."""

    storage_url = assignment.storage_url or ""
    local_path = storage_url.removeprefix("file://")
    path = Path(local_path)
    if not path.is_file():
        raise FileNotFoundError(f"作业图片不存在: {local_path}")
    return path.read_bytes(), assignment.mime_type or "image/jpeg"
