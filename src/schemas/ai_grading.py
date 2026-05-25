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
    "choice",
    "fill_blank",
    "calculation",
    "experiment",
    "short_answer",
    "open_ended",
]

MistakeType = Literal[
    "concept_error",
    "calculation_error",
    "graph_reading_error",
    "experiment_design_error",
    "careless_error",
    "missing_answer",
    "unknown",
]

KnowledgeRole = Literal["primary", "secondary", "prerequisite"]
KnowledgeEventResult = Literal["correct", "partial", "wrong", "uncertain"]


class StrictSchema(BaseModel):
    """Base schema that rejects undeclared model output fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class QuestionStruct(StrictSchema):
    subject: str = Field(min_length=1, max_length=32)
    grade: str = Field(min_length=1, max_length=32)
    question_type: QuestionType
    stem: str = Field(min_length=1)
    options: dict[str, str] = Field(default_factory=dict)
    student_answer: str | None = None
    correct_answer: str | None = None
    diagrams: list[str] = Field(default_factory=list)
    known_conditions: list[str] = Field(default_factory=list)
    target: str | None = None


class SolutionStep(StrictSchema):
    index: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1)
    used_knowledge: list[str] = Field(default_factory=list)


class SolutionResult(StrictSchema):
    answer: str | None = None
    summary: str = Field(min_length=1)
    steps: list[SolutionStep] = Field(min_length=1)


class GradingResult(StrictSchema):
    is_correct: bool | None = None
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    mistake_type: MistakeType = "unknown"
    feedback: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_score_bounds(self) -> "GradingResult":
        if self.score > self.max_score:
            raise ValueError("score must be less than or equal to max_score")
        return self


class KnowledgeCandidate(StrictSchema):
    name: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1)


class QualityGate(StrictSchema):
    review_required: bool
    quality_flags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class AIGradingResult(StrictSchema):
    """First AI call output: understand, solve, and grade one question."""

    question: QuestionStruct
    solution: SolutionResult
    grading: GradingResult
    raw_knowledge_candidates: list[KnowledgeCandidate] = Field(default_factory=list)
    quality_gate: QualityGate


class MappedKnowledgePoint(StrictSchema):
    taxonomy_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    role: KnowledgeRole
    confidence: float = Field(ge=0, le=1)


class UnmappedKnowledgeCandidate(StrictSchema):
    name: str = Field(min_length=1, max_length=128)
    reason: Literal["taxonomy_missing_or_uncertain", "ambiguous", "out_of_scope"]


class KnowledgeMappingResult(StrictSchema):
    """Second AI call output: map candidates to the fixed taxonomy."""

    mapped_points: list[MappedKnowledgePoint] = Field(default_factory=list)
    unmapped_candidates: list[UnmappedKnowledgeCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_mapping_or_unmapped_reason(self) -> "KnowledgeMappingResult":
        if not self.mapped_points and not self.unmapped_candidates:
            raise ValueError("mapping must contain mapped_points or unmapped_candidates")
        return self


class StudentKnowledgeEventPayload(StrictSchema):
    """Immutable fact used later to aggregate student mastery."""

    student_id: str = Field(min_length=1, max_length=64)
    assignment_id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    knowledge_point_id: str = Field(min_length=1, max_length=128)
    result: KnowledgeEventResult
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    mistake_type: MistakeType = "unknown"
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
