"""
核心链路端到端测试

验证：上传图片 → OCR 保存 → AI 分析 → 创建 Question → 知识点归档 → 更新 StudentKnowledgeProfile

注意：这是集成测试，需要真实的服务（数据库）
"""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.models.assignment import Assignment, AssignmentStatus
from src.models.ocr_task import OCRTask, OCRTaskStatus
from src.models.question import Question
from src.models.knowledge_point import KnowledgePoint
from src.models.student_profile import StudentKnowledgeProfile


@pytest.fixture
async def db_session():
    """提供数据库会话的 fixture"""
    from src.db.session import get_celery_session
    
    async with get_celery_session() as session:
        yield session


@pytest.mark.asyncio
async def test_core_flow_with_mocks():
    """
    测试核心链路（使用 mock）
    
    流程：
    1. 上传文件 → 创建 Assignment
    2. OCR 任务 → 创建 OCRTask，保存结果
    3. AI 分析 → 创建 Question
    4. 知识点归档 → 创建 KnowledgePoint
    5. 更新学生画像 → 创建/更新 StudentKnowledgeProfile
    """
    from src.db.session import get_celery_session
    
    # 使用唯一 ID 避免冲突
    test_id = str(uuid4())[:8]
    
    # 创建测试数据库会话
    async with get_celery_session() as db:
        # 1. 模拟文件上传 - 创建 Assignment
        assignment = Assignment(
            student_id=f"test_student_{test_id}",
            file_id=f"test_file_{test_id}",
            file_hash=f"test_hash_{test_id}",
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
        
        # 3. 模拟 AI 分析 - 创建 Question（使用正确的 schema）
        assignment.status = AssignmentStatus.AI_RUNNING
        await db.commit()
        
        # 模拟 AI 返回的分析结果
        question = Question(
            assignment_id=assignment.id,
            raw_text="解方程：x^2 + 2x + 1 = 0",
            markdown="## 题目\n\n解方程：$x^2 + 2x + 1 = 0$",
            image_urls=[],
            subject="数学",
            grade="九年级",
            question_type="解答题",
            knowledge_points=["二次方程", "因式分解"],
            prerequisites=["一元一次方程"],
            difficulty=3,
            likely_error_causes=["计算错误", "公式记忆不清"],
            review_priority="medium",
            need_review=True,
            ai_confidence=0.85,
            is_confirmed=False,
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
        print(f"   Subject: {question.subject}, Grade: {question.grade}")
        print(f"   Knowledge points: {question.knowledge_points}")
        assert question.id is not None
        assert len(question.knowledge_points) == 2
        assert question.subject == "数学"
        assert assignment.status == AssignmentStatus.AI_DONE
        assert assignment.processing_status["ai"]["status"] == "done"
        
        # 4. 模拟知识点归档 - 创建 KnowledgePoint
        knowledge_points = []
        for kp_name in question.knowledge_points:
            # 查询是否已存在
            kp_result = await db.execute(
                select(KnowledgePoint).where(
                    KnowledgePoint.name == kp_name,
                    KnowledgePoint.subject == question.subject,
                )
            )
            kp = kp_result.scalar_one_or_none()
            
            if not kp:
                # 创建新知识点
                kp = KnowledgePoint(
                    name=kp_name,
                    subject=question.subject,
                    grade=question.grade,
                    is_active=True,
                )
                db.add(kp)
                await db.flush()
                print(f"✅ Step 5: Created KnowledgePoint - {kp_name}")
            else:
                print(f"✅ Step 5: Found existing KnowledgePoint - {kp_name}")
            
            knowledge_points.append(kp)
        
        await db.commit()
        
        # 5. 模拟更新学生画像（使用正确的 schema）
        for kp in knowledge_points:
            # 查询或创建知识点画像
            profile_result = await db.execute(
                select(StudentKnowledgeProfile).where(
                    StudentKnowledgeProfile.student_id == assignment.student_id,
                    StudentKnowledgeProfile.knowledge_point_id == kp.id,
                )
            )
            profile = profile_result.scalar_one_or_none()
            
            if not profile:
                # 创建新画像（假设这是错题）
                profile = StudentKnowledgeProfile(
                    student_id=assignment.student_id,
                    knowledge_point_id=kp.id,
                    appear_count=1,
                    error_count=1,  # 假设是错题
                    mastery_score=0.0,  # 第一次做错，掌握度为 0
                    review_priority="high",
                )
                db.add(profile)
                print(f"✅ Step 6: Created profile for {kp.name}")
            else:
                # 更新画像
                profile.appear_count += 1
                profile.error_count += 1
                # 重新计算掌握度（简单规则）
                profile.mastery_score = max(0.0, 1.0 - (profile.error_count / profile.appear_count))
                # 更新优先级
                if profile.mastery_score < 0.4:
                    profile.review_priority = "high"
                elif profile.mastery_score < 0.6:
                    profile.review_priority = "medium"
                else:
                    profile.review_priority = "low"
                print(f"✅ Step 6: Updated profile for {kp.name}")
        
        await db.commit()
        
        # 验证学生画像
        profiles_result = await db.execute(
            select(StudentKnowledgeProfile).where(
                StudentKnowledgeProfile.student_id == assignment.student_id
            )
        )
        profiles = list(profiles_result.scalars().all())
        
        print(f"✅ Step 7: Student profiles created - count: {len(profiles)}")
        assert len(profiles) == 2  # 两个知识点
        
        for profile in profiles:
            print(f"   - KP ID: {profile.knowledge_point_id}")
            print(f"     mastery={profile.mastery_score:.2f}, appear={profile.appear_count}, error={profile.error_count}")
            print(f"     priority={profile.review_priority}")
            assert profile.appear_count >= 1
            assert 0 <= profile.mastery_score <= 1
            assert profile.review_priority in ["high", "medium", "low"]
        
        # 清理测试数据（只删除本次创建的，不删除已存在的 knowledge_points）
        for profile in profiles:
            await db.delete(profile)
        await db.delete(question)
        await db.delete(ocr_task)
        await db.delete(assignment)
        await db.commit()
        
        print("\n🎉 核心链路测试通过！")
        print("   上传图片 → OCR 保存 → AI 分析 → 创建 Question → 知识点归档 → 更新 StudentKnowledgeProfile")
        print(f"\n注意：知识点 {[kp.name for kp in knowledge_points]} 已保留在数据库中供后续测试使用")




if __name__ == "__main__":
    # 运行测试
    asyncio.run(test_core_flow_with_mocks())

