"""
Phase 1 重构验证测试

测试统一配置管理、数据库连接共享、错误隔离机制
"""

import pytest


def test_config_singleton():
    """测试配置单例模式"""
    from src.config import get_settings, settings
    
    # 多次获取应该是同一个实例
    config1 = get_settings()
    config2 = get_settings()
    config3 = settings
    
    assert config1 is config2
    assert config2 is config3
    assert id(config1) == id(config2) == id(config3)


def test_config_validation():
    """测试配置校验"""
    from src.config import settings
    
    # 配置应该有必需的字段
    assert hasattr(settings, 'database_url')
    assert hasattr(settings, 'redis_url')
    assert hasattr(settings, 'celery_max_retries')
    
    # 配置应该有校验方法
    assert hasattr(settings, 'validate_required_for_ocr')
    assert hasattr(settings, 'validate_required_for_ai')


def test_database_engine_shared():
    """测试数据库引擎共享"""
    from src.db.session import engine, get_celery_session
    
    # Celery session 应该使用同一个引擎
    celery_session = get_celery_session()
    
    # 验证引擎是同一个实例
    assert celery_session.bind is engine


def test_assignment_processing_status_field():
    """测试 Assignment 模型的 processing_status 字段"""
    from src.models.assignment import Assignment, AssignmentStatus
    
    # 创建 Assignment 实例
    assignment = Assignment(
        student_id="test_student",
        file_id="test_file_id",
        file_hash="test_hash",
        original_filename="test.jpg",
        file_size=1024,
        mime_type="image/jpeg",
        storage_url="file://test.jpg",
        status=AssignmentStatus.UPLOADED,
    )
    
    # 验证 processing_status 字段存在
    assert hasattr(assignment, 'processing_status')
    
    # 设置 processing_status
    assignment.processing_status = {
        "ocr": {"status": "done", "confidence": 0.95},
        "ai": {"status": "running"},
    }
    
    # 验证可以正常访问
    assert assignment.processing_status["ocr"]["status"] == "done"
    assert assignment.processing_status["ocr"]["confidence"] == 0.95
    assert assignment.processing_status["ai"]["status"] == "running"


def test_new_assignment_statuses():
    """测试新增的 Assignment 状态"""
    from src.models.assignment import AssignmentStatus
    
    # 验证新增的状态存在
    assert hasattr(AssignmentStatus, 'OCR_FAILED')
    assert hasattr(AssignmentStatus, 'AI_FAILED')
    
    # 验证状态值
    assert AssignmentStatus.OCR_FAILED == "ocr_failed"
    assert AssignmentStatus.AI_FAILED == "ai_failed"


def test_config_database_url_validation():
    """测试数据库 URL 自动转换"""
    from src.config import Settings
    
    # 测试 postgresql:// 自动转换为 postgresql+asyncpg://
    settings = Settings(database_url="postgresql://user:pass@localhost/db")
    assert settings.database_url.startswith("postgresql+asyncpg://")
    
    # 测试已经是 asyncpg 的不重复转换
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/db")
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.database_url.count("asyncpg") == 1


def test_config_max_file_size_bytes():
    """测试文件大小配置转换"""
    from src.config import Settings
    
    # 测试 MB 转 bytes
    settings = Settings(max_file_size_mb=20)
    assert settings.max_file_size_bytes == 20 * 1024 * 1024


def test_ocr_tasks_use_unified_config():
    """测试 OCR 任务使用统一配置"""
    import inspect
    from src.tasks import ocr_tasks
    
    # 读取源代码
    source = inspect.getsource(ocr_tasks)
    
    # 验证使用了统一配置
    assert "from src.config import settings" in source
    assert "settings.validate_required_for_ocr()" in source
    assert "settings.paddleocr_token" in source
    
    # 验证没有直接使用 os.getenv
    assert "os.getenv" not in source or "os.getenv" in source.split("from src.config import settings")[0]


def test_ai_tasks_use_unified_config():
    """测试 AI 任务使用统一配置"""
    import inspect
    from src.tasks import ai_tasks
    
    # 读取源代码
    source = inspect.getsource(ai_tasks)
    
    # 验证使用了统一配置
    assert "from src.config import settings" in source
    assert "settings.validate_required_for_ai()" in source
    assert "settings.doubao_seed_api_key" in source
    
    # 验证没有直接使用 os.getenv
    assert "os.getenv" not in source or "os.getenv" in source.split("from src.config import settings")[0]


def test_celery_app_use_unified_config():
    """测试 Celery 应用使用统一配置"""
    import inspect
    from src import celery_app
    
    # 读取源代码
    source = inspect.getsource(celery_app)
    
    # 验证使用了统一配置
    assert "from src.config import settings" in source
    assert "settings.redis_url" in source
    assert "settings.celery_task_soft_time_limit" in source
    assert "settings.celery_task_time_limit" in source


def test_error_isolation_in_ocr_tasks():
    """测试 OCR 任务的错误隔离"""
    import inspect
    from src.tasks import ocr_tasks
    
    # 读取源代码
    source = inspect.getsource(ocr_tasks)
    
    # 验证使用了 processing_status
    assert "processing_status" in source
    assert 'assignment.processing_status["ocr"]' in source
    
    # 验证使用了新状态
    assert "AssignmentStatus.OCR_FAILED" in source


def test_error_isolation_in_ai_tasks():
    """测试 AI 任务的错误隔离"""
    import inspect
    from src.tasks import ai_tasks
    
    # 读取源代码
    source = inspect.getsource(ai_tasks)
    
    # 验证使用了 processing_status
    assert "processing_status" in source
    assert 'assignment.processing_status["ai"]' in source
    
    # 验证使用了新状态
    assert "AssignmentStatus.AI_FAILED" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
