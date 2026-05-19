"""
核心链路真实调用测试

真正调用任务函数，不只是手动创建数据库记录。

测试覆盖：
1. mock PaddleOCRAdapter.process_file
2. 调用 _process_ocr_async
3. mock DoubaoSeedProvider.analyze_question
4. 调用 _process_ai_analysis_async
5. 调用 _update_student_profile_async
6. 断言数据库里真实生成了 OCRTask、Question、StudentKnowledgeProfile
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from sqlalchemy import select

from src.models.assignment import Assignment, AssignmentStatus
from src.models.ocr_task import OCRTask as OCRTaskModel, OCRTaskStatus
from src.models.question import Question
from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile
from src.adapters.ocr.paddle_ocr_adapter import OCRResult
from src.tasks.ocr_tasks import _process_ocr_async
from src.tasks.ai_tasks import _process_ai_analysis_async, _update_student_profile_async


@pytest.fixture
def mock_ocr_result():
    """Mock OCR 结果"""
    return OCRResult(
        file_id="test_file_123",
        raw_text="求解方程 x^2 + 5x + 6 = 0",
        markdown="# 题目\n\n求解方程 $x^2 + 5x + 6 = 0$",
        images={"img1.jpg": "http://example.com/img1.jpg"},
        blocks=[],
        confidence=0.95,
        provider="paddleocr-vl-1.5",
        total_pages=1,
        extracted_pages=1,
        start_time="2024-01-01T00:00:00",
        end_time="2024-01-01T00:01:00",
        job_id="ocr_job_123",
    )


@pytest.fixture
def mock_ai_analysis():
    """Mock AI 分析结果"""
    return {
        "subject": "数学",
        "grade": "八年级",
        "question_type": "解答题",
        "knowledge_points": ["二次方程", "因式分解"],
        "prerequisites": ["一元一次方程", "乘法公式"],
        "difficulty": 3,
        "likely_error_causes": ["因式分解错误", "符号错误"],
        "review_priority": "medium",
        "need_review": True,
        "confidence": 0.9,
    }


@pytest.mark.asyncio
async def test_process_ocr_async_real_call(async_session, mock_ocr_result):
    """
    测试 1: 真实调用 _process_ocr_async
    
    Mock PaddleOCRAdapter.process_file，然后调用 _process_ocr_async
    """
    # 1. 创建 Assignment
    assignment = Assignment(
        student_id="test_student_001",
        file_id=str(uuid4()),
        file_hash="test_hash_123",
        original_filename="homework.jpg",
        file_size=2048,
        mime_type="image/jpeg",
        storage_url="file:///uploads/homework.jpg",
        status=AssignmentStatus.UPLOADED,
    )
    async_session.add(assignment)
    await async_session.commit()
    await async_session.refresh(assignment)
    
    # 2. Mock PaddleOCRAdapter.process_file
    with patch('src.tasks.ocr_tasks.PaddleOCRAdapter') as MockAdapter:
        mock_adapter_instance = MockAdapter.return_value
        mock_adapter_instance.process_file.return_value = mock_ocr_result
        
        # 3. Mock Celery task (避免真实调用 Celery)
        mock_task = MagicMock()
        mock_task.request.retries = 0
        mock_task.max_retries = 3
        
        # 4. Mock process_ai_analysis.delay to avoid Redis connection
        with patch('src.tasks.ai_tasks.process_ai_analysis.delay'):
            # 5. 调用 _process_ocr_async
            result = await _process_ocr_async(mock_task, str(assignment.id))
    
    # 5. 验证返回结果
    assert result["success"] is True
    assert result["assignment_id"] == str(assignment.id)
    assert result["confidence"] == 0.95
    
    # 6. 验证数据库中生成了 OCRTask
    ocr_result = await async_session.execute(
        select(OCRTaskModel).where(OCRTaskModel.assignment_id == assignment.id)
    )
    ocr_task = ocr_result.scalar_one_or_none()
    
    assert ocr_task is not None
    assert ocr_task.status == OCRTaskStatus.DONE
    assert ocr_task.raw_text == "求解方程 x^2 + 5x + 6 = 0"
    assert ocr_task.markdown == "# 题目\n\n求解方程 $x^2 + 5x + 6 = 0$"
    assert ocr_task.confidence == 0.95
    assert ocr_task.external_job_id == "ocr_job_123"  # 验证 job_id
    
    # 7. 验证 Assignment 状态更新
    await async_session.refresh(assignment)
    assert assignment.status == AssignmentStatus.OCR_DONE
    assert assignment.processing_status["ocr"]["status"] == "done"
    assert assignment.processing_status["ocr"]["confidence"] == 0.95
    
    print("✅ _process_ocr_async 真实调用测试通过")
    print(f"   - Assignment ID: {assignment.id}")
    print(f"   - OCR Task ID: {ocr_task.id}")
    print(f"   - OCR Job ID: {ocr_task.external_job_id}")


@pytest.mark.asyncio
async def test_process_ai_analysis_async_real_call(async_session, mock_ocr_result, mock_ai_analysis):
    """
    测试 2: 真实调用 _process_ai_analysis_async
    
    Mock DoubaoSeedProvider.analyze_question，然后调用 _process_ai_analysis_async
    """
    # 1. 创建 Assignment
    assignment = Assignment(
        student_id="test_student_002",
        file_id=str(uuid4()),
        file_hash="test_hash_456",
        original_filename="homework2.jpg",
        file_size=2048,
        mime_type="image/jpeg",
        storage_url="file:///uploads/homework2.jpg",
        status=AssignmentStatus.OCR_DONE,
    )
    async_session.add(assignment)
    await async_session.commit()
    await async_session.refresh(assignment)
    
    # 2. 创建 OCRTask
    ocr_task = OCRTaskModel(
        assignment_id=assignment.id,
        provider="paddleocr-vl-1.5",
        status=OCRTaskStatus.DONE,
        raw_text=mock_ocr_result.raw_text,
        markdown=mock_ocr_result.markdown,
        images=mock_ocr_result.images,
        confidence=mock_ocr_result.confidence,
        total_pages=mock_ocr_result.total_pages,
        external_job_id=mock_ocr_result.job_id,
    )
    async_session.add(ocr_task)
    await async_session.commit()
    
    # 3. Mock get_celery_session to use async_session
    @asynccontextmanager
    async def mock_get_celery_session():
        yield async_session
    
    # 4. Mock DoubaoSeedProvider.analyze_question
    with patch('src.tasks.ai_tasks.get_celery_session', side_effect=mock_get_celery_session):
        with patch('src.tasks.ai_tasks.DoubaoSeedProvider') as MockProvider:
            mock_provider_instance = MockProvider.return_value
            mock_provider_instance.analyze_question.return_value = mock_ai_analysis
            
            # 5. Mock Celery task
            mock_task = MagicMock()
            mock_task.request.retries = 0
            mock_task.max_retries = 3
            
            # 6. Mock update_student_profile.delay to avoid Redis connection
            with patch('src.tasks.ai_tasks.update_student_profile.delay'):
                # 7. 调用 _process_ai_analysis_async
                result = await _process_ai_analysis_async(mock_task, str(assignment.id))
    
    # 6. 验证返回结果
    assert result["success"] is True
    assert result["assignment_id"] == str(assignment.id)
    assert result["questions_count"] == 1
    
    # 7. 验证数据库中生成了 Question
    question_result = await async_session.execute(
        select(Question).where(Question.assignment_id == assignment.id)
    )
    question = question_result.scalar_one_or_none()
    
    assert question is not None
    assert question.raw_text == "求解方程 x^2 + 5x + 6 = 0"
    assert question.question_type == "解答题"
    assert question.difficulty == 3
    assert len(question.knowledge_points) == 2
    assert "二次方程" in question.knowledge_points
    assert "因式分解" in question.knowledge_points
    assert question.subject == "数学"
    assert question.grade == "八年级"
    
    # 8. 验证 Assignment 状态更新
    await async_session.refresh(assignment)
    assert assignment.status == AssignmentStatus.AI_DONE
    assert assignment.processing_status["ai"]["status"] == "done"
    assert assignment.processing_status["ai"]["questions_count"] == 1
    
    print("✅ _process_ai_analysis_async 真实调用测试通过")
    print(f"   - Assignment ID: {assignment.id}")
    print(f"   - Question ID: {question.id}")
    print(f"   - Knowledge Points: {question.knowledge_points}")


@pytest.mark.asyncio
async def test_update_student_profile_async_real_call(async_session, mock_ai_analysis):
    """
    测试 3: 真实调用 _update_student_profile_async
    
    调用 _update_student_profile_async，验证生成 StudentKnowledgeProfile
    """
    # 1. 创建 Assignment
    assignment = Assignment(
        student_id="test_student_003",
        file_id=str(uuid4()),
        file_hash="test_hash_789",
        original_filename="homework3.jpg",
        file_size=2048,
        mime_type="image/jpeg",
        storage_url="file:///uploads/homework3.jpg",
        status=AssignmentStatus.AI_DONE,
    )
    async_session.add(assignment)
    await async_session.commit()
    await async_session.refresh(assignment)
    
    # 2. 创建 Question
    question = Question(
        assignment_id=assignment.id,
        raw_text="求解方程 x^2 + 5x + 6 = 0",
        markdown="# 题目\n\n求解方程 $x^2 + 5x + 6 = 0$",
        question_type="解答题",
        difficulty=3,
        knowledge_points=["二次方程", "因式分解"],
        subject="数学",
        grade="八年级",
        need_review=True,
        review_priority="medium",
    )
    async_session.add(question)
    await async_session.commit()
    await async_session.refresh(question)
    
    # 3. Mock get_celery_session to use async_session
    @asynccontextmanager
    async def mock_get_celery_session():
        yield async_session
    
    # 4. 调用 _update_student_profile_async
    with patch('src.tasks.ai_tasks.get_celery_session', side_effect=mock_get_celery_session):
        result = await _update_student_profile_async(
            assignment.student_id,
            str(question.id)
        )
    
    # 4. 验证返回结果
    assert result["success"] is True
    assert result["student_id"] == assignment.student_id
    assert result["question_id"] == str(question.id)
    assert len(result["knowledge_points"]) == 2
    
    # 5. 验证数据库中生成了 KnowledgePoint
    kp_result = await async_session.execute(
        select(KnowledgePoint).where(KnowledgePoint.subject == "数学")
    )
    knowledge_points = kp_result.scalars().all()
    assert len(knowledge_points) >= 2
    
    kp_names = [kp.name for kp in knowledge_points]
    assert "二次方程" in kp_names
    
    # 6. 验证数据库中生成了 StudentKnowledgeProfile
    profile_result = await async_session.execute(
        select(StudentKnowledgeProfile).where(
            StudentKnowledgeProfile.student_id == assignment.student_id
        )
    )
    profiles = profile_result.scalars().all()
    assert len(profiles) == 2
    
    for profile in profiles:
        assert profile.appear_count == 1
        assert profile.error_count == 1
        assert profile.mastery_score == 0.3
        assert profile.review_priority == "high"
        assert profile.last_error_at is not None
    
    print("✅ _update_student_profile_async 真实调用测试通过")
    print(f"   - Student ID: {assignment.student_id}")
    print(f"   - Question ID: {question.id}")
    print(f"   - Knowledge Points: {len(knowledge_points)} 个")
    print(f"   - Student Profiles: {len(profiles)} 条记录")


@pytest.mark.asyncio
async def test_full_pipeline_real_calls(async_session, mock_ocr_result, mock_ai_analysis):
    """
    测试 4: 完整核心链路真实调用
    
    依次调用：
    1. _process_ocr_async
    2. _process_ai_analysis_async
    3. _update_student_profile_async
    
    验证数据库中生成了所有记录
    """
    # 1. 创建 Assignment
    assignment = Assignment(
        student_id="test_student_004",
        file_id=str(uuid4()),
        file_hash="test_hash_abc",
        original_filename="homework4.jpg",
        file_size=2048,
        mime_type="image/jpeg",
        storage_url="file:///uploads/homework4.jpg",
        status=AssignmentStatus.UPLOADED,
    )
    async_session.add(assignment)
    await async_session.commit()
    await async_session.refresh(assignment)
    
    # Mock get_celery_session to use async_session
    @asynccontextmanager
    async def mock_get_celery_session():
        yield async_session
    
    # 2. Mock PaddleOCRAdapter 并调用 _process_ocr_async
    with patch('src.tasks.ocr_tasks.get_celery_session', side_effect=mock_get_celery_session):
        with patch('src.tasks.ocr_tasks.PaddleOCRAdapter') as MockAdapter:
            mock_adapter_instance = MockAdapter.return_value
            mock_adapter_instance.process_file.return_value = mock_ocr_result
            
            mock_task = MagicMock()
            mock_task.request.retries = 0
            mock_task.max_retries = 3
            
            # Mock process_ai_analysis.delay to avoid Redis connection
            with patch('src.tasks.ai_tasks.process_ai_analysis.delay'):
                ocr_result = await _process_ocr_async(mock_task, str(assignment.id))
    
    assert ocr_result["success"] is True
    
    # 3. Mock DoubaoSeedProvider 并调用 _process_ai_analysis_async
    with patch('src.tasks.ai_tasks.get_celery_session', side_effect=mock_get_celery_session):
        with patch('src.tasks.ai_tasks.DoubaoSeedProvider') as MockProvider:
            mock_provider_instance = MockProvider.return_value
            mock_provider_instance.analyze_question.return_value = mock_ai_analysis
            
            mock_task = MagicMock()
            mock_task.request.retries = 0
            mock_task.max_retries = 3
            
            with patch('src.tasks.ai_tasks.update_student_profile.delay'):
                ai_result = await _process_ai_analysis_async(mock_task, str(assignment.id))
    
    assert ai_result["success"] is True
    assert ai_result["questions_count"] == 1
    
    # 4. 获取生成的 Question
    question_result = await async_session.execute(
        select(Question).where(Question.assignment_id == assignment.id)
    )
    question = question_result.scalar_one()
    
    # 5. 调用 _update_student_profile_async
    with patch('src.tasks.ai_tasks.get_celery_session', side_effect=mock_get_celery_session):
        profile_result = await _update_student_profile_async(
            assignment.student_id,
            str(question.id)
        )
    
    assert profile_result["success"] is True
    
    # 6. 验证数据库中的所有记录
    # 6.1 验证 OCRTask
    ocr_task_result = await async_session.execute(
        select(OCRTaskModel).where(OCRTaskModel.assignment_id == assignment.id)
    )
    ocr_task = ocr_task_result.scalar_one()
    assert ocr_task.status == OCRTaskStatus.DONE
    assert ocr_task.external_job_id == "ocr_job_123"
    
    # 6.2 验证 Question
    assert question.knowledge_points == ["二次方程", "因式分解"]
    assert question.subject == "数学"
    
    # 6.3 验证 KnowledgePoint
    kp_result = await async_session.execute(
        select(KnowledgePoint).where(KnowledgePoint.subject == "数学")
    )
    knowledge_points = kp_result.scalars().all()
    assert len(knowledge_points) >= 2
    
    # 6.4 验证 StudentKnowledgeProfile
    profile_query = await async_session.execute(
        select(StudentKnowledgeProfile).where(
            StudentKnowledgeProfile.student_id == assignment.student_id
        )
    )
    profiles = profile_query.scalars().all()
    assert len(profiles) == 2
    
    # 6.5 验证 Assignment 状态
    await async_session.refresh(assignment)
    assert assignment.status == AssignmentStatus.AI_DONE
    
    print("✅ 完整核心链路真实调用测试通过")
    print(f"   - Assignment: {assignment.id} ({assignment.status})")
    print(f"   - OCR Task: {ocr_task.id} (job_id: {ocr_task.external_job_id})")
    print(f"   - Question: {question.id}")
    print(f"   - Knowledge Points: {len(knowledge_points)} 个")
    print(f"   - Student Profiles: {len(profiles)} 条记录")
    print("\n🎉 核心链路完全畅通！所有任务函数真实调用成功！")


if __name__ == "__main__":
    print("运行核心链路真实调用测试...")
    print("注意：需要先启动 PostgreSQL 数据库")
    print("运行命令：pytest tests/test_core_pipeline_real_calls.py -v -s")
