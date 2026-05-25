from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.ai_grading import (
    AIGradingResult,
    GradingResult,
    KnowledgeMappingResult,
    QualityGate,
    StudentKnowledgeEventPayload,
)


def test_ai_grading_result_accepts_first_call_contract():
    result = AIGradingResult.model_validate(
        {
            "question": {
                "subject": "物理",
                "grade": "八年级",
                "question_type": "choice",
                "stem": "下图几组器材中，能完成测定电池电动势和内电阻实验的是？",
                "options": {"A": "一只电流表...", "B": "一只电流表..."},
                "student_answer": "A",
                "correct_answer": "B",
            },
            "solution": {
                "answer": "B",
                "summary": "需要能改变外电路电阻并测量电流变化。",
                "steps": [
                    {
                        "index": 1,
                        "title": "明确实验目的",
                        "content": "该实验需要得到多组电流和路端电压关系。",
                        "used_knowledge": ["闭合电路欧姆定律"],
                    }
                ],
            },
            "grading": {
                "is_correct": False,
                "score": 0,
                "max_score": 1,
                "mistake_type": "concept_error",
                "feedback": "你把电压表与电流表的测量作用混淆了。",
            },
            "raw_knowledge_candidates": [
                {
                    "name": "测定电源电动势和内阻",
                    "reason": "题目要求判断实验器材是否能完成该实验。",
                }
            ],
            "quality_gate": {
                "review_required": False,
                "quality_flags": [],
                "evidence": ["识别到题干、选项和学生答案"],
            },
        }
    )

    assert result.grading.score == 0
    assert result.question.question_type == "choice"
    assert result.quality_gate.review_required is False


def test_quality_gate_does_not_depend_on_model_confidence_number():
    gate = QualityGate.model_validate(
        {
            "review_required": True,
            "quality_flags": ["missing_student_answer", "low_text_clarity"],
            "evidence": ["未识别到学生作答区域"],
        }
    )

    assert gate.review_required is True
    assert "missing_student_answer" in gate.quality_flags
    assert not hasattr(gate, "vision_confidence")


def test_grading_score_must_stay_inside_bounds():
    with pytest.raises(ValidationError):
        GradingResult.model_validate(
            {
                "is_correct": True,
                "score": 2,
                "max_score": 1,
                "feedback": "越界分数不应该被接受",
            }
        )


def test_mapping_result_only_accepts_fixed_taxonomy_or_unmapped():
    mapped = KnowledgeMappingResult.model_validate(
        {
            "mapped_points": [
                {
                    "taxonomy_id": "physics_g8_electricity_ohms_law",
                    "name": "闭合电路欧姆定律",
                    "role": "primary",
                    "confidence": 0.88,
                }
            ],
            "unmapped_candidates": [],
        }
    )

    assert mapped.mapped_points[0].taxonomy_id == "physics_g8_electricity_ohms_law"

    unmapped = KnowledgeMappingResult.model_validate(
        {
            "mapped_points": [],
            "unmapped_candidates": [
                {
                    "name": "某个教材外说法",
                    "reason": "taxonomy_missing_or_uncertain",
                }
            ],
        }
    )

    assert unmapped.unmapped_candidates[0].reason == "taxonomy_missing_or_uncertain"


def test_student_knowledge_event_payload_keeps_time_dimension():
    created_at = datetime(2026, 5, 25, 9, 30, tzinfo=timezone.utc)

    event = StudentKnowledgeEventPayload.model_validate(
        {
            "student_id": "student_001",
            "assignment_id": "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
            "question_id": "81c53a0f-fc75-45b0-b11e-5cfbcbf4ed8e",
            "knowledge_point_id": "physics_g8_electricity_ohms_law",
            "result": "wrong",
            "score": 0,
            "max_score": 1,
            "mistake_type": "concept_error",
            "created_at": created_at,
        }
    )

    assert event.created_at == created_at
    assert event.result == "wrong"
