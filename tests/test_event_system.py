"""
事件系统测试

测试事件发布、订阅、分发机制。
"""

import pytest

from src.events import (
    AIAnalysisCompletedEvent,
    BaseEvent,
    EventBus,
    OCRCompletedEvent,
    QuestionCreatedEvent,
)


def test_base_event_creation():
    """测试基础事件创建"""
    event = BaseEvent()
    
    assert event.event_id is not None
    assert event.event_type == "BaseEvent"
    assert event.timestamp is not None
    assert event.payload == {}


def test_ocr_completed_event():
    """测试 OCR 完成事件"""
    event = OCRCompletedEvent(
        assignment_id="test_assignment_001",
        ocr_task_id="test_ocr_001",
        confidence=0.95,
        markdown="## 测试",
        raw_text="测试文本",
    )
    
    assert event.assignment_id == "test_assignment_001"
    assert event.ocr_task_id == "test_ocr_001"
    assert event.confidence == 0.95
    assert event.event_type == "OCRCompletedEvent"


def test_ai_analysis_completed_event():
    """测试 AI 分析完成事件"""
    event = AIAnalysisCompletedEvent(
        assignment_id="test_assignment_001",
        questions=[
            {"question_text": "题目1", "knowledge_points": ["知识点1"]},
        ],
        questions_count=1,
    )
    
    assert event.assignment_id == "test_assignment_001"
    assert len(event.questions) == 1
    assert event.questions_count == 1


def test_question_created_event():
    """测试题目创建事件"""
    event = QuestionCreatedEvent(
        question_id="test_question_001",
        assignment_id="test_assignment_001",
        student_id="test_student_001",
        knowledge_points=["二次方程", "因式分解"],
        question_type="解答题",
        difficulty="medium",
    )
    
    assert event.question_id == "test_question_001"
    assert len(event.knowledge_points) == 2


def test_event_bus_subscribe():
    """测试事件订阅"""
    bus = EventBus()
    
    # 订阅事件
    @bus.subscribe(OCRCompletedEvent)
    def handle_ocr_completed(event: OCRCompletedEvent):
        pass
    
    # 验证处理器已注册
    handlers = bus.get_handlers(OCRCompletedEvent)
    assert len(handlers) == 1
    assert handlers[0] == handle_ocr_completed


def test_event_bus_publish():
    """测试事件发布"""
    bus = EventBus()
    
    # 用于记录处理器是否被调用
    called = []
    
    # 订阅事件
    @bus.subscribe(OCRCompletedEvent)
    def handle_ocr_completed(event: OCRCompletedEvent):
        called.append(event.assignment_id)
    
    # 发布事件
    event = OCRCompletedEvent(
        assignment_id="test_001",
        ocr_task_id="ocr_001",
        confidence=0.95,
        markdown="## 测试",
    )
    bus.publish(event)
    
    # 验证处理器被调用
    assert len(called) == 1
    assert called[0] == "test_001"


def test_event_bus_multiple_handlers():
    """测试多个处理器"""
    bus = EventBus()
    
    called = []
    
    # 订阅同一事件的多个处理器
    @bus.subscribe(OCRCompletedEvent)
    def handler1(event: OCRCompletedEvent):
        called.append("handler1")
    
    @bus.subscribe(OCRCompletedEvent)
    def handler2(event: OCRCompletedEvent):
        called.append("handler2")
    
    # 发布事件
    event = OCRCompletedEvent(
        assignment_id="test_001",
        ocr_task_id="ocr_001",
        confidence=0.95,
        markdown="## 测试",
    )
    bus.publish(event)
    
    # 验证所有处理器都被调用
    assert len(called) == 2
    assert "handler1" in called
    assert "handler2" in called


def test_event_bus_no_handlers():
    """测试没有处理器的情况"""
    bus = EventBus()
    
    # 发布事件（没有订阅者）
    event = OCRCompletedEvent(
        assignment_id="test_001",
        ocr_task_id="ocr_001",
        confidence=0.95,
        markdown="## 测试",
    )
    
    # 不应该抛出异常
    bus.publish(event)


def test_event_bus_clear_handlers():
    """测试清除处理器"""
    bus = EventBus()
    
    @bus.subscribe(OCRCompletedEvent)
    def handler(event: OCRCompletedEvent):
        pass
    
    # 验证处理器已注册
    assert len(bus.get_handlers(OCRCompletedEvent)) == 1
    
    # 清除处理器
    bus.clear_handlers(OCRCompletedEvent)
    
    # 验证处理器已清除
    assert len(bus.get_handlers(OCRCompletedEvent)) == 0


def test_event_serialization():
    """测试事件序列化"""
    event = OCRCompletedEvent(
        assignment_id="test_001",
        ocr_task_id="ocr_001",
        confidence=0.95,
        markdown="## 测试",
    )
    
    # 序列化为字典
    event_dict = event.model_dump()
    
    assert event_dict["assignment_id"] == "test_001"
    assert event_dict["event_type"] == "OCRCompletedEvent"
    assert "event_id" in event_dict
    assert "timestamp" in event_dict
    
    # 反序列化
    event2 = OCRCompletedEvent(**event_dict)
    assert event2.assignment_id == event.assignment_id
    assert event2.event_id == event.event_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
