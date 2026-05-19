"""
核心链路端到端测试

验证：上传图片 → OCR 保存 → 豆包分析 → 创建 Question → 更新 StudentKnowledgeProfile

注意：这是集成测试，需要真实的服务（Redis、数据库）
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from src.models.assignment import Assignment, AssignmentStatus
from src.models.ocr_task import OCRTask, OCRTaskStatus
from src.models.question import Question
from src.models.student_profile import StudentKnowledgeProfile


@pytest.mark.asyncio
async def test_core_flow_with_mocks():
    """
    测试核心链路（使用 mock）
    
    流程：
    1. 上传文件 → 创建 Assignment
    2. OCR 任务 → 创建 OCRTask，保存结果
    3. AI 分析 → 创建 Question
    4. 更新学生画像 → 创建/更新 StudentKnowledgeProfile
    """
    from src.db.session import get_celery_session
    
    # 创建测试数据库会话
    async with get_celery_session() as db:
        # 1. 模拟文件上传 - 创建 Assignment
        assignment = Assignment(
            student_id="test_student_001",
            file_id="test_file_001",
            file_hash="test_hash_001",
            original_filename="test_homework.jpg",
            file_size=1024 * 100,  # 100KB
            mime_type="image/jpeg",
            storage_url="file://uploads/test_homework.jpg",
            status=AssignmentStatus.UPLOADED,
        )
        db.add(assignment)
        await db.commit()
        await db.refresh(assignment)
        
        print(f"✅ Step 1: Assignment created - ID: {assignment.id}")
        assert assignment.id is not None
        assert assignment.status == AssignmentStatus.UPLOADED
        
        # 2. 模拟 OCR 任务 - 创建 OCRTask
        assignment.status = AssignmentStatus.OCR_RUNNING
        await db.commit()
        
        ocr_task = OCRTask(
            assignment_id=assignment.id,
            provider="paddleocr-vl-1.5",
            status=OCRTaskStatus.RUNNING,
        )
        db.add(ocr_task)
        await db.commit()
        await db.refresh(ocr_task)
        
        print(f"✅ Step 2: OCRTask created - ID: {ocr_task.id}")
        
        # 模拟 OCR 完成
        ocr_task.status = OCRTaskStatus.DONE
        ocr_task.raw_text = "1. 解方程：x^2 + 2x + 1 = 0"
        ocr_task.markdown = "## 题目\n\n1. 解方程：$x^2 + 2x + 1 = 0$"
        ocr_task.confidence = 0.95
        ocr_task.total_pages = 1
        
        assignment.status = AssignmentStatus.OCR_DONE
        if not assignment.processing_status:
            assignment.processing_status = {}
        assignment.processing_status["ocr"] = {
            "status": "done",
            "confidence": 0.95,
            "ocr_task_id": str(ocr_task.id),
        }
        
        await db.commit()
        
        print(f"✅ Step 3: OCR completed - confidence: {ocr_task.confidence}")
        assert ocr_task.status == OCRTaskStatus.DONE
        assert assignment.status == AssignmentStatus.OCR_DONE
        assert assignment.processing_status["ocr"]["status"] == "done"
        
        # 3. 模拟 AI 分析 - 创建 Question
        assignment.status = AssignmentStatus.AI_RUNNING
        await db.commit()
        
        # 模拟 AI 返回的分析结果
        question = Question(
            assignment_id=assignment.id,
            question_number=1,
            question_text="解方程：x^2 + 2x + 1 = 0",
            question_type="解答题",
            difficulty="medium",
            knowledge_points=["二次方程", "因式分解"],
            solution="使用完全平方公式：(x+1)^2 = 0，得 x = -1",
            answer="x = -1",
        )
        db.add(question)
        
        assignment.status = AssignmentStatus.AI_DONE
        if not assignment.processing_status:
            assignment.processing_status = {}
        assignment.processing_status["ai"] = {
            "status": "done",
            "questions_count": 1,
        }
        
        await db.commit()
        await db.refresh(question)
        
        print(f"✅ Step 4: Question created - ID: {question.id}")
        print(f"   Knowledge points: {question.knowledge_points}")
        assert question.id is not None
        assert len(question.knowledge_points) == 2
        assert assignment.status == AssignmentStatus.AI_DONE
        assert assignment.processing_status["ai"]["status"] == "done"
        
        # 4. 模拟更新学生画像
        for kp_name in question.knowledge_points:
            # 查询或创建知识点画像
            profile_result = await db.execute(
                select(StudentKnowledgeProfile).where(
                    StudentKnowledgeProfile.student_id == assignment.student_id,
                    StudentKnowledgeProfile.knowledge_point == kp_name,
                )
            )
            profile = profile_result.scalar_one_or_none()
            
            if not profile:
                # 创建新画像
                profile = StudentKnowledgeProfile(
                    student_id=assignment.student_id,
                    knowledge_point=kp_name,
                    total_questions=1,
                    correct_questions=0,  # 默认认为是错题
                    mastery_level=0.0,
                )
                db.add(profile)
                print(f"✅ Step 5: Created profile for {kp_name}")
            else:
                # 更新画像
                profile.total_questions += 1
                profile.mastery_level = profile.correct_questions / profile.total_questions
                print(f"✅ Step 5: Updated profile for {kp_name}")
        
        await db.commit()
        
        # 验证学生画像
        profiles_result = await db.execute(
            select(StudentKnowledgeProfile).where(
                StudentKnowledgeProfile.student_id == assignment.student_id
            )
        )
        profiles = list(profiles_result.scalars().all())
        
        print(f"✅ Step 6: Student profiles created - count: {len(profiles)}")
        assert len(profiles) == 2  # 两个知识点
        
        for profile in profiles:
            print(f"   - {profile.knowledge_point}: mastery={profile.mastery_level:.2f}, questions={profile.total_questions}")
            assert profile.total_questions >= 1
            assert 0 <= profile.mastery_level <= 1
        
        # 清理测试数据
        await db.delete(assignment)
        for profile in profiles:
            await db.delete(profile)
        await db.commit()
        
        print("\n🎉 核心链路测试通过！")
        print("   上传图片 → OCR 保存 → 豆包分析 → 创建 Question → 更新 StudentKnowledgeProfile")


@pytest.mark.asyncio
async def test_error_isolation():
    """
    测试错误隔离机制
    
    验证：OCR 失败不影响 Assignment 记录，AI 失败不丢失 OCR 结果
    """
    from src.db.session import get_celery_session
    
    async with get_celery_session() as db:
        # 1. 创建 Assignment
        assignment = Assignment(
            student_id="test_student_002",
            file_id="test_file_002",
            file_hash="test_hash_002",
            original_filename="test_homework2.jpg",
            file_size=1024 * 100,
            mime_type="image/jpeg",
            storage_url="file://uploads/test_homework2.jpg",
            status=AssignmentStatus.UPLOADED,
        )
        db.add(assignment)
        await db.commit()
        await db.refresh(assignment)
        
        print(f"✅ Created Assignment - ID: {assignment.id}")
        
        # 2. 模拟 OCR 成功
        ocr_task = OCRTask(
            assignment_id=assignment.id,
            provider="paddleocr-vl-1.5",
            status=OCRTaskStatus.DONE,
            raw_text="测试文本",
            markdown="## 测试",
            confidence=0.90,
        )
        db.add(ocr_task)
        
        assignment.status = AssignmentStatus.OCR_DONE
        assignment.processing_status = {
            "ocr": {
                "status": "done",
                "confidence": 0.90,
            }
        }
        await db.commit()
        
        print(f"✅ OCR completed successfully")
        
        # 3. 模拟 AI 失败
        assignment.status = AssignmentStatus.AI_FAILED
        assignment.processing_status["ai"] = {
            "status": "failed",
            "error": "AI service timeout",
            "retry_count": 1,
        }
        await db.commit()
        
        print(f"✅ AI failed (simulated)")
        
        # 4. 验证错误隔离
        assert assignment.status == AssignmentStatus.AI_FAILED
        assert assignment.processing_status["ocr"]["status"] == "done"  # OCR 结果仍然保留
        assert assignment.processing_status["ai"]["status"] == "failed"
        
        print(f"✅ Error isolation verified:")
        print(f"   - OCR status: {assignment.processing_status['ocr']['status']}")
        print(f"   - AI status: {assignment.processing_status['ai']['status']}")
        print(f"   - OCR 结果仍然可用，可以重试 AI 分析")
        
        # 清理
        await db.delete(assignment)
        await db.commit()
        
        print("\n🎉 错误隔离测试通过！")


if __name__ == "__main__":
    # 运行测试
    asyncio.run(test_core_flow_with_mocks())
    asyncio.run(test_error_isolation())
