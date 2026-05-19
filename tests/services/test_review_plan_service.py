"""
复习计划生成服务测试

TDD：先写测试，再写实现。
覆盖：纯函数算法 + DB 查询逻辑（mock DB）
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.review_plan_service import (
    DailyReviewPlan,
    ReviewPlanService,
    ReviewTaskItem,
    calculate_priority_score,
    determine_priority,
    estimate_recommended_count,
)


# ─── 纯函数测试（无 DB 依赖） ────────────────────────────────────────────────


class TestCalculatePriorityScore:
    """calculate_priority_score 优先级评分算法测试"""

    def test_low_mastery_never_reviewed_gives_max_score(self):
        """掌握度为 0，从未复习 → 最高分 2.0"""
        score = calculate_priority_score(mastery_score=0.0, last_reviewed_at=None)
        assert score == pytest.approx(2.0, abs=0.01)

    def test_high_mastery_recently_reviewed_gives_low_score(self):
        """掌握度 0.9，刚复习过 → 低分"""
        recently = datetime.now(timezone.utc) - timedelta(hours=1)
        score = calculate_priority_score(mastery_score=0.9, last_reviewed_at=recently)
        assert score < 0.2

    def test_medium_mastery_long_ago_reviewed(self):
        """掌握度 0.5，30 天前复习 → 中等偏高分"""
        long_ago = datetime.now(timezone.utc) - timedelta(days=30)
        score = calculate_priority_score(mastery_score=0.5, last_reviewed_at=long_ago)
        # (1 - 0.5) * 2.0 = 1.0
        assert score == pytest.approx(1.0, abs=0.05)

    def test_score_is_non_negative(self):
        """任何情况下分数不为负"""
        score = calculate_priority_score(mastery_score=1.0, last_reviewed_at=None)
        assert score >= 0.0

    def test_recency_weight_caps_at_max(self):
        """超过 30 天的间隔权重上限为 2.0（不无限增长）"""
        very_long_ago = datetime.now(timezone.utc) - timedelta(days=365)
        exactly_30 = datetime.now(timezone.utc) - timedelta(days=30)
        score_long = calculate_priority_score(0.5, very_long_ago)
        score_30 = calculate_priority_score(0.5, exactly_30)
        assert abs(score_long - score_30) < 0.05


class TestDeterminePriority:
    """determine_priority 优先级映射测试"""

    def test_high_score_gives_high_priority(self):
        assert determine_priority(score=1.5) == "high"

    def test_medium_score_gives_medium_priority(self):
        assert determine_priority(score=0.7) == "medium"

    def test_low_score_gives_low_priority(self):
        assert determine_priority(score=0.2) == "low"

    def test_boundary_at_high_threshold(self):
        assert determine_priority(score=1.0) == "high"

    def test_boundary_at_medium_threshold(self):
        assert determine_priority(score=0.5) == "medium"


class TestEstimateRecommendedCount:
    """estimate_recommended_count 建议练习题数测试"""

    def test_very_weak_gets_most_questions(self):
        assert estimate_recommended_count(mastery_score=0.1) == 5

    def test_medium_weak_gets_medium_questions(self):
        assert estimate_recommended_count(mastery_score=0.4) == 3

    def test_almost_proficient_gets_few_questions(self):
        assert estimate_recommended_count(mastery_score=0.7) == 2

    def test_boundary_at_0_3(self):
        assert estimate_recommended_count(mastery_score=0.3) == 3

    def test_boundary_at_0_6(self):
        assert estimate_recommended_count(mastery_score=0.6) == 2


# ─── 辅助函数 ────────────────────────────────────────────────────────────────


KP_ID_1 = "00000000-0000-0000-0000-000000000001"
KP_ID_2 = "00000000-0000-0000-0000-000000000002"


def _make_profile(kp_id: str, mastery_score: float, last_reviewed_at=None):
    p = MagicMock()
    p.knowledge_point_id = uuid.UUID(kp_id)
    p.mastery_score = mastery_score
    p.review_priority = "medium"
    p.last_reviewed_at = last_reviewed_at
    p.next_review_at = None
    p.appear_count = 5
    p.error_count = 2
    return p


def _make_kp(kp_id: str, name: str, subject: str = "数学", grade: str = "八年级"):
    kp = MagicMock()
    kp.id = uuid.UUID(kp_id)
    kp.name = name
    kp.subject = subject
    kp.grade = grade
    return kp


# ─── 服务层测试（mock DB） ───────────────────────────────────────────────────


class TestReviewPlanService:
    """ReviewPlanService.generate_today_plan 测试"""

    @pytest.fixture
    def mock_db(self):
        return AsyncMock()

    @pytest.fixture
    def service(self, mock_db):
        return ReviewPlanService(db=mock_db)

    def _setup_db(self, mock_db, rows: list):
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        mock_db.execute.return_value = mock_result

    @pytest.mark.asyncio
    async def test_empty_profile_returns_empty_plan(self, service, mock_db):
        """学生无任何知识点记录 → 返回空计划"""
        self._setup_db(mock_db, [])
        plan = await service.generate_today_plan(student_id="stu_1")

        assert isinstance(plan, DailyReviewPlan)
        assert plan.tasks == []
        assert plan.total_minutes == 0
        assert plan.student_id == "stu_1"

    @pytest.mark.asyncio
    async def test_weak_point_is_high_priority(self, service, mock_db):
        """掌握度低（0.2）的知识点应出现且优先级为 high"""
        self._setup_db(mock_db, [
            (_make_profile(KP_ID_1, mastery_score=0.2), _make_kp(KP_ID_1, "一次函数")),
        ])

        plan = await service.generate_today_plan("stu_1")

        assert len(plan.tasks) == 1
        assert plan.tasks[0].knowledge_point_name == "一次函数"
        assert plan.tasks[0].priority == "high"

    @pytest.mark.asyncio
    async def test_max_tasks_is_respected(self, service, mock_db):
        """返回的任务数不超过 max_tasks"""
        rows = [
            (_make_profile(f"00000000-0000-0000-0000-{i:012d}", 0.1),
             _make_kp(f"00000000-0000-0000-0000-{i:012d}", f"知识点{i}"))
            for i in range(1, 8)
        ]
        self._setup_db(mock_db, rows)

        plan = await service.generate_today_plan("stu_1", max_tasks=3)

        assert len(plan.tasks) <= 3

    @pytest.mark.asyncio
    async def test_total_minutes_equals_sum_of_tasks(self, service, mock_db):
        """total_minutes 等于所有任务 estimated_minutes 之和"""
        self._setup_db(mock_db, [
            (_make_profile(KP_ID_1, 0.2), _make_kp(KP_ID_1, "知识点A")),
            (_make_profile(KP_ID_2, 0.4), _make_kp(KP_ID_2, "知识点B")),
        ])

        plan = await service.generate_today_plan("stu_1")

        assert plan.total_minutes == sum(t.estimated_minutes for t in plan.tasks)

    @pytest.mark.asyncio
    async def test_plan_date_is_today(self, service, mock_db):
        """返回的 date 字段是今天的 ISO 格式"""
        self._setup_db(mock_db, [])
        plan = await service.generate_today_plan("stu_1")
        assert plan.date == date.today().isoformat()

    @pytest.mark.asyncio
    async def test_review_task_item_has_all_required_fields(self, service, mock_db):
        """ReviewTaskItem 包含所有必需字段且类型正确"""
        self._setup_db(mock_db, [
            (_make_profile(KP_ID_1, 0.3), _make_kp(KP_ID_1, "二次函数", "数学", "九年级")),
        ])

        plan = await service.generate_today_plan("stu_1")
        task = plan.tasks[0]

        assert task.knowledge_point_id == KP_ID_1
        assert task.knowledge_point_name == "二次函数"
        assert task.subject == "数学"
        assert task.priority in ("high", "medium", "low")
        assert isinstance(task.reason, str) and len(task.reason) > 0
        assert task.recommended_count > 0
        assert task.estimated_minutes > 0
        assert task.mastery_score == pytest.approx(0.3)
