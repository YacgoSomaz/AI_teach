"""
服务层集成测试 — SQLite 内存库

使用真实 SQLAlchemy 模型字段，不 mock DB，验证查询逻辑正确性。
UUID 列在 SQLite 以 TEXT 存储，比较仍然正确。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.services.report_service import ReportService, classify_mastery
from src.services.review_plan_service import ReviewPlanService

# ── SQLite-compatible DDL（与真实模型字段一一对应）──────────────────────────

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS knowledge_points (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        subject     TEXT NOT NULL,
        grade       TEXT,
        chapter     TEXT,
        parent_id   TEXT,
        prerequisites TEXT,
        common_errors TEXT,
        description TEXT,
        textbook_version TEXT,
        is_active   INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT DEFAULT (datetime('now')),
        updated_at  TEXT DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS student_knowledge_profiles (
        id                  TEXT PRIMARY KEY,
        student_id          TEXT NOT NULL,
        knowledge_point_id  TEXT NOT NULL REFERENCES knowledge_points(id),
        appear_count        INTEGER NOT NULL DEFAULT 0,
        error_count         INTEGER NOT NULL DEFAULT 0,
        last_error_at       TEXT,
        last_reviewed_at    TEXT,
        mastery_score       REAL NOT NULL DEFAULT 0.5,
        review_priority     TEXT NOT NULL DEFAULT 'medium',
        next_review_at      TEXT,
        created_at          TEXT DEFAULT (datetime('now')),
        updated_at          TEXT DEFAULT (datetime('now'))
    )
    """,
]

STUDENT = "stu_integration_001"


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db() -> AsyncSession:
    """每个测试独立内存库，测试结束自动销毁。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        for ddl in _DDL:
            await conn.execute(text(ddl))

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


async def _insert_kp(db: AsyncSession, name: str, subject: str = "数学", grade: str = "八年级") -> str:
    kp_id = str(uuid.uuid4())
    await db.execute(text(
        "INSERT INTO knowledge_points(id,name,subject,grade) VALUES(:id,:n,:s,:g)"
    ), {"id": kp_id, "n": name, "s": subject, "g": grade})
    return kp_id


async def _insert_profile(
    db: AsyncSession,
    kp_id: str,
    mastery: float,
    appear: int = 5,
    error: int = 2,
    priority: str | None = None,  # 改为可选，自动计算
    last_reviewed_at: datetime | None = None,
) -> None:
    # 自动计算 priority（与 StudentProfileService 逻辑一致）
    if priority is None:
        if mastery < 0.4:
            priority = "high"
        elif mastery < 0.6:
            priority = "medium"
        else:
            priority = "low"
    
    reviewed = last_reviewed_at.isoformat() if last_reviewed_at else None
    await db.execute(text(
        """INSERT INTO student_knowledge_profiles
           (id, student_id, knowledge_point_id, mastery_score,
            appear_count, error_count, review_priority, last_reviewed_at)
           VALUES (:id,:stu,:kp,:m,:a,:e,:p,:r)"""
    ), {
        "id": str(uuid.uuid4()),
        "stu": STUDENT,
        "kp": kp_id,
        "m": mastery,
        "a": appear,
        "e": error,
        "p": priority,
        "r": reviewed,
    })
    await db.commit()


# ── ReviewPlanService 集成测试 ───────────────────────────────────────────────

class TestReviewPlanServiceIntegration:

    @pytest.mark.asyncio
    async def test_empty_student_returns_empty_plan(self, db):
        svc = ReviewPlanService(db=db)
        plan = await svc.generate_today_plan(STUDENT)
        assert plan.tasks == []
        assert plan.total_minutes == 0
        assert plan.student_id == STUDENT

    @pytest.mark.asyncio
    async def test_weak_point_appears_and_is_high_priority(self, db):
        kp_id = await _insert_kp(db, "三角函数")
        await _insert_profile(db, kp_id, mastery=0.1)

        svc = ReviewPlanService(db=db)
        plan = await svc.generate_today_plan(STUDENT)

        assert len(plan.tasks) == 1
        task = plan.tasks[0]
        assert task.knowledge_point_name == "三角函数"
        assert task.priority == "high"
        assert task.mastery_score == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_tasks_sorted_by_priority_score_desc(self, db):
        """掌握度最低的知识点排在最前面。"""
        for name, mastery in [("高掌握", 0.9), ("低掌握", 0.1), ("中掌握", 0.5)]:
            kp_id = await _insert_kp(db, name)
            await _insert_profile(db, kp_id, mastery=mastery)

        svc = ReviewPlanService(db=db)
        plan = await svc.generate_today_plan(STUDENT, max_tasks=3)

        assert plan.tasks[0].knowledge_point_name == "低掌握"
        assert plan.tasks[-1].knowledge_point_name == "高掌握"

    @pytest.mark.asyncio
    async def test_max_tasks_limits_output(self, db):
        for i in range(6):
            kp_id = await _insert_kp(db, f"知识点{i}")
            await _insert_profile(db, kp_id, mastery=0.2)

        svc = ReviewPlanService(db=db)
        plan = await svc.generate_today_plan(STUDENT, max_tasks=3)

        assert len(plan.tasks) == 3

    @pytest.mark.asyncio
    async def test_total_minutes_equals_sum_of_tasks(self, db):
        for i in range(3):
            kp_id = await _insert_kp(db, f"KP{i}")
            await _insert_profile(db, kp_id, mastery=0.3)

        svc = ReviewPlanService(db=db)
        plan = await svc.generate_today_plan(STUDENT)

        assert plan.total_minutes == sum(t.estimated_minutes for t in plan.tasks)

    @pytest.mark.asyncio
    async def test_never_reviewed_gets_higher_priority_than_recently_reviewed(self, db):
        """从未复习的知识点权重最大（recency_weight=2.0）。"""
        kp_never = await _insert_kp(db, "从未复习")
        await _insert_profile(db, kp_never, mastery=0.5, last_reviewed_at=None)

        kp_recent = await _insert_kp(db, "刚刚复习")
        await _insert_profile(
            db, kp_recent, mastery=0.5,
            last_reviewed_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        svc = ReviewPlanService(db=db)
        plan = await svc.generate_today_plan(STUDENT)

        assert plan.tasks[0].knowledge_point_name == "从未复习"

    @pytest.mark.asyncio
    async def test_task_fields_match_real_model_fields(self, db):
        """ReviewTaskItem 中的字段名与 KnowledgePoint/StudentKnowledgeProfile 一致。"""
        kp_id = await _insert_kp(db, "二次函数", subject="数学", grade="九年级")
        await _insert_profile(db, kp_id, mastery=0.25, appear=8, error=6)

        svc = ReviewPlanService(db=db)
        plan = await svc.generate_today_plan(STUDENT)

        task = plan.tasks[0]
        assert task.knowledge_point_id == kp_id
        assert task.subject == "数学"
        assert task.grade == "九年级"
        assert task.recommended_count == 7   # mastery=0.25 → int((1-0.25)*10) = 7 题
        assert task.estimated_minutes == 21  # 7 × 3 min


# ── ReportService 集成测试 ───────────────────────────────────────────────────

class TestReportServiceIntegration:

    @pytest.mark.asyncio
    async def test_empty_student_returns_zero_report(self, db):
        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT)
        assert report.total_knowledge_points == 0
        assert report.overall_mastery == 0.0
        assert report.subjects == []

    @pytest.mark.asyncio
    async def test_mastery_level_counts_match_real_data(self, db):
        for name, mastery in [("弱1", 0.2), ("弱2", 0.3), ("中", 0.55), ("强", 0.85)]:
            kp_id = await _insert_kp(db, name)
            await _insert_profile(db, kp_id, mastery=mastery)

        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT)

        assert report.total_knowledge_points == 4
        assert report.weak_count == 2    # < 0.4
        assert report.medium_count == 1  # 0.4-0.7
        assert report.strong_count == 1  # >= 0.7

    @pytest.mark.asyncio
    async def test_overall_mastery_is_correct_average(self, db):
        for name, mastery in [("A", 0.4), ("B", 0.6), ("C", 0.8)]:
            kp_id = await _insert_kp(db, name)
            await _insert_profile(db, kp_id, mastery=mastery)

        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT)

        assert report.overall_mastery == pytest.approx(0.6, abs=0.001)

    @pytest.mark.asyncio
    async def test_subject_grouping_is_correct(self, db):
        for name, subj in [("函数", "数学"), ("方程", "数学"), ("光合作用", "生物")]:
            kp_id = await _insert_kp(db, name, subject=subj)
            await _insert_profile(db, kp_id, mastery=0.5)

        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT)

        subjects = {s.subject: s for s in report.subjects}
        assert subjects["数学"].total == 2
        assert subjects["生物"].total == 1

    @pytest.mark.asyncio
    async def test_top_weak_points_sorted_ascending(self, db):
        for name, mastery in [("中等", 0.5), ("最弱", 0.05), ("较弱", 0.3)]:
            kp_id = await _insert_kp(db, name)
            await _insert_profile(db, kp_id, mastery=mastery)

        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT, top_n=3)

        names = [d.knowledge_point_name for d in report.top_weak_points]
        assert names[0] == "最弱"

    @pytest.mark.asyncio
    async def test_error_rate_computed_from_real_appear_error_counts(self, db):
        kp_id = await _insert_kp(db, "错误率验证")
        await _insert_profile(db, kp_id, mastery=0.4, appear=10, error=7)

        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT)

        detail = report.top_weak_points[0]
        assert detail.appear_count == 10
        assert detail.error_count == 7
        assert detail.error_rate == pytest.approx(0.7, abs=0.001)
