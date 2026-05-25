from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.ai_grading import (
    AIGradingResult,
    GradingResult,
    KnowledgeMappingResult,
    QualityFlags,
    StudentKnowledgeEventPayload,
)


def test_ai_grading_result_accepts_first_call_contract():
    result = AIGradingResult.model_validate(
        {
            "detected_subject": "physics",
            "detected_grade": "八年级",
            "support_status": "supported",
            "question_struct": {
                "subject": "physics",
                "grade": "八年级",
                "question_type": "multiple_choice",
                "stem": "下图几组器材中，能完成测定电池电动势和内电阻实验的是？",
                "options": {"A": "一只电流表...", "B": "一只电流表..."},
                "diagrams": ["U-I 图像"],
                "known_conditions": ["需要测定电池电动势和内电阻"],
                "target": "选择能完成实验的器材",
            },
            "solution": {
                "answer": "B",
                "reasoning_summary": "需要能改变外电路电阻并测量电流变化。",
                "solution_steps": [
                    {
                        "step": 1,
                        "title": "明确实验目的",
                        "content": "该实验需要得到多组电流和路端电压关系。",
                        "used_knowledge": ["闭合电路欧姆定律"],
                    }
                ],
            },
            "grading": {
                "student_answer": "A",
                "correct_answer": "B",
                "is_correct": False,
                "mistake_type": "concept_error",
                "mistake_reason": "把实验器材选择逻辑判断错了。",
                "feedback": "你把电压表与电流表的测量作用混淆了。",
            },
            "knowledge_candidates": [
                {
                    "raw_name": "测定电源电动势和内阻",
                    "confidence": 0.91,
                }
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
    )

    assert result.grading.score is None
    assert result.question_struct.question_type == "multiple_choice"
    assert result.support_status == "supported"
    assert result.review_required is False


def test_quality_gate_does_not_depend_on_model_confidence_number():
    flags = QualityFlags.model_validate(
        {
            "missing_student_answer": True,
        }
    )

    assert flags.missing_student_answer is True
    assert flags.low_payload_size is False
    assert not hasattr(flags, "vision_confidence")


def test_grading_score_must_stay_inside_bounds():
    with pytest.raises(ValidationError):
        GradingResult.model_validate(
            {
                "student_answer": "A",
                "correct_answer": "B",
                "is_correct": True,
                "score": 1.2,
                "feedback": "越界分数不应该被接受",
            }
        )


def test_mapping_result_only_accepts_fixed_taxonomy_or_unmapped():
    mapped = KnowledgeMappingResult.model_validate(
        {
            "primary_knowledge_points": [
                {
                    "taxonomy_id": "physics_g8_electricity_ohms_law",
                    "taxonomy_name": "闭合电路欧姆定律",
                    "role": "primary",
                    "confidence": 0.88,
                    "match_method": "ai_mapped",
                }
            ],
            "unmapped_candidates": [],
            "overall_confidence": 0.88,
        }
    )

    assert mapped.primary_knowledge_points[0].taxonomy_id == "physics_g8_electricity_ohms_law"

    unmapped = KnowledgeMappingResult.model_validate(
        {
            "primary_knowledge_points": [],
            "unmapped_candidates": ["某个教材外说法"],
            "overall_confidence": 0.2,
        }
    )

    assert unmapped.unmapped_candidates[0] == "某个教材外说法"


def test_student_knowledge_event_payload_keeps_time_dimension():
    created_at = datetime(2026, 5, 25, 9, 30, tzinfo=timezone.utc)

    event = StudentKnowledgeEventPayload.model_validate(
        {
            "student_id": "student_001",
            "assignment_id": "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
            "question_id": "81c53a0f-fc75-45b0-b11e-5cfbcbf4ed8e",
            "knowledge_point_id": "physics_g8_electricity_ohms_law",
            "result": "wrong",
            "grading_status": "ai_final",
            "score": 0,
            "max_score": 1,
            "mistake_type": "concept_error",
            "created_at": created_at,
        }
    )

    assert event.created_at == created_at
    assert event.result == "wrong"
    assert event.grading_status == "ai_final"


def test_uncertain_subject_is_support_status_not_event_result():
    result = AIGradingResult.model_validate(
        {
            "detected_subject": "unknown",
            "detected_grade": "未知",
            "support_status": "uncertain",
            "question_struct": {
                "subject": "未知",
                "grade": "未知",
                "question_type": "open_ended",
                "stem": "图片内容不完整，无法判断题目。",
                "target": "无法识别",
            },
            "solution": {
                "answer": "[无法解题]",
                "reasoning_summary": "图片信息不足，无法可靠解题。",
                "solution_steps": [
                    {
                        "step": 1,
                        "title": "无法识别题目",
                        "content": "题干和学生作答区域不完整。",
                        "used_knowledge": [],
                    }
                ],
            },
            "grading": {
                "student_answer": None,
                "correct_answer": "[无法解题]",
                "is_correct": None,
                "score": None,
                "mistake_type": "no_answer",
                "feedback": "请重新拍摄更清晰完整的题目。",
            },
            "knowledge_candidates": [],
            "quality_flags": {
                "missing_student_answer": True,
            },
            "review_required": True,
            "review_reasons": ["subject_uncertain"],
        }
    )

    assert result.support_status == "uncertain"

    with pytest.raises(ValidationError):
        StudentKnowledgeEventPayload.model_validate(
            {
                "student_id": "student_001",
                "assignment_id": "94ee850e-6562-4c9b-ac7c-15cdd1383c4e",
                "question_id": "81c53a0f-fc75-45b0-b11e-5cfbcbf4ed8e",
                "knowledge_point_id": "physics_g8_electricity_ohms_law",
                "result": "uncertain",
                "score": 0,
                "max_score": 1,
                "created_at": datetime(2026, 5, 25, 9, 30, tzinfo=timezone.utc),
            }
        )
