"""
健康检查端点测试

/health       — 始终 200 ok
/health/ready — DB+Redis 均 ok → 200；任一失败 → 503 degraded
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from src.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


class TestLiveness:
    """/health — 进程存活，无外部依赖，始终 200。"""

    def test_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_body_status_ok(self, client):
        assert client.get("/health").json()["status"] == "ok"

    def test_body_service_name(self, client):
        assert client.get("/health").json()["service"] == "ai-review-system"


class TestReadiness:
    """/health/ready — 200 ok 或 503 degraded。"""

    def _mock_db_ok(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = conn
        return mock_engine

    def _mock_redis_ok(self):
        r = AsyncMock()
        r.ping = AsyncMock(return_value=True)
        r.aclose = AsyncMock()
        return r

    def test_both_ok_returns_200(self, client):
        mock_engine = self._mock_db_ok()
        mock_redis = self._mock_redis_ok()
        with patch("src.api.health.engine", mock_engine), \
             patch("src.api.health.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_redis
            resp = client.get("/health/ready")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["checks"]["db"] == "ok"
        assert data["checks"]["redis"] == "ok"

    def test_db_fail_returns_503(self, client):
        bad_conn = AsyncMock()
        bad_conn.__aenter__ = AsyncMock(side_effect=Exception("connection refused"))
        bad_conn.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = bad_conn

        mock_redis = self._mock_redis_ok()
        with patch("src.api.health.engine", mock_engine), \
             patch("src.api.health.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_redis
            resp = client.get("/health/ready")

        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert "error" in data["checks"]["db"]
        assert data["checks"]["redis"] == "ok"

    def test_redis_fail_returns_503(self, client):
        mock_engine = self._mock_db_ok()
        bad_redis = AsyncMock()
        bad_redis.ping = AsyncMock(side_effect=Exception("redis unavailable"))
        bad_redis.aclose = AsyncMock()

        with patch("src.api.health.engine", mock_engine), \
             patch("src.api.health.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = bad_redis
            resp = client.get("/health/ready")

        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["checks"]["db"] == "ok"
        assert "error" in data["checks"]["redis"]

    def test_both_fail_returns_503(self, client):
        bad_conn = AsyncMock()
        bad_conn.__aenter__ = AsyncMock(side_effect=Exception("db down"))
        bad_conn.__aexit__ = AsyncMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.connect.return_value = bad_conn

        bad_redis = AsyncMock()
        bad_redis.ping = AsyncMock(side_effect=Exception("redis down"))
        bad_redis.aclose = AsyncMock()

        with patch("src.api.health.engine", mock_engine), \
             patch("src.api.health.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = bad_redis
            resp = client.get("/health/ready")

        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert "error" in data["checks"]["db"]
        assert "error" in data["checks"]["redis"]

    def test_redis_aclose_called_even_on_ping_failure(self, client):
        """Redis 客户端在 ping 失败时仍必须关闭，防止连接泄露。"""
        mock_engine = self._mock_db_ok()
        bad_redis = AsyncMock()
        bad_redis.ping = AsyncMock(side_effect=Exception("timeout"))
        bad_redis.aclose = AsyncMock()

        with patch("src.api.health.engine", mock_engine), \
             patch("src.api.health.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = bad_redis
            client.get("/health/ready")

        bad_redis.aclose.assert_called_once()

    def test_redis_aclose_called_on_success(self, client):
        """Redis 客户端在成功时也必须关闭。"""
        mock_engine = self._mock_db_ok()
        mock_redis = self._mock_redis_ok()

        with patch("src.api.health.engine", mock_engine), \
             patch("src.api.health.aioredis") as mock_aioredis:
            mock_aioredis.from_url.return_value = mock_redis
            client.get("/health/ready")

        mock_redis.aclose.assert_called_once()
