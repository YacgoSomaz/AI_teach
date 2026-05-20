"""
统一配置管理

负责：
1. 从环境变量读取所有配置
2. 配置校验和默认值
3. 类型转换和格式化
4. 配置访问接口

设计原则：
- 单一数据源：所有配置从这里读取
- 启动时校验：缺少必需配置立即报错
- 类型安全：使用 Pydantic 校验
"""

import os
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用配置"""
    
    # ==================== 数据库配置 ====================
    database_url: str = Field(
        default="postgresql+asyncpg://user:password@localhost:5432/ai_review_system",
        description="数据库连接 URL",
    )
    
    # ==================== Redis 配置 ====================
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接 URL（Celery broker 和 backend）",
    )
    
    # ==================== OCR 配置 ====================
    paddleocr_token: Optional[str] = Field(
        default=None,
        description="PaddleOCR API Token",
    )
    
    skip_ocr: bool = Field(
        default=False,
        description="跳过 OCR，直接进入 AI 分析（实验功能）",
    )
    
    # ==================== AI 配置 ====================
    doubao_seed_api_key: Optional[str] = Field(
        default=None,
        description="豆包 Seed1.8 API Key",
    )
    
    doubao_seed_model: str = Field(
        default="ep-20260518173637-nhzdp",
        description="豆包 Seed1.8 模型 endpoint",
    )
    
    doubao_seed_base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3",
        description="豆包 Seed1.8 API Base URL",
    )
    
    # ==================== 文件存储配置 ====================
    upload_dir: str = Field(
        default="uploads",
        description="文件上传目录",
    )
    
    max_file_size_mb: int = Field(
        default=20,
        description="最大文件大小（MB）",
    )
    
    # ==================== Celery 配置 ====================
    celery_task_soft_time_limit: int = Field(
        default=300,
        description="Celery 任务软超时（秒）",
    )
    
    celery_task_time_limit: int = Field(
        default=600,
        description="Celery 任务硬超时（秒）",
    )
    
    celery_max_retries: int = Field(
        default=3,
        description="Celery 任务最大重试次数",
    )
    
    # ==================== 限流配置 ====================
    upload_rate_limit_requests: int = Field(
        default=10,
        description="上传限流：每窗口期每学生最多请求次数",
    )

    upload_rate_limit_window: int = Field(
        default=60,
        description="上传限流：滑动窗口时长（秒）",
    )

    # ==================== 应用配置 ====================
    environment: str = Field(
        default="development",
        description="运行环境：development / production",
    )

    debug: bool = Field(
        default=False,
        description="调试模式",
    )
    
    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """确保使用 asyncpg 驱动"""
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
    
    @property
    def max_file_size_bytes(self) -> int:
        """最大文件大小（字节）"""
        return self.max_file_size_mb * 1024 * 1024
    
    def validate_required_for_ocr(self) -> None:
        """校验 OCR 必需配置"""
        if not self.paddleocr_token:
            raise ValueError("PADDLEOCR_TOKEN 未配置，OCR 功能无法使用")
    
    def validate_required_for_ai(self) -> None:
        """校验 AI 必需配置"""
        if not self.doubao_seed_api_key:
            raise ValueError("DOUBAO_SEED_API_KEY 未配置，AI 分析功能无法使用")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # 忽略额外的配置字段


# 全局配置实例（单例）
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    获取配置实例（单例模式）
    
    Returns:
        Settings: 配置对象
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# 便捷访问
settings = get_settings()
