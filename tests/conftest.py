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
    _mock_settings.upload_dir = "uploads"
    _mock_settings.max_file_size_mb = 20
    _mock_settings.max_file_size_bytes = 20 * 1024 * 1024
    _mock_settings.celery_task_soft_time_limit = 300
    _mock_settings.celery_task_time_limit = 600
    _mock_settings.celery_max_retries = 3

    _mock_config = ModuleType("src.config")
    _mock_config.settings = _mock_settings  # type: ignore[attr-defined]
    _mock_config.get_settings = lambda: _mock_settings  # type: ignore[attr-defined]
    _mock_config.Settings = MagicMock()  # type: ignore[attr-defined]

    sys.modules["src.config"] = _mock_config
