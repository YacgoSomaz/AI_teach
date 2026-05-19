"""
事件类型定义

定义系统中所有的事件类型。
"""

from typing import Dict, List, Optional

from pydantic import Field

from src.events.base import BaseEvent


class OCRCompletedEvent(BaseEvent):
    """
    OCR 完成事件
    
    当 OCR 任务成功完成时发布此事件。
    """
    
    assignment_id: str = Field(..., description="作业 ID")
    ocr_task_id: str = Field(..., description="OCR 任务 ID")
    confidence: float = Field(..., description="OCR 置信度")
    markdown: str = Field(..., description="OCR 结果（Markdown 格式）")
    raw_text: str = Field(default="", description="OCR 原始文本")
    images: Optional[Dict[str, str]] = Field(default=None, description="提取的图片")
    total_pages: int = Field(default=1, description="总页数")


class AIAnalysisCompletedEvent(BaseEvent):
    """
    AI 分析完成事件
    
    当 AI 分析任务成功完成时发布此事件。
    """
    
    assignment_id: str = Field(..., description="作业 ID")
    questions: List[Dict] = Field(..., description="分析出的题目列表")
    questions_count: int = Field(..., description="题目数量")


class QuestionCreatedEvent(BaseEvent):
    """
    题目创建事件
    
    当创建新题目时发布此事件。
    """
    
    question_id: str = Field(..., description="题目 ID")
    assignment_id: str = Field(..., description="作业 ID")
    student_id: str = Field(..., description="学生 ID")
    knowledge_points: List[str] = Field(..., description="知识点列表")
    question_type: str = Field(..., description="题目类型")
    difficulty: str = Field(..., description="难度")


class OCRFailedEvent(BaseEvent):
    """
    OCR 失败事件
    
    当 OCR 任务失败时发布此事件。
    """
    
    assignment_id: str = Field(..., description="作业 ID")
    error_message: str = Field(..., description="错误信息")
    retry_count: int = Field(..., description="重试次数")


class AIAnalysisFailedEvent(BaseEvent):
    """
    AI 分析失败事件
    
    当 AI 分析任务失败时发布此事件。
    """
    
    assignment_id: str = Field(..., description="作业 ID")
    error_message: str = Field(..., description="错误信息")
    retry_count: int = Field(..., description="重试次数")
