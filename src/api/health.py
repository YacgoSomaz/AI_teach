"""
健康检查 API

/health       — 进程存活探针（Liveness Probe），始终 200
/health/ready — 依赖就绪探针（Readiness Probe），检查 DB + Redis
"""

import redis.asyncio as aioredis
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from src.config import settings
from src.db.session import engine

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """进程存活检查：只要进程在运行就返回 200 ok。"""
    return HealthResponse(status="ok", service="ai-review-system")


@router.get("/health/ready", response_model=ReadyResponse)
async def readiness() -> ReadyResponse:
    """
    依赖就绪检查。

    - db: 对数据库执行 SELECT 1
    - redis: 对 Redis 执行 PING

    两者均正常时返回 HTTP 200 + status=ok。
    任意一项失败时返回 HTTP 503 + status=degraded，body 保留 checks 详情，
    供 K8s readiness probe 通过状态码直接判断（无需解析 body）。
    """
    from fastapi.responses import JSONResponse

    checks: dict[str, str] = {}
    overall = "ok"

    # ---- DB ----
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"
        overall = "degraded"

    # ---- Redis ----
    r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
    try:
        await r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"
        overall = "degraded"
    finally:
        await r.aclose()

    body = ReadyResponse(status=overall, checks=checks)
    status_code = 200 if overall == "ok" else 503
    return JSONResponse(content=body.model_dump(), status_code=status_code)
