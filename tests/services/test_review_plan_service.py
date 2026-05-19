"""
复习计划生成服务测试

测试覆盖：
1. 生成今日复习计划
2. 空计划（无薄弱知识点）
3. 权重计算（掌握度 + 时间）
4. 题目数推荐
5. 复习原因生成
6. 复习历史查询
"""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile
from src.services.review_plan_service import ReviewPlanService


@pytest.mark.asyncio
async def test_generate_today_plan_empty(async_session):
    """测试：生成今日复习计划（无薄弱知识点）"""
    service = ReviewPlanService(async_session)
    
    plan = await service.generate_today_plan("student_001", max_tasks=5)
    
    # 验证：返回空计划
    assert plan.student_id == "student_001"
    assert plan.date == datetime.now().date().isoformat()
    assert plan.tasks == []
    assert plan.total_minutes == 0


@pytest.mark.asyncio
async def test_generate_today_plan_with_weak_points(async_session):
    """测试：生成今日复习计划（有薄弱知识点）"""
    # 准备：知识点
    kps = []
    for i, name in enumerate(["三角函数", "立体几何", "概率统计"]):
        kp = KnowledgePoint(
            id=uuid4(),
            name=name,
            subject="数学",
            is_active=True,
        )
        kps.append(kp)
        async_session.add(kp)
    
    await async_session.flush()
    
    # 准备：学生画像（3 个薄弱知识点）
    profiles = []
    for i, (kp, mastery) in enumerate(zip(kps, [0.3, 0.5, 0.35])):
        profile = StudentKnowledgeProfile(
            id=uuid4(),
            student_id="student_001",
            knowledge_point_id=kp.id,
            appear_count=10,
            error_count=int(10 * (1 - mastery)),
            mastery_score=mastery,
            review_priority="high" if mastery < 0.4 else "medium",
            last_reviewed_at=datetime.now() - timedelta(days=3),
        )
        profiles.append(profile)
        async_session.add(profile)
    
    await async_session.commit()
    
    service = ReviewPlanService(async_session)
    plan = await service.generate_today_plan("student_001", max_tasks=5)
    
    # 验证：生成复习计划
    assert plan.student_id == "student_001"
    assert plan.date == datetime.now().date().isoformat()
    assert len(plan.tasks) == 3  # 3 个薄弱知识点
    assert plan.total_minutes > 0
    
    # 验证：任务按权重排序（掌握度最低的优先）
    assert plan.tasks[0].knowledge_point_name == "三角函数"  # mastery=0.3
    assert plan.tasks[0].priority == "high"
    assert plan.tasks[0].recommended_count >= 3


@pytest.mark.asyncio
async def test_generate_today_plan_with_max_tasks_limit(async_session):
    """测试：生成今日复习计划（限制最大任务数）"""
    # 准备：5 个薄弱知识点
    for i in range(5):
        kp = KnowledgePoint(
            id=uuid4(),
            name=f"知识点{i}",
            subject="数学",
            is_active=True,
        )
        async_session.add(kp)
        await async_session.flush()
        
        profile = StudentKnowledgeProfile(
            id=uuid4(),
            student_id="student_001",
            knowledge_point_id=kp.id,
            appear_count=10,
            error_count=7,
            mastery_score=0.3 + i * 0.05,
            review_priority="high",
            last_reviewed_at=datetime.now() - timedelta(days=1),
        )
        async_session.add(profile)
    
    await async_session.commit()
    
    service = ReviewPlanService(async_session)
    plan = await service.generate_today_plan("student_001", max_tasks=3)
    
    # 验证：返回数量符合限制
    assert len(plan.tasks) == 3


@pytest.mark.asyncio
async def test_generate_today_plan_time_weight(async_session):
    """测试：时间权重计算（长时间未复习的优先）"""
    # 准备：2 个知识点，掌握度相同，但复习时间不同
    kp1 = KnowledgePoint(
        id=uuid4(),
        name="最近复习",
        subject="数学",
        is_active=True,
    )
    kp2 = KnowledgePoint(
        id=uuid4(),
        name="很久未复习",
        subject="数学",
        is_active=True,
    )
    async_session.add_all([kp1, kp2])
    await async_session.flush()
    
    # 画像 1：最近复习过（3 天前）
    profile1 = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp1.id,
        appear_count=10,
        error_count=5,
        mastery_score=0.5,
        review_priority="medium",
        last_reviewed_at=datetime.now() - timedelta(days=3),
    )
    
    # 画像 2：很久未复习（15 天前）
    profile2 = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp2.id,
        appear_count=10,
        error_count=5,
        mastery_score=0.5,
        review_priority="medium",
        last_reviewed_at=datetime.now() - timedelta(days=15),
    )
    
    async_session.add_all([profile1, profile2])
    await async_session.commit()
    
    service = ReviewPlanService(async_session)
    plan = await service.generate_today_plan("student_001", max_tasks=5)
    
    # 验证：很久未复习的排在前面（时间权重加成）
    assert len(plan.tasks) == 2
    assert plan.tasks[0].knowledge_point_name == "很久未复习"


@pytest.mark.asyncio
async def test_generate_today_plan_never_reviewed(async_session):
    """测试：从未复习过的知识点（权重加成）"""
    # 准备：2 个知识点，一个复习过，一个从未复习
    kp1 = KnowledgePoint(
        id=uuid4(),
        name="复习过",
        subject="数学",
        is_active=True,
    )
    kp2 = KnowledgePoint(
        id=uuid4(),
        name="从未复习",
        subject="数学",
        is_active=True,
    )
    async_session.add_all([kp1, kp2])
    await async_session.flush()
    
    # 画像 1：复习过
    profile1 = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp1.id,
        appear_count=10,
        error_count=5,
        mastery_score=0.5,
        review_priority="medium",
        last_reviewed_at=datetime.now() - timedelta(days=3),
    )
    
    # 画像 2：从未复习（last_reviewed_at = None）
    profile2 = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp2.id,
        appear_count=10,
        error_count=5,
        mastery_score=0.5,
        review_priority="medium",
        last_reviewed_at=None,
    )
    
    async_session.add_all([profile1, profile2])
    await async_session.commit()
    
    service = ReviewPlanService(async_session)
    plan = await service.generate_today_plan("student_001", max_tasks=5)
    
    # 验证：从未复习的排在前面（权重加成 50%）
    assert len(plan.tasks) == 2
    assert plan.tasks[0].knowledge_point_name == "从未复习"


@pytest.mark.asyncio
async def test_calculate_recommended_count(async_session):
    """测试：推荐题目数计算"""
    service = ReviewPlanService(async_session)
    
    # 掌握度越低，推荐越多题目
    assert service._calculate_recommended_count(0.0) == 10  # 最多 10 题
    assert service._calculate_recommended_count(0.3) == 7
    assert service._calculate_recommended_count(0.5) == 5
    assert service._calculate_recommended_count(0.6) == 4
    assert service._calculate_recommended_count(0.9) == 3  # 最少 3 题


@pytest.mark.asyncio
async def test_generate_reason_low_mastery(async_session):
    """测试：复习原因生成（低掌握度）"""
    # 准备：知识点
    kp = KnowledgePoint(
        id=uuid4(),
        name="二次方程",
        subject="数学",
        is_active=True,
    )
    async_session.add(kp)
    await async_session.flush()
    
    # 准备：低掌握度画像
    profile = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp.id,
        appear_count=10,
        error_count=8,
        mastery_score=0.2,
        review_priority="high",
        last_reviewed_at=datetime.now() - timedelta(days=3),
    )
    async_session.add(profile)
    await async_session.commit()
    
    service = ReviewPlanService(async_session)
    reason = service._generate_reason(profile)
    
    # 验证：包含掌握度低的原因
    assert "掌握度较低" in reason or "20%" in reason


@pytest.mark.asyncio
async def test_generate_reason_high_error_rate(async_session):
    """测试：复习原因生成（高错误率）"""
    # 准备：知识点
    kp = KnowledgePoint(
        id=uuid4(),
        name="三角函数",
        subject="数学",
        is_active=True,
    )
    async_session.add(kp)
    await async_session.flush()
    
    # 准备：高错误率画像
    profile = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp.id,
        appear_count=10,
        error_count=7,  # 70% 错误率
        mastery_score=0.4,
        review_priority="high",
        last_reviewed_at=datetime.now() - timedelta(days=2),
    )
    async_session.add(profile)
    await async_session.commit()
    
    service = ReviewPlanService(async_session)
    reason = service._generate_reason(profile)
    
    # 验证：包含错误率高的原因
    assert "错误率" in reason


@pytest.mark.asyncio
async def test_generate_reason_long_time_no_review(async_session):
    """测试：复习原因生成（长时间未复习）"""
    # 准备：知识点
    kp = KnowledgePoint(
        id=uuid4(),
        name="立体几何",
        subject="数学",
        is_active=True,
    )
    async_session.add(kp)
    await async_session.flush()
    
    # 准备：长时间未复习画像
    profile = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp.id,
        appear_count=10,
        error_count=4,
        mastery_score=0.5,
        review_priority="medium",
        last_reviewed_at=datetime.now() - timedelta(days=20),
    )
    async_session.add(profile)
    await async_session.commit()
    
    service = ReviewPlanService(async_session)
    reason = service._generate_reason(profile)
    
    # 验证：包含长时间未复习的原因
    assert "天未复习" in reason or "20" in reason


@pytest.mark.asyncio
async def test_get_review_history_empty(async_session):
    """测试：获取复习历史（无数据）"""
    service = ReviewPlanService(async_session)
    
    history = await service.get_review_history("student_001", days=30)
    
    # 验证：返回空列表
    assert history == []


@pytest.mark.asyncio
async def test_get_review_history_with_data(async_session):
    """测试：获取复习历史（有数据）"""
    # 准备：知识点
    kps = []
    for i, name in enumerate(["二次方程", "三角函数", "立体几何"]):
        kp = KnowledgePoint(
            id=uuid4(),
            name=name,
            subject="数学",
            is_active=True,
        )
        kps.append(kp)
        async_session.add(kp)
    
    await async_session.flush()
    
    # 准备：学生画像（最近 30 天内复习过）
    now = datetime.now()
    for i, kp in enumerate(kps):
        profile = StudentKnowledgeProfile(
            id=uuid4(),
            student_id="student_001",
            knowledge_point_id=kp.id,
            appear_count=10,
            error_count=3,
            mastery_score=0.7,
            review_priority="low",
            last_reviewed_at=now - timedelta(days=i * 5),  # 0, 5, 10 天前
        )
        async_session.add(profile)
    
    await async_session.commit()
    
    service = ReviewPlanService(async_session)
    history = await service.get_review_history("student_001", days=30)
    
    # 验证：返回复习历史
    assert len(history) == 3
    
    # 验证：按时间倒序排列（最近的在前）
    assert history[0]["knowledge_point"] == "二次方程"
    assert history[1]["knowledge_point"] == "三角函数"
    assert history[2]["knowledge_point"] == "立体几何"


@pytest.mark.asyncio
async def test_get_review_history_with_time_filter(async_session):
    """测试：获取复习历史（时间过滤）"""
    # 准备：知识点
    kp1 = KnowledgePoint(
        id=uuid4(),
        name="最近复习",
        subject="数学",
        is_active=True,
    )
    kp2 = KnowledgePoint(
        id=uuid4(),
        name="很久前复习",
        subject="数学",
        is_active=True,
    )
    async_session.add_all([kp1, kp2])
    await async_session.flush()
    
    # 准备：学生画像
    now = datetime.now()
    
    # 最近复习（5 天前）
    profile1 = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp1.id,
        appear_count=10,
        error_count=3,
        mastery_score=0.7,
        review_priority="low",
        last_reviewed_at=now - timedelta(days=5),
    )
    
    # 很久前复习（40 天前，超出 30 天范围）
    profile2 = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp2.id,
        appear_count=10,
        error_count=3,
        mastery_score=0.7,
        review_priority="low",
        last_reviewed_at=now - timedelta(days=40),
    )
    
    async_session.add_all([profile1, profile2])
    await async_session.commit()
    
    service = ReviewPlanService(async_session)
    history = await service.get_review_history("student_001", days=30)
    
    # 验证：只返回 30 天内的复习历史
    assert len(history) == 1
    assert history[0]["knowledge_point"] == "最近复习"


@pytest.mark.asyncio
async def test_generate_today_plan_total_minutes_calculation(async_session):
    """测试：总时间计算"""
    # 准备：知识点
    kp = KnowledgePoint(
        id=uuid4(),
        name="二次方程",
        subject="数学",
        is_active=True,
    )
    async_session.add(kp)
    await async_session.flush()
    
    # 准备：学生画像
    profile = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp.id,
        appear_count=10,
        error_count=7,
        mastery_score=0.3,
        review_priority="high",
        last_reviewed_at=datetime.now() - timedelta(days=3),
    )
    async_session.add(profile)
    await async_session.commit()
    
    service = ReviewPlanService(async_session)
    plan = await service.generate_today_plan("student_001", max_tasks=5)
    
    # 验证：总时间 = 推荐题目数 × 3 分钟
    assert len(plan.tasks) == 1
    task = plan.tasks[0]
    assert plan.total_minutes == task.estimated_minutes
    assert task.estimated_minutes == task.recommended_count * 3
