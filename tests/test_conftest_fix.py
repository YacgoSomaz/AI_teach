"""
测试 conftest.py 修复是否正确

验证 Settings 类可以正常实例化
"""

import pytest


def test_settings_class_is_real():
    """测试 Settings 类是真实的类，不是 MagicMock"""
    from src.config import Settings
    from unittest.mock import MagicMock
    
    # Settings 应该是一个真实的类，不是 MagicMock
    assert not isinstance(Settings, type(MagicMock()))
    
    # 应该可以实例化
    settings = Settings(
        database_url="postgresql+asyncpg://test:test@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
    )
    
    # 应该有正确的字段
    assert settings.database_url == "postgresql+asyncpg://test:test@localhost:5432/test"
    assert settings.redis_url == "redis://localhost:6379/0"
    
    print("✅ Settings 类可以正常实例化")


def test_settings_instance_is_mocked():
    """测试 settings 实例是 mock 的（用于大部分测试）"""
    from src.config import settings
    
    # settings 实例应该是 mock
    assert settings.database_url == "postgresql+asyncpg://test:test@localhost:5432/test_db"
    assert settings.environment == "test"
    
    print("✅ settings 实例是 mock 的")


def test_get_settings_returns_mock():
    """测试 get_settings() 返回 mock 实例"""
    from src.config import get_settings
    
    settings = get_settings()
    
    # 应该返回 mock 实例
    assert settings.database_url == "postgresql+asyncpg://test:test@localhost:5432/test_db"
    assert settings.environment == "test"
    
    print("✅ get_settings() 返回 mock 实例")


if __name__ == "__main__":
    print("运行 conftest 修复测试...")
    test_settings_class_is_real()
    test_settings_instance_is_mocked()
    test_get_settings_returns_mock()
    print("\n✅ 所有测试通过！")
