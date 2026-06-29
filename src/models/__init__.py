"""数据模型模块"""
from src.models.base import Base
from src.models.assignment import Assignment, AssignmentStatus
from src.models.ocr_task import OCRTask, OCRTaskStatus
from src.models.question import Question
from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile
# AI grading models (Codex-owned; parallel to Kiro's knowledge/profile tables)
from src.models.grading import (
    AssignmentAnalysis,
    GradingResult,
    GradingTaxonomy,
    QuestionKnowledgePoint,
    StudentKnowledgeEvent,
    StudentKnowledgePoint,
)

from src.models.knowledge_graph import CurriculumKPRelation, StudentReport

__all__ = [
    "CurriculumKPRelation",
    "StudentReport",
    "Base",
    "Assignment",
    "AssignmentStatus",
    "OCRTask",
    "OCRTaskStatus",
    "Question",
    "KnowledgePoint",
    "StudentKnowledgeProfile",
    "AssignmentAnalysis",
    "GradingResult",
    "GradingTaxonomy",
    "QuestionKnowledgePoint",
    "StudentKnowledgeEvent",
    "StudentKnowledgePoint",
]
