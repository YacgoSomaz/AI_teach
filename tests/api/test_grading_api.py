from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.api.grading import dispute_ai_grading, start_ai_grading
from src.main import create_app
from src.models.assignment import Assignment, AssignmentStatus
from src.models.grading import AssignmentAnalysis, GradingResult


def test_grading_routes_are_registered():
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/api/grading/{assignment_id}/start" in paths
    assert "/api/grading/{assignment_id}" in paths
    assert "/api/grading/{assignment_id}/dispute" in paths


def assignment(status=AssignmentStatus.UPLOADED):
    item = Assignment(
        student_id="student_001",
        file_id="file_001",
        file_hash="hash_001",
        original_filename="q.jpg",
        file_size=100,
        mime_type="image/jpeg",
        storage_url="file://q.jpg",
        status=status,
    )
    item.id = "94ee850e-6562-4c9b-ac7c-15cdd1383c4e"
    item.created_at = datetime(2026, 5, 25, tzinfo=timezone.utc)
    item.updated_at = datetime(2026, 5, 25, tzinfo=timezone.utc)
    return item


@pytest.mark.asyncio
async def test_start_rejects_duplicate_running_task(mocker):
    db = AsyncMock()
    item = assignment(AssignmentStatus.AI_RUNNING)
    item.processing_status = {"grading": {"status": "running"}}
    assignment_result = MagicMock()
    assignment_result.scalar_one_or_none.return_value = item
    analysis_result = MagicMock()
    analysis_result.scalar_one_or_none.return_value = None
    grading_result = MagicMock()
    grading_result.scalar_one_or_none.return_value = None
    db.execute.side_effect = [assignment_result, analysis_result, grading_result]
    delay = mocker.patch("src.api.grading.process_ai_grading.delay")

    with pytest.raises(HTTPException) as exc:
        await start_ai_grading(
            "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
            current_student_id="student_001",
            db=db,
        )

    assert exc.value.status_code == 409
    delay.assert_not_called()


@pytest.mark.asyncio
async def test_start_allows_ai_done_without_grading_records(mocker):
    db = AsyncMock()
    item = assignment(AssignmentStatus.AI_DONE)
    item.processing_status = {"upload": {"status": "received"}}
    assignment_result = MagicMock()
    assignment_result.scalar_one_or_none.return_value = item
    analysis_result = MagicMock()
    analysis_result.scalar_one_or_none.return_value = None
    grading_result = MagicMock()
    grading_result.scalar_one_or_none.return_value = None
    db.execute.side_effect = [assignment_result, analysis_result, grading_result]
    delay = mocker.patch("src.api.grading.process_ai_grading.delay")

    result = await start_ai_grading(
        "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
        current_student_id="student_001",
        db=db,
    )

    assert result.success is True
    assert result.status == "queued"
    delay.assert_called_once_with(str(item.id))


@pytest.mark.asyncio
async def test_start_rejects_ai_done_with_grading_records(mocker):
    db = AsyncMock()
    item = assignment(AssignmentStatus.AI_DONE)
    assignment_result = MagicMock()
    assignment_result.scalar_one_or_none.return_value = item
    analysis_result = MagicMock()
    analysis_result.scalar_one_or_none.return_value = AssignmentAnalysis(
        assignment_id="94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
        student_id="student_001",
        detected_subject="physics",
        detected_grade="八年级",
        question_struct={"question_type": "multiple_choice"},
        support_status="supported",
    )
    grading_result = MagicMock()
    grading_result.scalar_one_or_none.return_value = GradingResult(
        assignment_id="94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
        student_id="student_001",
        correct_answer="A",
        score=Decimal("1"),
        max_score=Decimal("1"),
    )
    db.execute.side_effect = [assignment_result, analysis_result, grading_result]
    delay = mocker.patch("src.api.grading.process_ai_grading.delay")

    with pytest.raises(HTTPException) as exc:
        await start_ai_grading(
            "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
            current_student_id="student_001",
            db=db,
        )

    assert exc.value.status_code == 409
    delay.assert_not_called()


@pytest.mark.asyncio
async def test_dispute_rejects_non_ai_final_status(mocker):
    db = AsyncMock()
    assignment_result = MagicMock()
    assignment_result.scalar_one_or_none.return_value = assignment()
    grading_result = MagicMock()
    grading_result.scalar_one_or_none.return_value = GradingResult(
        assignment_id="94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
        student_id="student_001",
        correct_answer="A",
        score=Decimal("0"),
        max_score=Decimal("1"),
        status="disputed",
    )
    db.execute.side_effect = [assignment_result, grading_result]
    rebuild = mocker.patch("src.api.grading.rebuild_student_knowledge_point")

    with pytest.raises(HTTPException) as exc:
        await dispute_ai_grading(
            "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
            current_student_id="student_001",
            db=db,
        )

    assert exc.value.status_code == 409
    rebuild.assert_not_called()
