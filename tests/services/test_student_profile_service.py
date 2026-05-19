"""
学生画像服务测试

测试覆盖：
1. 获取学生完整画像
2. 获取薄弱知识点
3. 获取学习进度
4. 更新学生画像
5. 生成复习建议

使用真实的数据库模型进行测试
"""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from src.models.assignment import Assignment
from src.models.question import Question
from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile
from src.services.student_profile_service import StudentProfileService


@pytest.mark.asyncio
async def test_get_profile_empty(async_session):
    """测试：获取空画像（学生没有任何记录）"""
    service = StudentProfileService(async_session)
    
    profile = await service.get_profile("student_001")
    
    # 验证：返回空画像
    assert profile["student_id"] == "student_001"
    assert profile["total_questions"] == 0
    assert profile["correct_rate"] == 0.0
    assert profile["knowledge_points"] == []
    assert profile["weak_points"] == []
    assert "updated_at" in profile


@pytest.mark.asyncio
async def test_get_profile_with_data(async_session):
    """测试：获取有数据的学生画像"""
    # 准备：知识点
    kp1 = KnowledgePoint(
        id=uuid4(),
        name="二次方程",
        subject="数学",
        is_active=True,
    )
    kp2 = KnowledgePoint(
        id=uuid4(),
        name="三角函数",
        subject="数学",
        is_active=True,
    )
    async_session.add_all([kp1, kp2])
    await async_session.flush()
    
    # 准备：学生画像
    profile1 = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp1.id,
        appear_count=10,
        error_count=2,
        mastery_score=0.8,
        review_priority="low",
        last_reviewed_at=datetime.now(),
    )
    profile2 = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp2.id,
        appear_count=5,
        error_count=3,
        mastery_score=0.4,
        review_priority="high",
        last_reviewed_at=datetime.now(),
    )
    async_session.add_all([profile1, profile2])
    await async_session.commit()
    
    service = StudentProfileService(async_session)
    profile = await service.get_profile("student_001")
    
    # 验证：统计数据正确
    assert profile["student_id"] == "student_001"
    assert profile["total_questions"] == 15  # 10 + 5
    assert profile["correct_rate"] == 10 / 15  # (8 + 2) / 15
    assert len(profile["knowledge_points"]) == 2
    
    # 验证：薄弱知识点识别正确（掌握度 < 0.6）
    assert len(profile["weak_points"]) == 1
    assert "三角函数" in profile["weak_points"]


@pytest.mark.asyncio
async def test_get_weak_points(async_session):
    """测试：获取薄弱知识点"""
    # 准备：知识点
    kps = []
    for i, (name, mastery) in enumerate([
        ("三角函数", 0.3),
        ("立体几何", 0.5),
        ("概率统计", 0.35),
    ]):
        kp = KnowledgePoint(
            id=uuid4(),
            name=name,
            subject="数学",
            is_active=True,
        )
        kps.append(kp)
        async_session.add(kp)
    
    await async_session.flush()
    
    # 准备：学生画像
    for kp, mastery in zip(kps, [0.3, 0.5, 0.35]):
        profile = StudentKnowledgeProfile(
            id=uuid4(),
            student_id="student_001",
            knowledge_point_id=kp.id,
            appear_count=10,
            error_count=int(10 * (1 - mastery)),
            mastery_score=mastery,
            review_priority="high" if mastery < 0.4 else "medium",
            last_reviewed_at=datetime.now(),
        )
        async_session.add(profile)
    
    await async_session.commit()
    
    service = StudentProfileService(async_session)
    weak_points = await service.get_weak_points("student_001", limit=5, threshold=0.6)
    
    # 验证：返回所有薄弱知识点
    assert len(weak_points) == 3
    assert weak_points[0]["knowledge_point"] == "三角函数"
    assert weak_points[0]["mastery_score"] == 0.3
    assert weak_points[0]["question_count"] == 10


@pytest.mark.asyncio
async def test_get_weak_points_with_limit(async_session):
    """测试：获取薄弱知识点（带数量限制）"""
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
            last_reviewed_at=datetime.now(),
        )
        async_session.add(profile)
    
    await async_session.commit()
    
    service = StudentProfileService(async_session)
    weak_points = await service.get_weak_points("student_001", limit=3)
    
    # 验证：返回数量符合限制
    assert len(weak_points) == 3


@pytest.mark.asyncio
async def test_get_progress_empty(async_session):
    """测试：获取学习进度（无数据）"""
    service = StudentProfileService(async_session)
    
    progress = await service.get_progress("student_001", days=30)
    
    # 验证：返回空进度
    assert progress["student_id"] == "student_001"
    assert progress["period"] == "30 days"
    assert progress["total_questions"] == 0
    assert progress["correct_rate"] == 0.0
    assert progress["daily_stats"] == []


@pytest.mark.asyncio
async def test_get_progress_with_data(async_session):
    """测试：获取学习进度（有数据）"""
    # 准备：作业
    assignment = Assignment(
        id=uuid4(),
        student_id="student_001",
        file_id=f"file_{uuid4()}",
        original_filename="test.jpg",
        file_hash="hash123",
        file_size=1024,
        mime_type="image/jpeg",
        storage_url="https://example.com/test.jpg",
        status="completed",
    )
    async_session.add(assignment)
    await async_session.flush()
    
    # 准备：3 天的题目记录
    now = datetime.now()
    
    # 第 1 天：5 题
    for i in range(5):
        q = Question(
            id=uuid4(),
            assignment_id=assignment.id,
            raw_text=f"题目{i}",
        )
        q.created_at = now - timedelta(days=2)
        async_session.add(q)
    
    # 第 2 天：3 题
    for i in range(3):
        q = Question(
            id=uuid4(),
            assignment_id=assignment.id,
            raw_text=f"题目{i+5}",
        )
        q.created_at = now - timedelta(days=1)
        async_session.add(q)
    
    # 第 3 天：4 题
    for i in range(4):
        q = Question(
            id=uuid4(),
            assignment_id=assignment.id,
            raw_text=f"题目{i+8}",
        )
        q.created_at = now
        async_session.add(q)
    
    await async_session.commit()
    
    service = StudentProfileService(async_session)
    progress = await service.get_progress("student_001", days=30)
    
    # 验证：统计数据正确
    assert progress["student_id"] == "student_001"
    assert progress["total_questions"] == 12  # 5 + 3 + 4
    # 注意：由于 Question 模型没有 is_correct 字段，正确率为 0
    assert progress["correct_rate"] == 0.0
    assert len(progress["daily_stats"]) == 3
    
    # 验证每日统计
    assert progress["daily_stats"][0]["questions"] == 5
    assert progress["daily_stats"][1]["questions"] == 3
    assert progress["daily_stats"][2]["questions"] == 4


@pytest.mark.asyncio
async def test_update_profile_new_knowledge_point(async_session):
    """测试：更新画像（新知识点）"""
    # 准备：作业
    assignment = Assignment(
        id=uuid4(),
        student_id="student_001",
        file_id=f"file_{uuid4()}",
        original_filename="test.jpg",
        file_hash="hash123",
        file_size=1024,
        mime_type="image/jpeg",
        storage_url="https://example.com/test.jpg",
        status="completed",
    )
    async_session.add(assignment)
    await async_session.flush()
    
    # 准备：题目
    question = Question(
        id=uuid4(),
        assignment_id=assignment.id,
        raw_text="测试题目",
        subject="数学",
        knowledge_points=["二次方程"],
    )
    async_session.add(question)
    await async_session.commit()
    
    service = StudentProfileService(async_session)
    await service.update_profile(
        student_id="student_001",
        question_id=str(question.id),
        is_correct=True,
    )
    
    # 验证：题目正确性被更新
    await async_session.refresh(question)
    assert question.is_correct == True
    
    # 验证：画像被创建
    from sqlalchemy import select
    result = await async_session.execute(
        select(StudentKnowledgeProfile).where(
            StudentKnowledgeProfile.student_id == "student_001"
        )
    )
    profiles = list(result.scalars().all())
    assert len(profiles) == 1
    assert profiles[0].appear_count == 1
    assert profiles[0].error_count == 0
    assert profiles[0].mastery_score == 1.0


@pytest.mark.asyncio
async def test_update_profile_existing_knowledge_point(async_session):
    """测试：更新画像（已存在的知识点）"""
    # 准备：知识点
    kp = KnowledgePoint(
        id=uuid4(),
        name="二次方程",
        subject="数学",
        is_active=True,
    )
    async_session.add(kp)
    await async_session.flush()
    
    # 准备：已存在的画像
    existing_profile = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp.id,
        appear_count=5,
        error_count=2,
        mastery_score=0.6,
        review_priority="medium",
        last_reviewed_at=datetime.now(),
    )
    async_session.add(existing_profile)
    
    # 准备：作业
    assignment = Assignment(
        id=uuid4(),
        student_id="student_001",
        file_id=f"file_{uuid4()}",
        original_filename="test.jpg",
        file_hash="hash456",
        file_size=1024,
        mime_type="image/jpeg",
        storage_url="https://example.com/test.jpg",
        status="completed",
    )
    async_session.add(assignment)
    await async_session.flush()
    
    # 准备：题目
    question = Question(
        id=uuid4(),
        assignment_id=assignment.id,
        raw_text="测试题目",
        subject="数学",
        knowledge_points=["二次方程"],
    )
    async_session.add(question)
    await async_session.commit()
    
    service = StudentProfileService(async_session)
    await service.update_profile(
        student_id="student_001",
        question_id=str(question.id),
        is_correct=True,
    )
    
    # 验证：画像被更新
    await async_session.refresh(existing_profile)
    assert existing_profile.appear_count == 6  # 5 + 1
    assert existing_profile.error_count == 2  # 没有增加
    # 掌握度使用指数移动平均更新
    assert existing_profile.mastery_score > 0.6


@pytest.mark.asyncio
async def test_update_profile_question_not_found(async_session):
    """测试：更新画像（题目不存在）"""
    service = StudentProfileService(async_session)
    
    # 不应该抛出异常，只是静默返回
    await service.update_profile(
        student_id="student_001",
        question_id=str(uuid4()),
        is_correct=True,
    )


@pytest.mark.asyncio
async def test_update_profile_no_knowledge_points(async_session):
    """测试：更新画像（题目没有知识点）"""
    # 准备：作业
    assignment = Assignment(
        id=uuid4(),
        student_id="student_001",
        file_id=f"file_{uuid4()}",
        original_filename="test.jpg",
        file_hash="hash789",
        file_size=1024,
        mime_type="image/jpeg",
        storage_url="https://example.com/test.jpg",
        status="completed",
    )
    async_session.add(assignment)
    await async_session.flush()
    
    # 准备：题目（无知识点）
    question = Question(
        id=uuid4(),
        assignment_id=assignment.id,
        raw_text="测试题目",
        knowledge_points=None,
    )
    async_session.add(question)
    await async_session.commit()
    
    service = StudentProfileService(async_session)
    
    # 不应该抛出异常，只是静默返回
    await service.update_profile(
        student_id="student_001",
        question_id=str(question.id),
        is_correct=True,
    )


@pytest.mark.asyncio
async def test_get_review_suggestions_empty(async_session):
    """测试：生成复习建议（无薄弱知识点）"""
    service = StudentProfileService(async_session)
    
    tasks = await service.get_review_suggestions("student_001", max_tasks=5)
    
    # 验证：返回空列表
    assert tasks == []


@pytest.mark.asyncio
async def test_get_review_suggestions_with_weak_points(async_session):
    """测试：生成复习建议（有薄弱知识点）"""
    # 准备：知识点
    kp1 = KnowledgePoint(
        id=uuid4(),
        name="三角函数",
        subject="数学",
        is_active=True,
    )
    kp2 = KnowledgePoint(
        id=uuid4(),
        name="立体几何",
        subject="数学",
        is_active=True,
    )
    async_session.add_all([kp1, kp2])
    await async_session.flush()
    
    # 准备：学生画像
    profile1 = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp1.id,
        appear_count=10,
        error_count=7,
        mastery_score=0.3,
        review_priority="high",
        last_reviewed_at=datetime.now(),
    )
    profile2 = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp2.id,
        appear_count=8,
        error_count=4,
        mastery_score=0.5,
        review_priority="medium",
        last_reviewed_at=datetime.now(),
    )
    async_session.add_all([profile1, profile2])
    await async_session.commit()
    
    service = StudentProfileService(async_session)
    tasks = await service.get_review_suggestions("student_001", max_tasks=5)
    
    # 验证：生成复习任务
    assert len(tasks) == 2
    
    # 验证第一个任务（掌握度最低）
    task1 = tasks[0]
    assert task1["knowledge_point"] == "三角函数"
    assert task1["priority"] == "high"
    assert task1["current_mastery"] == 0.3
    assert task1["recommended_questions"] >= 3
    assert task1["estimated_time"] > 0
    
    # 验证第二个任务
    task2 = tasks[1]
    assert task2["knowledge_point"] == "立体几何"
    assert task2["priority"] == "medium"
    assert task2["current_mastery"] == 0.5


@pytest.mark.asyncio
async def test_update_profile_mastery_score_calculation(async_session):
    """测试：掌握度计算（指数移动平均）"""
    # 准备：知识点
    kp = KnowledgePoint(
        id=uuid4(),
        name="二次方程",
        subject="数学",
        is_active=True,
    )
    async_session.add(kp)
    await async_session.flush()
    
    # 准备：已存在的画像
    existing_profile = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp.id,
        appear_count=10,
        error_count=5,
        mastery_score=0.5,
        review_priority="medium",
        last_reviewed_at=datetime.now(),
    )
    async_session.add(existing_profile)
    
    # 准备：作业
    assignment = Assignment(
        id=uuid4(),
        student_id="student_001",
        file_id=f"file_{uuid4()}",
        original_filename="test.jpg",
        file_hash="hash_mastery",
        file_size=1024,
        mime_type="image/jpeg",
        storage_url="https://example.com/test.jpg",
        status="completed",
    )
    async_session.add(assignment)
    await async_session.flush()
    
    # 准备：题目
    question = Question(
        id=uuid4(),
        assignment_id=assignment.id,
        raw_text="测试题目",
        subject="数学",
        knowledge_points=["二次方程"],
    )
    async_session.add(question)
    await async_session.commit()
    
    service = StudentProfileService(async_session)
    
    # 测试答对的情况
    await service.update_profile(
        student_id="student_001",
        question_id=str(question.id),
        is_correct=True,
    )
    
    # 验证：掌握度使用指数移动平均更新
    # new_mastery = alpha * 1.0 + (1 - alpha) * 0.5
    # alpha = 0.3, 所以 new_mastery = 0.3 * 1.0 + 0.7 * 0.5 = 0.65
    await async_session.refresh(existing_profile)
    assert abs(existing_profile.mastery_score - 0.65) < 0.01


@pytest.mark.asyncio
async def test_update_profile_review_priority_calculation(async_session):
    """测试：复习优先级计算"""
    # 准备：知识点
    kp = KnowledgePoint(
        id=uuid4(),
        name="二次方程",
        subject="数学",
        is_active=True,
    )
    async_session.add(kp)
    await async_session.flush()
    
    # 准备：低掌握度的画像
    existing_profile = StudentKnowledgeProfile(
        id=uuid4(),
        student_id="student_001",
        knowledge_point_id=kp.id,
        appear_count=10,
        error_count=8,
        mastery_score=0.2,
        review_priority="high",
        last_reviewed_at=datetime.now(),
    )
    async_session.add(existing_profile)
    
    # 准备：作业
    assignment = Assignment(
        id=uuid4(),
        student_id="student_001",
        file_id=f"file_{uuid4()}",
        original_filename="test.jpg",
        file_hash="hash_priority",
        file_size=1024,
        mime_type="image/jpeg",
        storage_url="https://example.com/test.jpg",
        status="completed",
    )
    async_session.add(assignment)
    await async_session.flush()
    
    # 准备：题目
    question = Question(
        id=uuid4(),
        assignment_id=assignment.id,
        raw_text="测试题目",
        subject="数学",
        knowledge_points=["二次方程"],
    )
    async_session.add(question)
    await async_session.commit()
    
    service = StudentProfileService(async_session)
    
    # 测试答错的情况
    await service.update_profile(
        student_id="student_001",
        question_id=str(question.id),
        is_correct=False,
    )
    
    # 验证：优先级仍然是 high（掌握度 < 0.4）
    await async_session.refresh(existing_profile)
    assert existing_profile.review_priority == "high"
    assert existing_profile.mastery_score < 0.4
