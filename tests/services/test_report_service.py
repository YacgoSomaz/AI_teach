"""
学习报告生成服务测试

覆盖：纯函数 + mock DB 集成场景
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.report_service import (
    LearningReport,
    ReportService,
    classify_mastery,
    compute_error_rate,
    compute_overall_mastery,
)

KP_ID_1 = "00000000-0000-0000-0000-000000000001"
KP_ID_2 = "00000000-0000-0000-0000-000000000002"
KP_ID_3 = "00000000-0000-0000-0000-000000000003"


# ─── 纯函数测试 ──────────────────────────────────────────────────────────────


class TestClassifyMastery:
    def test_weak_below_04(self):
        assert classify_mastery(0.1) == "weak"
        assert classify_mastery(0.39) == "weak"

    def test_medium_between_04_and_07(self):
        assert classify_mastery(0.4) == "medium"
        assert classify_mastery(0.6) == "medium"

    def test_strong_at_or_above_07(self):
        assert classify_mastery(0.7) == "strong"
        assert classify_mastery(1.0) == "strong"

    def test_boundary_values(self):
        assert classify_mastery(0.0) == "weak"
        assert classify_mastery(0.4) == "medium"
        assert classify_mastery(0.7) == "strong"


class TestComputeErrorRate:
    def test_zero_appear_count_returns_zero(self):
        assert compute_error_rate(0, 0) == 0.0

    def test_all_wrong_returns_one(self):
        assert compute_error_rate(10, 10) == pytest.approx(1.0)

    def test_half_wrong(self):
        assert compute_error_rate(10, 5) == pytest.approx(0.5)

    def test_returns_rounded_to_4_decimals(self):
        rate = compute_error_rate(3, 2)
        assert rate == pytest.approx(0.6667, abs=0.0001)


class TestComputeOverallMastery:
    def test_empty_list_returns_zero(self):
        assert compute_overall_mastery([]) == 0.0

    def test_single_score(self):
        assert compute_overall_mastery([0.8]) == pytest.approx(0.8)

    def test_average_of_multiple(self):
        assert compute_overall_mastery([0.4, 0.6, 0.8]) == pytest.approx(0.6)

    def test_returns_rounded(self):
        result = compute_overall_mastery([1 / 3])
        assert len(str(result).split(".")[-1]) <= 4


# ─── 辅助函数 ────────────────────────────────────────────────────────────────


def _make_profile(kp_id: str, mastery_score: float, appear: int = 5, error: int = 2):
    p = MagicMock()
    p.knowledge_point_id = uuid.UUID(kp_id)
    p.mastery_score = mastery_score
    p.review_priority = "medium"
    p.last_reviewed_at = None
    p.appear_count = appear
    p.error_count = error
    return p


def _make_kp(kp_id: str, name: str, subject: str = "数学", grade: str = "八年级"):
    kp = MagicMock()
    kp.id = uuid.UUID(kp_id)
    kp.name = name
    kp.subject = subject
    kp.grade = grade
    return kp


# ─── 服务层测试 ──────────────────────────────────────────────────────────────


class TestReportService:
    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        return ReportService(db=mock_db)

    def _setup_db(self, mock_db, rows: list):
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_db.execute.return_value = mock_result

    @pytest.mark.asyncio
    async def test_empty_profile_returns_empty_report(self, service, mock_db):
        """无知识点时返回全零报告"""
        self._setup_db(mock_db, [])
        report = await service.generate_report("stu_1")

        assert isinstance(report, LearningReport)
        assert report.total_knowledge_points == 0
        assert report.overall_mastery == 0.0
        assert report.subjects == []
        assert report.top_weak_points == []
        assert report.top_strong_points == []

    @pytest.mark.asyncio
    async def test_overall_mastery_computed_correctly(self, service, mock_db):
        """overall_mastery 为所有知识点掌握度均值"""
        self._setup_db(mock_db, [
            (_make_profile(KP_ID_1, 0.4), _make_kp(KP_ID_1, "A")),
            (_make_profile(KP_ID_2, 0.8), _make_kp(KP_ID_2, "B")),
        ])
        report = await service.generate_report("stu_1")

        assert report.overall_mastery == pytest.approx(0.6)
        assert report.total_knowledge_points == 2

    @pytest.mark.asyncio
    async def test_mastery_level_counts_are_correct(self, service, mock_db):
        """weak / medium / strong 计数正确"""
        self._setup_db(mock_db, [
            (_make_profile(KP_ID_1, 0.2), _make_kp(KP_ID_1, "weak_kp")),
            (_make_profile(KP_ID_2, 0.5), _make_kp(KP_ID_2, "medium_kp")),
            (_make_profile(KP_ID_3, 0.9), _make_kp(KP_ID_3, "strong_kp")),
        ])
        report = await service.generate_report("stu_1")

        assert report.weak_count == 1
        assert report.medium_count == 1
        assert report.strong_count == 1

    @pytest.mark.asyncio
    async def test_top_weak_points_sorted_ascending(self, service, mock_db):
        """top_weak_points 按掌握度升序，最弱的排第一"""
        self._setup_db(mock_db, [
            (_make_profile(KP_ID_1, 0.8), _make_kp(KP_ID_1, "好")),
            (_make_profile(KP_ID_2, 0.1), _make_kp(KP_ID_2, "最弱")),
            (_make_profile(KP_ID_3, 0.4), _make_kp(KP_ID_3, "中等")),
        ])
        report = await service.generate_report("stu_1", top_n=3)

        names = [d.knowledge_point_name for d in report.top_weak_points]
        assert names[0] == "最弱"

    @pytest.mark.asyncio
    async def test_top_n_limits_weak_and_strong(self, service, mock_db):
        """top_n 参数限制 top_weak 和 top_strong 的数量"""
        rows = [
            (_make_profile(f"00000000-0000-0000-0000-{i:012d}", i * 0.1),
             _make_kp(f"00000000-0000-0000-0000-{i:012d}", f"KP{i}"))
            for i in range(1, 9)
        ]
        self._setup_db(mock_db, rows)
        report = await service.generate_report("stu_1", top_n=3)

        assert len(report.top_weak_points) <= 3
        assert len(report.top_strong_points) <= 3

    @pytest.mark.asyncio
    async def test_subject_summaries_grouped_correctly(self, service, mock_db):
        """同学科知识点被正确归组"""
        self._setup_db(mock_db, [
            (_make_profile(KP_ID_1, 0.3), _make_kp(KP_ID_1, "一次函数", subject="数学")),
            (_make_profile(KP_ID_2, 0.7), _make_kp(KP_ID_2, "勾股定理", subject="数学")),
            (_make_profile(KP_ID_3, 0.6), _make_kp(KP_ID_3, "光合作用", subject="生物")),
        ])
        report = await service.generate_report("stu_1")

        subjects = {s.subject: s for s in report.subjects}
        assert "数学" in subjects
        assert "生物" in subjects
        assert subjects["数学"].total == 2
        assert subjects["生物"].total == 1

    @pytest.mark.asyncio
    async def test_generated_at_is_iso_format(self, service, mock_db):
        """generated_at 是合法的 ISO 日期时间字符串"""
        self._setup_db(mock_db, [])
        report = await service.generate_report("stu_1")

        parsed = datetime.fromisoformat(report.generated_at)
        assert isinstance(parsed, datetime)

    @pytest.mark.asyncio
    async def test_error_rate_in_detail(self, service, mock_db):
        """知识点详情中 error_rate 计算正确"""
        self._setup_db(mock_db, [
            (_make_profile(KP_ID_1, 0.3, appear=10, error=4),
             _make_kp(KP_ID_1, "错误率测试")),
        ])
        report = await service.generate_report("stu_1")
        detail = report.top_weak_points[0]

        assert detail.error_rate == pytest.approx(0.4)
