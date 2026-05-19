"""
报告生成流程集成测试 — SQLite 内存库

验证报告生成、题目查询等端到端数据流程。
"""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.services.report_service import ReportService, classify_mastery

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
    """
    CREATE TABLE IF NOT EXISTS assignments (
        id              TEXT PRIMARY KEY,
        student_id      TEXT NOT NULL,
        file_id         TEXT,
        file_hash       TEXT,
        original_filename TEXT,
        file_size       INTEGER,
        mime_type       TEXT,
        storage_url     TEXT,
        status          TEXT DEFAULT 'uploaded',
        processing_status TEXT,
        created_at      TEXT DEFAULT (datetime('now')),
        updated_at      TEXT DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS questions (
        id              TEXT PRIMARY KEY,
        assignment_id   TEXT NOT NULL REFERENCES assignments(id),
        raw_text        TEXT,
        markdown        TEXT,
        image_urls      TEXT,
        image_semantics TEXT,
        subject         TEXT,
        grade           TEXT,
        question_type   TEXT,
        knowledge_points TEXT,
        prerequisites   TEXT,
        difficulty      INTEGER,
        likely_error_causes TEXT,
        review_priority TEXT,
        need_review     INTEGER,
        ai_confidence   REAL,
        is_confirmed    INTEGER NOT NULL DEFAULT 0,
        confirmed_knowledge_points TEXT,
        created_at      TEXT DEFAULT (datetime('now')),
        updated_at      TEXT DEFAULT (datetime('now'))
    )
    """,
]

STUDENT = "stu_flow_001"
OTHER_STUDENT = "stu_flow_002"


@pytest_asyncio.fixture
async def db() -> AsyncSession:
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


async def _insert_profile(db: AsyncSession, kp_id: str, mastery: float,
                           appear: int = 5, error: int = 2) -> None:
    await db.execute(text(
        """INSERT INTO student_knowledge_profiles
           (id,student_id,knowledge_point_id,mastery_score,appear_count,error_count)
           VALUES(:id,:stu,:kp,:m,:a,:e)"""
    ), {"id": str(uuid.uuid4()), "stu": STUDENT, "kp": kp_id,
        "m": mastery, "a": appear, "e": error})
    await db.commit()


async def _insert_assignment(db: AsyncSession, student_id: str = STUDENT) -> str:
    a_id = str(uuid.uuid4())
    await db.execute(text(
        "INSERT INTO assignments(id,student_id,status) VALUES(:id,:stu,'uploaded')"
    ), {"id": a_id, "stu": student_id})
    return a_id


async def _insert_question(db: AsyncSession, assignment_id: str,
                            subject: str = "数学", priority: str = "high") -> str:
    q_id = str(uuid.uuid4())
    await db.execute(text(
        """INSERT INTO questions(id,assignment_id,subject,review_priority,need_review)
           VALUES(:id,:aid,:sub,:pri,1)"""
    ), {"id": q_id, "aid": assignment_id, "sub": subject, "pri": priority})
    await db.commit()
    return q_id


# ── classify_mastery 单元测试 ────────────────────────────────────────────────

class TestClassifyMastery:

    def test_below_04_is_weak(self):
        assert classify_mastery(0.0) == "weak"
        assert classify_mastery(0.39) == "weak"

    def test_04_to_07_is_medium(self):
        assert classify_mastery(0.4) == "medium"
        assert classify_mastery(0.69) == "medium"

    def test_07_and_above_is_strong(self):
        assert classify_mastery(0.7) == "strong"
        assert classify_mastery(1.0) == "strong"


# ── ReportService 流程集成测试 ───────────────────────────────────────────────

class TestReportFlow:

    @pytest.mark.asyncio
    async def test_empty_student_report_has_zero_totals(self, db):
        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT)
        assert report.total_knowledge_points == 0
        assert report.overall_mastery == 0.0
        assert report.subjects == []
        assert report.top_weak_points == []

    @pytest.mark.asyncio
    async def test_report_counts_weak_medium_strong_correctly(self, db):
        for name, mastery in [("弱", 0.2), ("中", 0.55), ("强", 0.8)]:
            kp_id = await _insert_kp(db, name)
            await _insert_profile(db, kp_id, mastery)

        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT)

        assert report.total_knowledge_points == 3
        assert report.weak_count == 1
        assert report.medium_count == 1
        assert report.strong_count == 1

    @pytest.mark.asyncio
    async def test_report_top_weak_points_sorted_ascending(self, db):
        for name, mastery in [("中等", 0.5), ("最弱", 0.05), ("较弱", 0.3)]:
            kp_id = await _insert_kp(db, name)
            await _insert_profile(db, kp_id, mastery)

        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT, top_n=3)

        assert report.top_weak_points[0].knowledge_point_name == "最弱"

    @pytest.mark.asyncio
    async def test_report_subject_grouping(self, db):
        for name, subj in [("函数", "数学"), ("方程", "数学"), ("光合作用", "生物")]:
            kp_id = await _insert_kp(db, name, subject=subj)
            await _insert_profile(db, kp_id, mastery=0.5)

        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT)

        subjects = {s.subject: s for s in report.subjects}
        assert subjects["数学"].total == 2
        assert subjects["生物"].total == 1

    @pytest.mark.asyncio
    async def test_report_student_isolation(self, db):
        """不同学生的数据互不干扰。"""
        kp_id = await _insert_kp(db, "三角函数")
        # 只给 OTHER_STUDENT 插数据
        await db.execute(text(
            """INSERT INTO student_knowledge_profiles
               (id,student_id,knowledge_point_id,mastery_score,appear_count,error_count)
               VALUES(:id,:stu,:kp,0.3,5,3)"""
        ), {"id": str(uuid.uuid4()), "stu": OTHER_STUDENT, "kp": kp_id})
        await db.commit()

        svc = ReportService(db=db)
        report = await svc.generate_report(STUDENT)
        assert report.total_knowledge_points == 0


# ── 题目查询隔离测试 ─────────────────────────────────────────────────────────

class TestQuestionIsolation:

    @pytest.mark.asyncio
    async def test_questions_belong_to_correct_student(self, db):
        """通过 Assignment 关联确保题目只属于对应学生。"""
        a1 = await _insert_assignment(db, STUDENT)
        a2 = await _insert_assignment(db, OTHER_STUDENT)

        q1 = await _insert_question(db, a1, subject="数学")
        q2 = await _insert_question(db, a2, subject="语文")

        from sqlalchemy import select
        from src.models.assignment import Assignment
        from src.models.question import Question

        stmt = (
            select(Question)
            .join(Assignment, Question.assignment_id == Assignment.id)
            .where(Assignment.student_id == STUDENT)
        )
        rows = (await db.execute(stmt)).all()
        ids = [str(r[0].id) for r in rows]

        assert q1 in ids
        assert q2 not in ids
