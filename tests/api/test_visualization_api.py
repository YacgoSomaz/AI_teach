"""可视化数据 API 测试"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.db.session import get_db
from src.main import create_app

STUDENT_ID = "stu_viz_001"
OTHER_ID = "stu_other_999"


@pytest.fixture
def app():
    _app = create_app()

    async def override_get_db():
        yield AsyncMock()

    _app.dependency_overrides[get_db] = override_get_db
    return _app


@pytest.fixture
def client(app):
    return TestClient(app)


def _make_profile(mastery: float = 0.6, subject: str = "数学", priority: str = "medium"):
    p = MagicMock()
    p.mastery_score = mastery
    p.review_priority = priority
    p.last_reviewed_at = None
    return p


def _make_kp(subject: str = "数学"):
    kp = MagicMock()
    kp.subject = subject
    return kp


class TestRadarEndpoint:
    """GET /api/visualization/student/{student_id}/radar"""

    def test_returns_200_with_labels_and_values(self, app):
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = [("数学", 0.8), ("物理", 0.5)]
        mock_db.execute.return_value = result

        async def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        client = TestClient(app)
        resp = client.get(
            f"/api/visualization/student/{STUDENT_ID}/radar",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "labels" in data
        assert "values" in data
        assert len(data["labels"]) == len(data["values"])

    def test_idor_returns_404(self, client):
        resp = client.get(
            f"/api/visualization/student/{OTHER_ID}/radar",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 404

    def test_empty_profile_returns_empty_arrays(self, app):
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        mock_db.execute.return_value = result

        async def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        client = TestClient(app)
        resp = client.get(
            f"/api/visualization/student/{STUDENT_ID}/radar",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["labels"] == []
        assert data["values"] == []

    def test_values_are_averages_per_subject(self, app):
        """同一学科多条记录，value 为平均掌握度。"""
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = [("数学", 0.6)]
        mock_db.execute.return_value = result

        async def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        client = TestClient(app)
        resp = client.get(
            f"/api/visualization/student/{STUDENT_ID}/radar",
            headers={"X-Student-Id": STUDENT_ID},
        )
        data = resp.json()
        assert data["labels"] == ["数学"]
        assert abs(data["values"][0] - 0.6) < 0.001


class TestHeatmapEndpoint:
    """GET /api/visualization/student/{student_id}/heatmap"""

    def test_returns_200_with_dates_and_counts(self, app):
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = [("2026-05-01", 3), ("2026-05-10", 5)]
        mock_db.execute.return_value = result

        async def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        client = TestClient(app)
        resp = client.get(
            f"/api/visualization/student/{STUDENT_ID}/heatmap",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "dates" in data
        assert "counts" in data
        assert len(data["dates"]) == len(data["counts"])

    def test_idor_returns_404(self, client):
        resp = client.get(
            f"/api/visualization/student/{OTHER_ID}/heatmap",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 404

    def test_empty_returns_empty_arrays(self, app):
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        mock_db.execute.return_value = result

        async def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        client = TestClient(app)
        resp = client.get(
            f"/api/visualization/student/{STUDENT_ID}/heatmap",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dates"] == []
        assert data["counts"] == []


class TestProgressLineEndpoint:
    """GET /api/visualization/student/{student_id}/progress-line"""

    def test_returns_200_with_dates_and_scores(self, app):
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = [("2026-05-01", 0.4), ("2026-05-10", 0.6)]
        mock_db.execute.return_value = result

        async def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        client = TestClient(app)
        resp = client.get(
            f"/api/visualization/student/{STUDENT_ID}/progress-line",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "dates" in data
        assert "mastery_scores" in data
        assert len(data["dates"]) == len(data["mastery_scores"])

    def test_idor_returns_404(self, client):
        resp = client.get(
            f"/api/visualization/student/{OTHER_ID}/progress-line",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 404

    def test_empty_returns_empty_arrays(self, app):
        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        mock_db.execute.return_value = result

        async def override():
            yield mock_db

        app.dependency_overrides[get_db] = override
        client = TestClient(app)
        resp = client.get(
            f"/api/visualization/student/{STUDENT_ID}/progress-line",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dates"] == []
        assert data["mastery_scores"] == []
