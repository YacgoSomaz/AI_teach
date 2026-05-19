"""
事件基类

所有事件都继承自 BaseEvent。
"""

from datetime import datetime
from typing import Any, Dict
from uuid import uuid4

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    """
    事件基类
    
    所有事件都应该继承这个类。
    """
    
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str = Field(default="")
    timestamp: datetime = Field(default_factory=datetime.now)
    payload: Dict[str, Any] = Field(default_factory=dict)
    
    def __init__(self, **data):
        super().__init__(**data)
        # 自动设置 event_type 为类名
        if not self.event_type:
            self.event_type = self.__class__.__name__
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
