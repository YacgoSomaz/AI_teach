"""
复习任务 API 测试

测试 GET /api/review/plans/today 端点。
使用 FastAPI TestClient + app.dependency_overrides 覆盖 DB 依赖。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.db.session import get_db
from src.main import create_app
from src.services.review_plan_service import DailyReviewPlan, ReviewTaskItem

KP_ID = "00000000-0000-0000-0000-000000000001"
STUDENT_ID = "student_abc"


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


def _empty_plan(student_id: str = STUDENT_ID) -> DailyReviewPlan:
    return DailyReviewPlan(
        student_id=student_id, date="2026-05-19", tasks=[], total_minutes=0
    )


class TestGetTodayReviewPlan:
    """GET /api/review/plans/today"""

    def test_returns_200_with_student_id_header(self, client):
        with patch("src.api.review.ReviewPlanService") as mock_cls:
            svc = AsyncMock()
            mock_cls.return_value = svc
            svc.generate_today_plan.return_value = _empty_plan()

            resp = client.get(
                "/api/review/plans/today",
                headers={"X-Student-Id": STUDENT_ID},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["student_id"] == STUDENT_ID
        assert data["tasks"] == []
        assert data["task_count"] == 0

    def test_empty_plan_returns_zero_minutes(self, client):
        with patch("src.api.review.ReviewPlanService") as mock_cls:
            svc = AsyncMock()
            mock_cls.return_value = svc
            svc.generate_today_plan.return_value = _empty_plan()

            resp = client.get(
                "/api/review/plans/today",
                headers={"X-Student-Id": STUDENT_ID},
            )

        assert resp.status_code == 200
        assert resp.json()["total_minutes"] == 0

    def test_max_tasks_validation_out_of_range(self, client):
        """max_tasks 超出合法范围（>20）时返回 422"""
        resp = client.get(
            "/api/review/plans/today?max_tasks=99",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 422

    def test_task_fields_are_present(self, client):
        """返回的任务包含所有必需字段"""
        task = ReviewTaskItem(
            knowledge_point_id=KP_ID,
            knowledge_point_name="一次函数",
            subject="数学",
            grade="八年级",
            mastery_score=0.2,
            priority="high",
            reason="掌握度仅 20%，需要重点强化；从未复习",
            recommended_count=5,
            estimated_minutes=25,
        )
        plan = DailyReviewPlan(
            student_id=STUDENT_ID, date="2026-05-19", tasks=[task], total_minutes=25
        )

        with patch("src.api.review.ReviewPlanService") as mock_cls:
            svc = AsyncMock()
            mock_cls.return_value = svc
            svc.generate_today_plan.return_value = plan

            resp = client.get(
                "/api/review/plans/today",
                headers={"X-Student-Id": STUDENT_ID},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["task_count"] == 1
        assert data["total_minutes"] == 25
        t = data["tasks"][0]
        assert t["knowledge_point_id"] == KP_ID
        assert t["knowledge_point_name"] == "一次函数"
        assert t["priority"] == "high"
        assert t["recommended_count"] == 5
        assert t["estimated_minutes"] == 25

    def test_max_tasks_param_passed_to_service(self, client):
        """max_tasks 参数正确传递给 service"""
        with patch("src.api.review.ReviewPlanService") as mock_cls:
            svc = AsyncMock()
            mock_cls.return_value = svc
            svc.generate_today_plan.return_value = _empty_plan()

            resp = client.get(
                "/api/review/plans/today?max_tasks=3",
                headers={"X-Student-Id": STUDENT_ID},
            )

        assert resp.status_code == 200
        svc.generate_today_plan.assert_called_once_with(
            student_id=STUDENT_ID,
            max_tasks=3,
        )

    def test_default_student_id_is_used_without_header(self, client):
        """不传 X-Student-Id 时使用默认值 test_student"""
        with patch("src.api.review.ReviewPlanService") as mock_cls:
            svc = AsyncMock()
            mock_cls.return_value = svc
            svc.generate_today_plan.return_value = _empty_plan("test_student")

            resp = client.get("/api/review/plans/today")

        assert resp.status_code == 200
        svc.generate_today_plan.assert_called_once_with(
            student_id="test_student",
            max_tasks=5,
        )
