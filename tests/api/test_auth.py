"""
身份校验行为测试

覆盖：
- 缺少 X-Student-Id Header 返回 401
- 上传接口使用 Header 里的学生 ID
- 学生 ID 不匹配仍返回 404（IDOR 防护）
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.deps import get_current_student_id
from src.api.rate_limit import upload_rate_limit
from src.db.session import get_db
from src.main import create_app

STUDENT_ID = "stu_auth_001"


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


class TestMissingStudentIdHeader:
    """所有需要身份的端点，缺少 X-Student-Id 时返回 401。"""

    def test_student_profile_returns_401(self, client):
        resp = client.get(f"/api/students/{STUDENT_ID}/profile")
        assert resp.status_code == 401

    def test_weak_points_returns_401(self, client):
        resp = client.get(f"/api/students/{STUDENT_ID}/weak-points")
        assert resp.status_code == 401

    def test_progress_returns_401(self, client):
        resp = client.get(f"/api/students/{STUDENT_ID}/progress")
        assert resp.status_code == 401

    def test_review_tasks_returns_401(self, client):
        resp = client.get(f"/api/students/{STUDENT_ID}/review-tasks")
        assert resp.status_code == 401

    def test_student_report_returns_401(self, client):
        resp = client.get(f"/api/reports/student/{STUDENT_ID}")
        assert resp.status_code == 401

    def test_parent_report_returns_401(self, client):
        resp = client.get(f"/api/reports/parent/{STUDENT_ID}")
        assert resp.status_code == 401

    def test_export_kp_returns_401(self, client):
        resp = client.get(f"/api/export/student/{STUDENT_ID}/knowledge-points")
        assert resp.status_code == 401

    def test_export_questions_returns_401(self, client):
        resp = client.get(f"/api/export/student/{STUDENT_ID}/questions")
        assert resp.status_code == 401

    def test_radar_returns_401(self, client):
        resp = client.get(f"/api/visualization/student/{STUDENT_ID}/radar")
        assert resp.status_code == 401

    def test_heatmap_returns_401(self, client):
        resp = client.get(f"/api/visualization/student/{STUDENT_ID}/heatmap")
        assert resp.status_code == 401

    def test_progress_line_returns_401(self, client):
        resp = client.get(f"/api/visualization/student/{STUDENT_ID}/progress-line")
        assert resp.status_code == 401

    def test_upload_returns_401(self, client):
        resp = client.post(
            "/api/upload",
            files={"file": ("test.jpg", b"fake-image-data", "image/jpeg")},
        )
        assert resp.status_code == 401

    def test_401_body_contains_message(self, client):
        resp = client.get(f"/api/students/{STUDENT_ID}/profile")
        assert "detail" in resp.json()

    def test_empty_string_header_returns_401(self, client):
        resp = client.get(
            f"/api/students/{STUDENT_ID}/profile",
            headers={"X-Student-Id": ""},
        )
        assert resp.status_code == 401

    def test_whitespace_only_header_returns_401(self, client):
        resp = client.get(
            f"/api/students/{STUDENT_ID}/profile",
            headers={"X-Student-Id": "   "},
        )
        assert resp.status_code == 401


class TestHeaderStripping:
    """X-Student-Id 前后空格应被 strip，不污染 student_id 数据。"""

    def test_padded_header_passes_auth_and_uses_stripped_value(self, client):
        """' stu_001 ' 通过鉴权（不返回 401），且 strip 后作为 'stu_001' 用于 IDOR 校验。

        路径用 other_stu 触发 IDOR → 返回 404 而非 401，
        证明 header 已被 strip 成有效 ID 并进入所有权校验阶段。
        """
        resp = client.get(
            "/api/students/other_stu/profile",
            headers={"X-Student-Id": " stu_001 "},
        )
        assert resp.status_code == 404


class TestOwnershipStillEnforced:
    """加了 X-Student-Id Header 但与路径不匹配，仍返回 404。"""

    def test_student_profile_idor(self, client):
        resp = client.get(
            f"/api/students/other_stu/profile",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 404

    def test_review_tasks_idor(self, client):
        resp = client.get(
            "/api/students/other_stu/review-tasks",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 404

    def test_export_idor(self, client):
        resp = client.get(
            "/api/export/student/other_stu/knowledge-points",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 404


class TestAssignmentStatusIDOR:
    """GET /api/assignments/{id} — H1 所有权校验。"""

    ASSIGNMENT_ID = "00000000-0000-0000-0000-000000000099"

    def _mock_assignment(self, student_id: str) -> MagicMock:
        a = MagicMock()
        a.id = self.ASSIGNMENT_ID
        a.student_id = student_id
        a.status = "uploaded"
        a.error_message = None
        a.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        a.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return a

    def test_missing_header_returns_401(self, client):
        """缺少 X-Student-Id → 401，鉴权在所有权校验之前。"""
        resp = client.get(f"/api/assignments/{self.ASSIGNMENT_ID}")
        assert resp.status_code == 401

    def test_wrong_student_returns_404(self, app):
        """Header 与 assignment.student_id 不一致 → 404（不泄露 403）。"""
        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._mock_assignment("owner_stu")
        mock_db.execute = AsyncMock(return_value=result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        resp = TestClient(app).get(
            f"/api/assignments/{self.ASSIGNMENT_ID}",
            headers={"X-Student-Id": "other_stu"},
        )
        assert resp.status_code == 404

    def test_matching_student_returns_200(self, app):
        """Header 与 assignment.student_id 一致 → 200，返回 assignment 数据。"""
        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._mock_assignment(STUDENT_ID)
        mock_db.execute = AsyncMock(return_value=result)

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        resp = TestClient(app).get(
            f"/api/assignments/{self.ASSIGNMENT_ID}",
            headers={"X-Student-Id": STUDENT_ID},
        )
        assert resp.status_code == 200
        assert resp.json()["assignment_id"] == self.ASSIGNMENT_ID


class TestUploadUsesHeaderStudentId:
    """上传接口使用 Header 提供的学生 ID 创建 Assignment。"""

    def test_upload_creates_assignment_with_header_student_id(self, app):
        mock_db = AsyncMock()
        hash_result = MagicMock()
        hash_result.fetchall.return_value = []

        async def fake_refresh(obj):
            obj.id = "00000000-0000-0000-0000-000000000001"
            obj.status = "uploaded"

        mock_db.execute.return_value = hash_result
        mock_db.refresh.side_effect = fake_refresh

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        # 绕过限流，保留 Header → student_id 的提取逻辑
        app.dependency_overrides[upload_rate_limit] = get_current_student_id

        mock_file_result = MagicMock()
        mock_file_result.file_id = "file_abc"
        mock_file_result.file_hash = "hash_abc"
        mock_file_result.original_filename = "test.jpg"
        mock_file_result.file_size = 100
        mock_file_result.mime_type = "image/jpeg"
        mock_file_result.storage_url = "file://test.jpg"
        mock_file_result.is_duplicate = False

        with patch("src.api.upload.FileService") as mock_svc_cls, \
             patch("src.api.upload.LocalFileStorage"), \
             patch("src.tasks.ocr_tasks.process_ocr") as mock_ocr:

            mock_svc_cls.return_value.upload.return_value = mock_file_result
            mock_ocr.delay = MagicMock()

            client = TestClient(app)
            resp = client.post(
                "/api/upload",
                files={"file": ("test.jpg", b"fake-image-data", "image/jpeg")},
                headers={"X-Student-Id": STUDENT_ID},
            )

        assert resp.status_code == 200
        # 验证 db.add 被调用，且 Assignment 的 student_id 来自 Header
        assert mock_db.add.called
        assignment_arg = mock_db.add.call_args[0][0]
        assert assignment_arg.student_id == STUDENT_ID
