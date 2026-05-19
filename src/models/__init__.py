"""数据模型模块"""
from src.models.base import Base
from src.models.assignment import Assignment, AssignmentStatus
from src.models.ocr_task import OCRTask, OCRTaskStatus
from src.models.question import Question
from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile

__all__ = [
    "Base",
    "Assignment",
    "AssignmentStatus",
    "OCRTask",
    "OCRTaskStatus",
    "Question",
    "KnowledgePoint",
    "StudentKnowledgeProfile",
]
