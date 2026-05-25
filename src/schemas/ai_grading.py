"""Contracts for the AI grading pipeline.

These models define the two AI boundaries for the first MVP:
1. multimodal question understanding, solution, and grading
2. taxonomy-constrained knowledge-point mapping

Student mastery should be updated from immutable knowledge events, not directly
from a single model response.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


QuestionType = Literal[
    "multiple_choice",
    "fill_blank",
    "calculation",
    "experiment",
    "open_ended",
]

MistakeType = Literal[
    "correct",
    "concept_error",
    "calculation_error",
    "graph_reading_error",
    "experiment_design_error",
    "formula_error",
    "no_answer",
    "partial",
]

KnowledgeRole = Literal["primary", "secondary"]
MatchMethod = Literal["exact", "alias", "ai_mapped"]
KnowledgeEventResult = Literal["correct", "partial", "wrong"]
SupportStatus = Literal[
    "supported",
    "unsupported_subject",
    "unsupported_grade",
    "uncertain",
]
GradingStatus = Literal["ai_final", "disputed", "corrected", "excluded"]


class StrictSchema(BaseModel):
    """Base schema that rejects undeclared model output fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class QuestionStruct(StrictSchema):
    subject: str = Field(min_length=1, max_length=32)
    grade: str = Field(min_length=1, max_length=32)
    question_type: QuestionType
    stem: str = Field(min_length=1)
    options: dict[str, str] | None = None
    diagrams: list[str] = Field(default_factory=list)
    known_conditions: list[str] = Field(default_factory=list)
    target: str = Field(min_length=1)


class SolutionStep(StrictSchema):
    step: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1)
    used_knowledge: list[str] = Field(default_factory=list)


class SolutionResult(StrictSchema):
    answer: str = Field(min_length=1)
    solution_steps: list[SolutionStep] = Field(min_length=1)
    reasoning_summary: str = Field(min_length=1)


class GradingResult(StrictSchema):
    student_answer: str | None = None
    correct_answer: str = Field(min_length=1)
    is_correct: bool | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    mistake_type: MistakeType | None = None
    mistake_reason: str | None = None
    feedback: str | None = None


class KnowledgeCandidate(StrictSchema):
    raw_name: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0, le=1)


class QualityFlags(StrictSchema):
    low_payload_size: bool = False
    missing_student_answer: bool = False
    answer_solution_mismatch: bool = False
    incomplete_schema: bool = False


class AIGradingResult(StrictSchema):
    """First AI call output: understand, solve, and grade one question."""

    detected_subject: str = Field(min_length=1, max_length=32)
    detected_grade: str = Field(min_length=1, max_length=32)
    support_status: SupportStatus
    question_struct: QuestionStruct
    solution: SolutionResult
    grading: GradingResult
    knowledge_candidates: list[KnowledgeCandidate] = Field(
        default_factory=list,
        max_length=5,
    )
    quality_flags: QualityFlags = Field(default_factory=QualityFlags)
    review_required: bool
    review_reasons: list[str] = Field(default_factory=list)


class MappedKnowledgePoint(StrictSchema):
    taxonomy_id: str = Field(min_length=1, max_length=128)
    taxonomy_name: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0, le=1)
    match_method: MatchMethod
    role: KnowledgeRole


class KnowledgeMappingResult(StrictSchema):
    """Second AI call output: map candidates to the fixed taxonomy."""

    primary_knowledge_points: list[MappedKnowledgePoint] = Field(
        default_factory=list,
        max_length=3,
    )
    unmapped_candidates: list[str] = Field(default_factory=list)
    overall_confidence: float = Field(ge=0, le=1)


class StudentKnowledgeEventPayload(StrictSchema):
    """Immutable fact used later to aggregate student mastery."""

    student_id: str = Field(min_length=1, max_length=64)
    assignment_id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    knowledge_point_id: str = Field(min_length=1, max_length=128)
    result: KnowledgeEventResult
    grading_status: GradingStatus = "ai_final"
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    mistake_type: MistakeType | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_score_bounds(self) -> "StudentKnowledgeEventPayload":
        if self.score > self.max_score:
            raise ValueError("score must be less than or equal to max_score")
        return self

    @field_validator("created_at")
    @classmethod
    def require_time_dimension(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include timezone information")
        return value
