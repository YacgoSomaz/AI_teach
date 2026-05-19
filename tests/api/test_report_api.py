"""家长报告 API 测试"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from src.db.session import get_db
from src.main import create_app
from src.services.report_service import KnowledgePointDetail, LearningReport, SubjectSummary

STUDENT_ID = "stu_parent_001"
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


def _empty_report(student_id: str = STUDENT_ID) -> LearningReport:
    return LearningReport(
        student_id=student_id,
        generated_at="2026-05-19T00:00:00",
        total_knowledge_points=0,
        overall_mastery=0.0,
        weak_count=0,
        medium_count=0,
        strong_count=0,
    )


def _report_with_data() -> LearningReport:
    return LearningReport(
        student_id=STUDENT_ID,
        generated_at="2026-05-19T10:00:00",
        total_knowledge_points=3,
        overall_mastery=0.5,
        weak_count=1,
        medium_count=1,
        strong_count=1,
        subjects=[
            SubjectSummary(
                subject="数学", total=3,
                weak_count=1, medium_count=1, strong_count=1,
                average_mastery=0.5, average_error_rate=0.3,
            )
        ],
        top_weak_points=[
            KnowledgePointDetail(
                knowledge_point_id="kp-001",
                knowledge_point_name="三角函数",
                subject="数学", grade="八年级",
                mastery_score=0.2, mastery_level="weak",
                appear_count=5, error_count=4, error_rate=0.8,
                review_priority="high", last_reviewed_at=None,
            )
        ],
        top_strong_points=[],
    )


class TestGetParentReport:
    """GET /api/reports/parent/{student_id}"""

    def test_returns_200_with_matching_header(self, client):
        with patch("src.api.report.ReportService") as mock_cls:
            svc = AsyncMock()
            mock_cls.return_value = svc
            svc.generate_report.return_value = _empty_report()
            resp = client.get(
                f"/api/reports/parent/{STUDENT_ID}",
                headers={"X-Student-Id": STUDENT_ID},
            )
        assert resp.status_code == 200
        assert resp.json()["student_id"] == STUDENT_ID

    def test_idor_returns_404(self, client):
        resp = client.get(
            f"/api/reports/parent/{OTHER_ID}",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 404

    def test_response_contains_required_fields(self, client):
        with patch("src.api.report.ReportService") as mock_cls:
            svc = AsyncMock()
            mock_cls.return_value = svc
            svc.generate_report.return_value = _empty_report()
            resp = client.get(
                f"/api/reports/parent/{STUDENT_ID}",
                headers={"X-Student-Id": STUDENT_ID},
            )
        data = resp.json()
        for field in ("overall_mastery", "weak_count", "subjects", "top_weak_points"):
            assert field in data

    def test_excludes_internal_fields(self, client):
        """家长报告不暴露 medium_count / strong_count 等内部分级数据"""
        with patch("src.api.report.ReportService") as mock_cls:
            svc = AsyncMock()
            mock_cls.return_value = svc
            svc.generate_report.return_value = _empty_report()
            resp = client.get(
                f"/api/reports/parent/{STUDENT_ID}",
                headers={"X-Student-Id": STUDENT_ID},
            )
        data = resp.json()
        assert "medium_count" not in data
        assert "strong_count" not in data

    def test_weak_points_simplified(self, client):
        """薄弱知识点只包含名称、学科、掌握度，不暴露错误率等细节"""
        with patch("src.api.report.ReportService") as mock_cls:
            svc = AsyncMock()
            mock_cls.return_value = svc
            svc.generate_report.return_value = _report_with_data()
            resp = client.get(
                f"/api/reports/parent/{STUDENT_ID}",
                headers={"X-Student-Id": STUDENT_ID},
            )
        wp = resp.json()["top_weak_points"][0]
        assert wp["knowledge_point_name"] == "三角函数"
        assert wp["mastery_score"] == pytest.approx(0.2)
        assert "error_rate" not in wp
        assert "appear_count" not in wp

    def test_default_top_n_is_three(self, client):
        with patch("src.api.report.ReportService") as mock_cls:
            svc = AsyncMock()
            mock_cls.return_value = svc
            svc.generate_report.return_value = _empty_report()
            client.get(
                f"/api/reports/parent/{STUDENT_ID}",
                headers={"X-Student-Id": STUDENT_ID},
            )
        svc.generate_report.assert_called_once_with(student_id=STUDENT_ID, top_n=3)
