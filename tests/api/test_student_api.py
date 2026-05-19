"""
学生画像 API 测试

测试 student.py 的三个端点。
使用 FastAPI TestClient + app.dependency_overrides 覆盖 DB 依赖。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.db.session import get_db
from src.main import create_app

STUDENT_ID = "stu_test_001"
KP_ID_1 = "00000000-0000-0000-0000-000000000001"
KP_ID_2 = "00000000-0000-0000-0000-000000000002"


def _make_profile(kp_id: str, mastery: float, priority: str = "medium"):
    p = MagicMock()
    p.knowledge_point_id = uuid.UUID(kp_id)
    p.mastery_score = mastery
    p.review_priority = priority
    p.appear_count = 5
    p.error_count = 2
    p.last_reviewed_at = None
    return p


def _make_kp(kp_id: str, name: str = "知识点", subject: str = "数学", grade: str = "八年级"):
    kp = MagicMock()
    kp.id = uuid.UUID(kp_id)
    kp.name = name
    kp.subject = subject
    kp.grade = grade
    return kp


def _make_client_with_db(mock_db) -> TestClient:
    """创建 TestClient，将 get_db 依赖替换为 mock_db。"""
    app = create_app()

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


class TestGetStudentProfile:
    """GET /api/students/{student_id}/profile"""

    def test_returns_profile_for_valid_student(self):
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = [
            (_make_profile(KP_ID_1, 0.8), _make_kp(KP_ID_1, "一次函数")),
        ]
        mock_db.execute.return_value = result

        client = _make_client_with_db(mock_db)
        resp = client.get(
            f"/api/students/{STUDENT_ID}/profile",
            headers={"X-Student-Id": STUDENT_ID},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["student_id"] == STUDENT_ID
        assert data["total_knowledge_points"] == 1
        assert len(data["knowledge_points"]) == 1

    def test_idor_protection_returns_404_for_other_student(self):
        """访问他人数据返回 404，而非 403"""
        mock_db = AsyncMock()
        client = _make_client_with_db(mock_db)
        resp = client.get(
            "/api/students/other_student/profile",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 404

    def test_empty_profile_returns_zeros(self):
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        mock_db.execute.return_value = result

        client = _make_client_with_db(mock_db)
        resp = client.get(
            f"/api/students/{STUDENT_ID}/profile",
            headers={"X-Student-Id": STUDENT_ID},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_knowledge_points"] == 0
        assert data["overall_mastery"] == 0.0
        assert data["weak_count"] == 0

    def test_weak_count_excludes_strong_points(self):
        """掌握度 >= 0.6 的知识点不计入 weak_count"""
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = [
            (_make_profile(KP_ID_1, 0.3), _make_kp(KP_ID_1, "薄弱点")),
            (_make_profile(KP_ID_2, 0.9), _make_kp(KP_ID_2, "掌握点")),
        ]
        mock_db.execute.return_value = result

        client = _make_client_with_db(mock_db)
        resp = client.get(
            f"/api/students/{STUDENT_ID}/profile",
            headers={"X-Student-Id": STUDENT_ID},
        )

        assert resp.status_code == 200
        assert resp.json()["weak_count"] == 1

    def test_overall_mastery_is_average(self):
        """overall_mastery 为所有知识点掌握度均值"""
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = [
            (_make_profile(KP_ID_1, 0.4), _make_kp(KP_ID_1, "A")),
            (_make_profile(KP_ID_2, 0.8), _make_kp(KP_ID_2, "B")),
        ]
        mock_db.execute.return_value = result

        client = _make_client_with_db(mock_db)
        resp = client.get(
            f"/api/students/{STUDENT_ID}/profile",
            headers={"X-Student-Id": STUDENT_ID},
        )

        assert resp.status_code == 200
        assert abs(resp.json()["overall_mastery"] - 0.6) < 0.001


class TestGetWeakPoints:
    """GET /api/students/{student_id}/weak-points"""

    def test_idor_returns_404(self):
        mock_db = AsyncMock()
        client = _make_client_with_db(mock_db)
        resp = client.get(
            "/api/students/other_stu/weak-points",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 404

    def test_returns_paginated_response_fields(self):
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        list_result = MagicMock()
        list_result.all.return_value = []
        mock_db.execute.side_effect = [count_result, list_result]

        client = _make_client_with_db(mock_db)
        resp = client.get(
            f"/api/students/{STUDENT_ID}/weak-points",
            headers={"X-Student-Id": STUDENT_ID},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "items" in data


class TestGetStudentProgress:
    """GET /api/students/{student_id}/progress"""

    def test_idor_returns_404(self):
        mock_db = AsyncMock()
        client = _make_client_with_db(mock_db)
        resp = client.get(
            "/api/students/other_stu/progress",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 404

    def test_empty_profile_returns_zero_counts(self):
        mock_db = AsyncMock()

        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_result
        mock_db.execute.return_value = execute_result

        client = _make_client_with_db(mock_db)
        resp = client.get(
            f"/api/students/{STUDENT_ID}/progress",
            headers={"X-Student-Id": STUDENT_ID},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_knowledge_points"] == 0
        assert data["weak_count"] == 0
        assert data["strong_count"] == 0

    def test_priority_counts_present_in_response(self):
        mock_db = AsyncMock()

        p1 = MagicMock()
        p1.mastery_score = 0.2
        p1.review_priority = "high"
        p2 = MagicMock()
        p2.mastery_score = 0.8
        p2.review_priority = "low"

        scalars_result = MagicMock()
        scalars_result.all.return_value = [p1, p2]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_result
        mock_db.execute.return_value = execute_result

        client = _make_client_with_db(mock_db)
        resp = client.get(
            f"/api/students/{STUDENT_ID}/progress",
            headers={"X-Student-Id": STUDENT_ID},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["priority_high_count"] == 1
        assert data["priority_low_count"] == 1
        assert data["priority_medium_count"] == 0
