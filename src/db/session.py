"""
数据库会话管理

使用 SQLAlchemy 2.0 异步引擎 + AsyncSession。

设计原则：
- 单例引擎：全局共享一个引擎实例，避免重复创建连接池
- 连接池管理：统一配置连接池参数
- 会话工厂：为 FastAPI 和 Celery 提供会话
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import settings

# ==================== 全局引擎（单例）====================
# 所有模块共享同一个引擎，避免重复创建连接池
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,      # 调试模式下打印 SQL
    pool_pre_ping=True,       # 连接前检测
    pool_size=10,             # 常驻连接数
    max_overflow=20,          # 峰值额外连接
    pool_recycle=3600,        # 1小时回收连接
)

# ==================== 会话工厂 ====================
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,   # commit 后对象不过期
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """
    FastAPI 依赖注入：获取数据库会话

    用法：
        @router.get("/")
        async def endpoint(db: AsyncSession = Depends(get_db)):
            ...

    自动处理 commit / rollback / close。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ==================== Celery 任务使用的会话工厂 ====================
def get_celery_session() -> AsyncSession:
    """
    Celery 任务中获取数据库会话（共享同一个引擎）
    
    用法：
        async with get_celery_session() as db:
            # 数据库操作
            await db.commit()
    
    注意：返回的是 session 对象，需要使用 async with 管理生命周期
    """
    return AsyncSessionLocal()


# ==================== 引擎生命周期管理 ====================
async def close_db_engine():
    """
    关闭数据库引擎（应用关闭时调用）
    
    用法：
        @app.on_event("shutdown")
        async def shutdown():
            await close_db_engine()
    """
    await engine.dispose()
