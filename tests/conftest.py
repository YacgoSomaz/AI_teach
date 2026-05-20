"""
全局测试配置

在所有测试模块导入之前，向 sys.modules 注入 src.config mock，
避免 pydantic-settings 在测试环境中因 .env 中存在 Settings 未声明的字段
而触发 ValidationError。

这是测试基础设施代码，不修改任何 Kiro 的源文件。
"""

import sys
from types import ModuleType
from unittest.mock import MagicMock

# ── 仅在 src.config 尚未被真实加载时才注入 mock ──────────────────────────────
if "src.config" not in sys.modules:
    # 先导入真实的 Settings 类（保留真实类，只 mock 实例）
    import os
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test_db")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    
    from src.config import Settings as _RealSettings
    
    # 创建 mock 实例（用于大部分测试）
    _mock_settings = MagicMock()
    _mock_settings.database_url = (
        "postgresql+asyncpg://test:test@localhost:5432/test_db"
    )
    _mock_settings.debug = False
    _mock_settings.redis_url = "redis://localhost:6379/0"
    _mock_settings.environment = "test"
    _mock_settings.doubao_seed_api_key = None
    _mock_settings.doubao_seed_model = "ep-test"
    _mock_settings.doubao_seed_base_url = "https://ark.cn-beijing.volces.com/api/v3"
    _mock_settings.paddleocr_token = None
    _mock_settings.skip_ocr = False
    _mock_settings.upload_dir = "uploads"
    _mock_settings.max_file_size_mb = 20
    _mock_settings.max_file_size_bytes = 20 * 1024 * 1024
    _mock_settings.celery_task_soft_time_limit = 300
    _mock_settings.celery_task_time_limit = 600
    _mock_settings.celery_max_retries = 3

    _mock_config = ModuleType("src.config")
    _mock_config.settings = _mock_settings  # type: ignore[attr-defined]
    _mock_config.get_settings = lambda: _mock_settings  # type: ignore[attr-defined]
    _mock_config.Settings = _RealSettings  # type: ignore[attr-defined] - 保留真实类

    sys.modules["src.config"] = _mock_config


# ── Pytest Fixtures ──────────────────────────────────────────────────────────

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from src.models.base import Base


@pytest_asyncio.fixture
async def async_session():
    """
    提供异步数据库会话用于测试
    
    每个测试使用独立的事务，测试结束后回滚
    """
    # 使用测试数据库 URL
    test_db_url = "postgresql+asyncpg://test:test@localhost:5432/test_db"
    
    # 创建测试引擎（每个测试独立）
    engine = create_async_engine(
        test_db_url,
        poolclass=NullPool,  # 测试时不使用连接池
        echo=False,
    )
    
    # 创建所有表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    # 创建会话工厂
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    # 创建会话
    async with async_session_factory() as session:
        yield session
        # 测试结束后回滚
        await session.rollback()
    
    # 清理引擎
    await engine.dispose()
