from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.assignment import AssignmentStatus
from src.services.ai_grading_service import ImagePreflightError
from src.tasks.grading_tasks import (
    _process_ai_grading_async,
    read_assignment_image,
    read_assignment_image_from_values,
)


class Assignment:
    def __init__(self, storage_url, mime_type="image/jpeg"):
        self.storage_url = storage_url
        self.mime_type = mime_type


def test_read_assignment_image_supports_file_url(tmp_path: Path):
    image_path = tmp_path / "question.jpg"
    image_path.write_bytes(b"image-bytes")

    image_bytes, mime_type = read_assignment_image(
        Assignment(f"file://{image_path}", "image/jpeg")
    )

    assert image_bytes == b"image-bytes"
    assert mime_type == "image/jpeg"


def test_read_assignment_image_supports_plain_local_path(tmp_path: Path):
    image_path = tmp_path / "question.jpg"
    image_path.write_bytes(b"image-bytes")

    image_bytes, mime_type = read_assignment_image(
        Assignment(str(image_path), "image/jpeg")
    )

    assert image_bytes == b"image-bytes"
    assert mime_type == "image/jpeg"


def test_read_assignment_image_from_cached_values(tmp_path: Path):
    image_path = tmp_path / "question.jpg"
    image_path.write_bytes(b"image-bytes")

    image_bytes, mime_type = read_assignment_image_from_values(
        f"file://{image_path}",
        "image/jpeg",
    )

    assert image_bytes == b"image-bytes"
    assert mime_type == "image/jpeg"


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, assignment):
        self.assignment = assignment
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement):
        return ScalarResult(self.assignment)

    async def commit(self):
        self.commits += 1


class FakeTask:
    max_retries = 3

    def __init__(self, retries=0):
        self.request = SimpleNamespace(retries=retries)
        self.retry = MagicMock(side_effect=RuntimeError("retry called"))


def make_assignment(tmp_path: Path):
    image_path = tmp_path / "question.jpg"
    image_path.write_bytes(b"image-bytes")
    return SimpleNamespace(
        id="94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
        student_id="student_001",
        storage_url=f"file://{image_path}",
        mime_type="image/jpeg",
        status=AssignmentStatus.UPLOADED,
        processing_status={"upload": {"status": "done"}},
        retry_count=0,
        error_message=None,
    )


@pytest.mark.asyncio
async def test_process_ai_grading_success_uses_cached_assignment_values(mocker, tmp_path):
    assignment = make_assignment(tmp_path)
    session = FakeSession(assignment)
    mocker.patch("src.tasks.grading_tasks.get_celery_session", return_value=session)
    mocker.patch(
        "src.tasks.grading_tasks.read_assignment_image_from_values",
        return_value=(b"cached-image", "image/jpeg"),
    )
    result = SimpleNamespace(
        call1_result=SimpleNamespace(support_status="supported", review_required=False),
        mapping_result=SimpleNamespace(primary_knowledge_points=[object()]),
    )
    service = mocker.MagicMock()
    service.analyze_and_persist = AsyncMock(return_value=result)
    mocker.patch("src.tasks.grading_tasks.AIGradingService", return_value=service)
    mocker.patch("src.tasks.grading_tasks.create_default_grading_ai_client")

    output = await _process_ai_grading_async(
        FakeTask(),
        "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
    )

    assert output["success"] is True
    assert assignment.status == AssignmentStatus.AI_DONE
    assert assignment.processing_status == {
        "grading": {
            "status": "done",
            "support_status": "supported",
            "review_required": False,
            "mapped_count": 1,
        }
    }


@pytest.mark.asyncio
async def test_process_ai_grading_preflight_failure_sets_manual_required(
    mocker,
    tmp_path,
):
    assignment = make_assignment(tmp_path)
    session = FakeSession(assignment)
    mocker.patch("src.tasks.grading_tasks.get_celery_session", return_value=session)
    mocker.patch(
        "src.tasks.grading_tasks.read_assignment_image_from_values",
        return_value=(b"small", "image/jpeg"),
    )
    service = mocker.MagicMock()
    service.analyze_and_persist = AsyncMock(
        side_effect=ImagePreflightError("image_too_small", "图片太小")
    )
    mocker.patch("src.tasks.grading_tasks.AIGradingService", return_value=service)
    mocker.patch("src.tasks.grading_tasks.create_default_grading_ai_client")

    output = await _process_ai_grading_async(
        FakeTask(),
        "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
    )

    assert output["success"] is False
    assert output["reason"] == "image_too_small"
    assert assignment.status == AssignmentStatus.MANUAL_REQUIRED


@pytest.mark.asyncio
async def test_process_ai_grading_retries_generic_failure(mocker, tmp_path):
    assignment = make_assignment(tmp_path)
    session = FakeSession(assignment)
    task = FakeTask(retries=0)
    mocker.patch("src.tasks.grading_tasks.get_celery_session", return_value=session)
    mocker.patch(
        "src.tasks.grading_tasks.read_assignment_image_from_values",
        return_value=(b"image", "image/jpeg"),
    )
    service = mocker.MagicMock()
    service.analyze_and_persist = AsyncMock(side_effect=RuntimeError("boom"))
    mocker.patch("src.tasks.grading_tasks.AIGradingService", return_value=service)
    mocker.patch("src.tasks.grading_tasks.create_default_grading_ai_client")

    with pytest.raises(RuntimeError, match="retry called"):
        await _process_ai_grading_async(
            task,
            "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
        )

    assert assignment.status == AssignmentStatus.AI_RUNNING
    assert assignment.processing_status == {
        "grading": {
            "status": "retrying",
            "error": "boom",
            "retry_count": 0,
        },
    }
    assert assignment.retry_count == 1
    task.retry.assert_called_once()


@pytest.mark.asyncio
async def test_process_ai_grading_marks_failed_after_final_retry(mocker, tmp_path):
    assignment = make_assignment(tmp_path)
    session = FakeSession(assignment)
    task = FakeTask(retries=3)
    mocker.patch("src.tasks.grading_tasks.get_celery_session", return_value=session)
    mocker.patch(
        "src.tasks.grading_tasks.read_assignment_image_from_values",
        return_value=(b"image", "image/jpeg"),
    )
    service = mocker.MagicMock()
    service.analyze_and_persist = AsyncMock(side_effect=RuntimeError("boom"))
    mocker.patch("src.tasks.grading_tasks.AIGradingService", return_value=service)
    mocker.patch("src.tasks.grading_tasks.create_default_grading_ai_client")

    with pytest.raises(RuntimeError, match="boom"):
        await _process_ai_grading_async(
            task,
            "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
        )

    assert assignment.status == AssignmentStatus.AI_FAILED
    assert assignment.processing_status == {
        "grading": {
            "status": "failed",
            "error": "boom",
            "retry_count": 3,
        },
    }
    assert assignment.retry_count == 1
    task.retry.assert_not_called()
