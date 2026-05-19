"""
事件总线

基于 Celery 实现的事件总线，用于解耦任务链。

设计原则：
- 发布者不知道订阅者的存在
- 订阅者通过事件类型注册
- 异步处理，不阻塞发布者
"""

import logging
from typing import Callable, Dict, List, Type

from src.events.base import BaseEvent

logger = logging.getLogger(__name__)


class EventBus:
    """
    事件总线
    
    用法：
        # 订阅事件
        @event_bus.subscribe(OCRCompletedEvent)
        def handle_ocr_completed(event: OCRCompletedEvent):
            # 处理事件
            pass
        
        # 发布事件
        event = OCRCompletedEvent(assignment_id="123", ...)
        event_bus.publish(event)
    """
    
    def __init__(self):
        # 事件类型 -> 处理器列表
        self._handlers: Dict[str, List[Callable]] = {}
    
    def subscribe(self, event_type: Type[BaseEvent]):
        """
        订阅事件（装饰器）
        
        Args:
            event_type: 事件类型
        
        Returns:
            装饰器函数
        
        Example:
            @event_bus.subscribe(OCRCompletedEvent)
            def handle_ocr_completed(event: OCRCompletedEvent):
                pass
        """
        def decorator(handler: Callable):
            event_type_name = event_type.__name__
            
            if event_type_name not in self._handlers:
                self._handlers[event_type_name] = []
            
            self._handlers[event_type_name].append(handler)
            logger.info(f"Registered handler {handler.__name__} for event {event_type_name}")
            
            return handler
        
        return decorator
    
    def publish(self, event: BaseEvent):
        """
        发布事件
        
        Args:
            event: 事件对象
        
        Note:
            事件会异步分发给所有订阅者（通过 Celery 任务）
        """
        event_type_name = event.__class__.__name__
        handlers = self._handlers.get(event_type_name, [])
        
        if not handlers:
            logger.warning(f"No handlers registered for event {event_type_name}")
            return
        
        logger.info(f"Publishing event {event_type_name} (ID: {event.event_id}) to {len(handlers)} handlers")
        
        # 异步调用所有处理器
        for handler in handlers:
            try:
                # 如果处理器是 Celery 任务，使用 delay 异步调用
                if hasattr(handler, 'delay'):
                    handler.delay(event.model_dump())
                else:
                    # 否则直接调用（同步）
                    handler(event)
            except Exception as e:
                logger.error(f"Error calling handler {handler.__name__} for event {event_type_name}: {e}")
    
    def get_handlers(self, event_type: Type[BaseEvent]) -> List[Callable]:
        """
        获取事件的所有处理器
        
        Args:
            event_type: 事件类型
        
        Returns:
            处理器列表
        """
        event_type_name = event_type.__name__
        return self._handlers.get(event_type_name, [])
    
    def clear_handlers(self, event_type: Type[BaseEvent] = None):
        """
        清除处理器（用于测试）
        
        Args:
            event_type: 事件类型，如果为 None 则清除所有
        """
        if event_type is None:
            self._handlers.clear()
        else:
            event_type_name = event_type.__name__
            if event_type_name in self._handlers:
                del self._handlers[event_type_name]


# 全局事件总线实例（单例）
event_bus = EventBus()
