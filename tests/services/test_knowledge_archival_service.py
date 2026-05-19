"""
知识点归档服务测试
"""

import pytest
from uuid import uuid4

from src.models.assignment import Assignment
from src.models.question import Question
from src.models.knowledge_point import KnowledgePoint
from src.services.knowledge_archival_service import (
    KnowledgeArchivalService,
    KnowledgeArchivalException,
)


@pytest.mark.asyncio
async def test_standardize_and_archive_new_knowledge_points(async_session):
    """测试：标准化并归档新知识点"""
    service = KnowledgeArchivalService(async_session)
    
    raw_points = ["一元二次方程", "解二次方程", "二次函数"]
    knowledge_points = await service.standardize_and_archive(
        raw_knowledge_points=raw_points,
        subject="数学",
        grade="九年级",
    )
    
    # 手动提交事务
    await async_session.commit()
    
    # 验证：返回的知识点数量（"一元二次方程"和"解二次方程"会被标准化为"二次方程"）
    assert len(knowledge_points) == 2  # "二次方程" 和 "二次函数"
    
    # 验证：知识点已写入数据库
    for kp in knowledge_points:
        assert kp.id is not None
        assert kp.subject == "数学"
        assert kp.name in ["二次方程", "二次函数"]


@pytest.mark.asyncio
async def test_standardize_and_archive_existing_knowledge_points(async_session):
    """测试：标准化并归档已存在的知识点"""
    # 准备：已存在的知识点
    existing_kp = KnowledgePoint(
        id=uuid4(),
        name="二次方程",
        subject="数学",
        is_active=True,
    )
    async_session.add(existing_kp)
    await async_session.commit()
    await async_session.refresh(existing_kp)  # 刷新以确保数据已持久化
    
    service = KnowledgeArchivalService(async_session)
    
    raw_points = ["一元二次方程", "二次方程"]  # 都会标准化为"二次方程"
    knowledge_points = await service.standardize_and_archive(
        raw_knowledge_points=raw_points,
        subject="数学",
    )
    
    # 手动提交事务
    await async_session.commit()
    
    # 验证：返回已存在的知识点，不创建新的
    assert len(knowledge_points) == 1
    assert knowledge_points[0].name == "二次方程"
    assert knowledge_points[0].subject == "数学"
    
    # 验证：数据库中只有一个"二次方程"知识点
    from sqlalchemy import select, func
    result = await async_session.execute(
        select(func.count()).select_from(KnowledgePoint).where(
            KnowledgePoint.name == "二次方程",
            KnowledgePoint.subject == "数学"
        )
    )
    count = result.scalar()
    assert count == 1, f"Expected 1 knowledge point, found {count}"


@pytest.mark.asyncio
async def test_standardize_and_archive_empty_list(async_session):
    """测试：空列表不报错"""
    service = KnowledgeArchivalService(async_session)
    
    knowledge_points = await service.standardize_and_archive(
        raw_knowledge_points=[],
        subject="数学",
    )
    
    assert knowledge_points == []


@pytest.mark.asyncio
async def test_link_question_to_knowledge_points(async_session):
    """测试：将题目与知识点关联"""
    # 准备：知识点
    kp1 = KnowledgePoint(
        id=uuid4(),
        name="二次方程",
        subject="数学",
        is_active=True,
    )
    kp2 = KnowledgePoint(
        id=uuid4(),
        name="二次函数",
        subject="数学",
        is_active=True,
    )
    async_session.add_all([kp1, kp2])
    
    # 准备：题目
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
    
    question = Question(
        id=uuid4(),
        assignment_id=assignment.id,
        raw_text="求解方程 x^2 - 5x + 6 = 0",
        knowledge_points=None,  # 初始为空
    )
    async_session.add(question)
    await async_session.commit()
    
    # 执行服务
    service = KnowledgeArchivalService(async_session)
    await service.link_question_to_knowledge_points(
        question_id=str(question.id),
        knowledge_points=[kp1, kp2],
    )
    
    # 手动提交事务
    await async_session.commit()
    
    # 验证：题目的 knowledge_points 字段已更新
    await async_session.refresh(question)
    assert set(question.knowledge_points) == {"二次方程", "二次函数"}


@pytest.mark.asyncio
async def test_link_question_prevents_duplicates(async_session):
    """测试：防止重复知识点重复写入"""
    # 准备：知识点
    kp1 = KnowledgePoint(
        id=uuid4(),
        name="二次方程",
        subject="数学",
        is_active=True,
    )
    kp2 = KnowledgePoint(
        id=uuid4(),
        name="二次函数",
        subject="数学",
        is_active=True,
    )
    async_session.add_all([kp1, kp2])
    
    # 准备：题目（已有一个知识点）
    assignment = Assignment(
        id=uuid4(),
        student_id="student_002",
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
    
    question = Question(
        id=uuid4(),
        assignment_id=assignment.id,
        raw_text="综合题",
        knowledge_points=["二次方程"],  # 已有一个知识点
    )
    async_session.add(question)
    await async_session.commit()
    
    # 执行服务：添加重复的知识点
    service = KnowledgeArchivalService(async_session)
    await service.link_question_to_knowledge_points(
        question_id=str(question.id),
        knowledge_points=[kp1, kp2],  # kp1 是重复的
    )
    
    # 手动提交事务
    await async_session.commit()
    
    # 验证：不会重复添加
    await async_session.refresh(question)
    assert len(question.knowledge_points) == 2
    assert "二次方程" in question.knowledge_points
    assert "二次函数" in question.knowledge_points


@pytest.mark.asyncio
async def test_link_question_empty_knowledge_points(async_session):
    """测试：空知识点列表不报错"""
    # 准备：题目
    assignment = Assignment(
        id=uuid4(),
        student_id="student_003",
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
    
    question = Question(
        id=uuid4(),
        assignment_id=assignment.id,
        raw_text="测试题目",
        knowledge_points=None,
    )
    async_session.add(question)
    await async_session.commit()
    
    # 执行服务：空列表
    service = KnowledgeArchivalService(async_session)
    await service.link_question_to_knowledge_points(
        question_id=str(question.id),
        knowledge_points=[],
    )
    
    # 验证：不报错，knowledge_points 保持为 None
    await async_session.refresh(question)
    assert question.knowledge_points is None


@pytest.mark.asyncio
async def test_link_question_not_found(async_session):
    """测试：题目不存在时抛出异常"""
    service = KnowledgeArchivalService(async_session)
    
    with pytest.raises(KnowledgeArchivalException, match="Question not found"):
        await service.link_question_to_knowledge_points(
            question_id=str(uuid4()),  # 不存在的题目 ID
            knowledge_points=[],
        )


@pytest.mark.asyncio
async def test_archive_and_link(async_session):
    """测试：一站式归档（标准化 + 关联）"""
    # 准备：题目
    assignment = Assignment(
        id=uuid4(),
        student_id="student_004",
        file_id=f"file_{uuid4()}",
        original_filename="test.jpg",
        file_hash="hash_all",
        file_size=1024,
        mime_type="image/jpeg",
        storage_url="https://example.com/test.jpg",
        status="completed",
    )
    async_session.add(assignment)
    await async_session.flush()
    
    question = Question(
        id=uuid4(),
        assignment_id=assignment.id,
        raw_text="综合题",
        knowledge_points=None,
    )
    async_session.add(question)
    await async_session.commit()
    
    # 执行服务
    service = KnowledgeArchivalService(async_session)
    knowledge_points = await service.archive_and_link(
        question_id=str(question.id),
        raw_knowledge_points=["一元二次方程", "二次函数"],
        subject="数学",
        grade="九年级",
    )
    
    # 手动提交事务
    await async_session.commit()
    
    # 验证：知识点已创建
    assert len(knowledge_points) == 2
    kp_names = {kp.name for kp in knowledge_points}
    assert kp_names == {"二次方程", "二次函数"}
    
    # 验证：题目已关联
    await async_session.refresh(question)
    assert len(question.knowledge_points) == 2
    assert set(question.knowledge_points) == {"二次方程", "二次函数"}


@pytest.mark.asyncio
async def test_archive_and_link_empty_knowledge_points(async_session):
    """测试：一站式归档支持空知识点"""
    # 准备：题目
    assignment = Assignment(
        id=uuid4(),
        student_id="student_005",
        file_id=f"file_{uuid4()}",
        original_filename="test.jpg",
        file_hash="hash_empty",
        file_size=1024,
        mime_type="image/jpeg",
        storage_url="https://example.com/test.jpg",
        status="completed",
    )
    async_session.add(assignment)
    await async_session.flush()
    
    question = Question(
        id=uuid4(),
        assignment_id=assignment.id,
        raw_text="无知识点题目",
        knowledge_points=None,
    )
    async_session.add(question)
    await async_session.commit()
    
    # 执行服务：空知识点列表
    service = KnowledgeArchivalService(async_session)
    knowledge_points = await service.archive_and_link(
        question_id=str(question.id),
        raw_knowledge_points=[],
        subject="数学",
    )
    
    # 验证：返回空列表，不报错
    assert knowledge_points == []
    
    # 验证：题目的 knowledge_points 保持为 None
    await async_session.refresh(question)
    assert question.knowledge_points is None
