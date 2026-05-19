"""
事件系统

提供事件驱动架构支持，解耦任务链。
"""

from src.events.base import BaseEvent
from src.events.bus import EventBus, event_bus
from src.events.types import (
    AIAnalysisCompletedEvent,
    OCRCompletedEvent,
    QuestionCreatedEvent,
)

__all__ = [
    "BaseEvent",
    "EventBus",
    "event_bus",
    "OCRCompletedEvent",
    "AIAnalysisCompletedEvent",
    "QuestionCreatedEvent",
]
