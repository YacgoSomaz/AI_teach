from sqlalchemy import Boolean, ForeignKeyConstraint, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from src.models import Base
from src.models.grading import (
    AssignmentAnalysis,
    GradingResult,
    GradingTaxonomy,
    QuestionKnowledgePoint,
    StudentKnowledgeEvent,
    StudentKnowledgePoint,
)


def columns(model) -> dict:
    return model.__table__.c


def unique_constraints(model) -> set[tuple[str, ...]]:
    return {
        tuple(constraint.columns.keys())
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def foreign_key_targets(model) -> set[str]:
    targets = set()
    for constraint in model.__table__.constraints:
        if isinstance(constraint, ForeignKeyConstraint):
            for element in constraint.elements:
                targets.add(f"{element.column.table.name}.{element.column.name}")
    return targets


def test_grading_models_are_registered_on_base_metadata():
    expected = {
        "grading_taxonomy",
        "assignment_analyses",
        "grading_results",
        "question_knowledge_points",
        "student_knowledge_events",
        "student_knowledge_points",
    }

    assert expected <= set(Base.metadata.tables)


def test_grading_taxonomy_uses_string_ids_and_self_parent():
    table = GradingTaxonomy.__table__
    cols = columns(GradingTaxonomy)

    assert table.name == "grading_taxonomy"
    assert isinstance(cols["id"].type, String)
    assert cols["id"].primary_key
    assert isinstance(cols["aliases"].type, JSONB)
    assert cols["aliases"].nullable is False
    assert "grading_taxonomy.id" in foreign_key_targets(GradingTaxonomy)


def test_assignment_analysis_stores_call1_output_without_touching_kiro_questions():
    cols = columns(AssignmentAnalysis)

    assert AssignmentAnalysis.__table__.name == "assignment_analyses"
    assert "assignments.id" in foreign_key_targets(AssignmentAnalysis)
    assert isinstance(cols["question_struct"].type, JSONB)
    assert isinstance(cols["review_reasons"].type, JSONB)
    assert isinstance(cols["quality_flags"].type, JSONB)
    assert isinstance(cols["call1_raw"].type, JSONB)


def test_grading_result_has_idempotency_and_status_fields():
    cols = columns(GradingResult)

    assert GradingResult.__table__.name == "grading_results"
    assert ("assignment_id",) in unique_constraints(GradingResult)
    assert "assignments.id" in foreign_key_targets(GradingResult)
    assert isinstance(cols["correct_answer"].type, Text)
    assert isinstance(cols["student_answer"].type, Text)
    assert isinstance(cols["is_correct"].type, Boolean)
    assert isinstance(cols["score"].type, Numeric)
    assert isinstance(cols["max_score"].type, Numeric)
    assert cols["status"].default.arg == "ai_final"


def test_question_knowledge_points_reference_grading_taxonomy():
    cols = columns(QuestionKnowledgePoint)

    assert QuestionKnowledgePoint.__table__.name == "question_knowledge_points"
    assert "assignments.id" in foreign_key_targets(QuestionKnowledgePoint)
    assert "grading_taxonomy.id" in foreign_key_targets(QuestionKnowledgePoint)
    assert isinstance(cols["confidence"].type, Numeric)
    assert cols["role"].default.arg == "primary"


def test_student_knowledge_events_are_fact_source_with_idempotency():
    cols = columns(StudentKnowledgeEvent)

    assert StudentKnowledgeEvent.__table__.name == "student_knowledge_events"
    assert ("assignment_id", "knowledge_point_id") in unique_constraints(StudentKnowledgeEvent)
    assert "assignments.id" in foreign_key_targets(StudentKnowledgeEvent)
    assert "grading_taxonomy.id" in foreign_key_targets(StudentKnowledgeEvent)
    assert isinstance(cols["excluded_from_mastery"].type, Boolean)
    assert cols["grading_status"].default.arg == "ai_final"


def test_student_knowledge_points_are_derived_aggregate():
    cols = columns(StudentKnowledgePoint)

    assert StudentKnowledgePoint.__table__.name == "student_knowledge_points"
    assert ("student_id", "knowledge_point_id") in unique_constraints(StudentKnowledgePoint)
    assert "grading_taxonomy.id" in foreign_key_targets(StudentKnowledgePoint)
    assert isinstance(cols["mastery"].type, Numeric)
    assert cols["attempts"].default.arg == 0
    assert cols["correct_count"].default.arg == 0
