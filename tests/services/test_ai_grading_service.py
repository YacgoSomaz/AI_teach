import pytest

from src.schemas.ai_grading import AIGradingResult, KnowledgeMappingResult
from src.services.ai_grading_service import (
    AIGradingService,
    ImagePreflightError,
    derive_event_result,
    should_write_mastery_event,
)


def valid_call1_payload(**overrides):
    payload = {
        "detected_subject": "physics",
        "detected_grade": "八年级",
        "support_status": "supported",
        "question_struct": {
            "subject": "physics",
            "grade": "八年级",
            "question_type": "multiple_choice",
            "stem": "下列关于串联电路电流规律的说法正确的是？",
            "options": {"A": "各处电流相等", "B": "电压处处相等"},
            "diagrams": [],
            "known_conditions": ["串联电路"],
            "target": "判断电流规律",
        },
        "solution": {
            "answer": "A",
            "solution_steps": [
                {
                    "step": 1,
                    "title": "应用串联电路规律",
                    "content": "串联电路中电流处处相等。",
                    "used_knowledge": ["串联电路电流规律"],
                }
            ],
            "reasoning_summary": "串联电路电流处处相等。",
        },
        "grading": {
            "student_answer": "B",
            "correct_answer": "A",
            "is_correct": False,
            "score": None,
            "mistake_type": "concept_error",
            "mistake_reason": "把串联电流规律判断错了。",
            "feedback": "注意串联电路只有电流处处相等。",
        },
        "knowledge_candidates": [
            {"raw_name": "串联电路电流规律", "confidence": 0.96}
        ],
        "quality_flags": {
            "low_payload_size": False,
            "missing_student_answer": False,
            "answer_solution_mismatch": False,
            "incomplete_schema": False,
        },
        "review_required": False,
        "review_reasons": [],
    }
    payload.update(overrides)
    return payload


def valid_mapping_payload(**overrides):
    payload = {
        "primary_knowledge_points": [
            {
                "taxonomy_id": "physics_g8_electricity_series_current",
                "taxonomy_name": "串联电路电流规律",
                "confidence": 0.94,
                "match_method": "exact",
                "role": "primary",
            }
        ],
        "unmapped_candidates": [],
        "overall_confidence": 0.94,
    }
    payload.update(overrides)
    return payload


class FakeAIClient:
    def __init__(self, call1_payload=None, call2_payload=None):
        self.call1_payload = call1_payload or valid_call1_payload()
        self.call2_payload = call2_payload or valid_mapping_payload()
        self.calls = []

    async def complete_json(self, *, messages, model, timeout):
        self.calls.append({"messages": messages, "model": model, "timeout": timeout})
        if len(self.calls) == 1:
            return self.call1_payload
        return self.call2_payload


def jpeg_bytes(width=320, height=240, payload_size=90_000):
    header = bytearray(b"\xff\xd8")
    header += b"\xff\xc0\x00\x11\x08"
    header += height.to_bytes(2, "big")
    header += width.to_bytes(2, "big")
    header += b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    header += b"\xff\xd9"
    return bytes(header).ljust(payload_size, b"0")


def test_preflight_rejects_small_image_before_ai_call():
    service = AIGradingService(ai_client=FakeAIClient())

    with pytest.raises(ImagePreflightError) as exc:
        service.preflight_image(b"tiny", "image/jpeg")

    assert exc.value.reason == "image_too_small"


def test_preflight_rejects_non_image_payload():
    service = AIGradingService(ai_client=FakeAIClient())

    with pytest.raises(ImagePreflightError) as exc:
        service.preflight_image(jpeg_bytes(), "application/pdf")

    assert exc.value.reason == "unsupported_file_type"


def test_post_ai_checks_mark_review_required_without_trusting_model_flag():
    result = AIGradingResult.model_validate(
        valid_call1_payload(
            solution={**valid_call1_payload()["solution"], "answer": "A"},
            grading={**valid_call1_payload()["grading"], "correct_answer": "B"},
        )
    )
    service = AIGradingService(ai_client=FakeAIClient())

    checked = service.apply_post_ai_checks(result)

    assert checked.review_required is True
    assert "answer_solution_mismatch" in checked.review_reasons
    assert checked.quality_flags.answer_solution_mismatch is True


@pytest.mark.asyncio
async def test_unsupported_subject_skips_taxonomy_mapping():
    client = FakeAIClient(
        call1_payload=valid_call1_payload(
            detected_subject="math",
            support_status="unsupported_subject",
            knowledge_candidates=[{"raw_name": "完全平方公式", "confidence": 0.95}],
        )
    )
    service = AIGradingService(ai_client=client)

    result = await service.analyze_image_bytes(
        image_bytes=jpeg_bytes(),
        mime_type="image/jpeg",
        taxonomy_entries=[{"id": "x", "name": "x", "chapter": "x", "aliases": []}],
    )

    assert result.mapping_result is None
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_supported_result_runs_call2_and_validates_mapping():
    client = FakeAIClient()
    service = AIGradingService(ai_client=client)

    result = await service.analyze_image_bytes(
        image_bytes=jpeg_bytes(),
        mime_type="image/jpeg",
        taxonomy_entries=[
            {
                "id": "physics_g8_electricity_series_current",
                "name": "串联电路电流规律",
                "chapter": "电学",
                "aliases": ["串联电路电流规律"],
                "is_active": True,
            }
        ],
    )

    assert isinstance(result.call1_result, AIGradingResult)
    assert isinstance(result.mapping_result, KnowledgeMappingResult)
    assert len(client.calls) == 2


def test_no_student_answer_does_not_write_mastery_event():
    result = AIGradingResult.model_validate(
        valid_call1_payload(
            grading={
                "student_answer": None,
                "correct_answer": "A",
                "is_correct": None,
                "score": None,
                "mistake_type": "no_answer",
                "mistake_reason": None,
                "feedback": None,
            }
        )
    )

    assert should_write_mastery_event(result) is False


def test_event_result_uses_partial_for_fractional_scores():
    assert derive_event_result(is_correct=True, score=None) == "correct"
    assert derive_event_result(is_correct=False, score=None) == "wrong"
    assert derive_event_result(is_correct=False, score=0.6) == "partial"
