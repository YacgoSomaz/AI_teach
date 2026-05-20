"""
AI 分析异步任务

负责：
1. 获取 OCR 结果
2. 调用豆包 Seed1.8 分析题目
3. 提取知识点
4. 创建 Question 记录
5. 发布 AI 完成事件（解耦）

设计改进：
- 使用统一数据库连接（共享引擎）
- 使用统一配置管理
- 错误隔离：AI 失败不影响 OCR 结果
- 事件驱动：发布事件而非直接调用下游任务
"""

import asyncio
import json
from uuid import UUID

from celery import Task
from sqlalchemy import select

from src.celery_app import app
from src.config import settings
from src.db.session import get_celery_session
from src.models.assignment import Assignment, AssignmentStatus
from src.models.ocr_task import OCRTask as OCRTaskModel
from src.models.question import Question
from src.models.student_profile import StudentKnowledgeProfile
from src.services.ai_analysis_service import DoubaoSeedProvider


class AIAnalysisTask(Task):
    """AI 分析任务基类"""
    
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """任务失败回调"""
        print(f"AI 分析任务失败: {task_id}, 错误: {exc}")


@app.task(base=AIAnalysisTask, bind=True, max_retries=settings.celery_max_retries)
def process_ai_analysis(self, assignment_id: str):
    """
    处理 AI 分析任务
    
    Args:
        assignment_id: 作业 ID
    
    流程：
    1. 更新 Assignment 状态为 ai_running
    2. 获取 OCR 结果
    3. 调用豆包 Seed1.8 分析题目
    4. 解析 AI 返回的知识点
    5. 创建 Question 记录
    6. 更新状态为 ai_done
    7. 发布 AI 完成事件（解耦）
    """
    return asyncio.run(_process_ai_analysis_async(self, assignment_id))


async def _process_ai_analysis_async(task, assignment_id: str):
    """异步 AI 分析处理逻辑"""
    assignment = None  # 初始化 assignment 变量
    async with get_celery_session() as db:
        try:
            # 1. 查询 Assignment 和 OCRTask
            result = await db.execute(
                select(Assignment).where(Assignment.id == UUID(assignment_id))
            )
            assignment = result.scalar_one_or_none()
            
            if not assignment:
                raise ValueError(f"Assignment {assignment_id} 不存在")
            
            # 2. 更新状态为 ai_running
            assignment.status = AssignmentStatus.AI_RUNNING
            await db.commit()
            
            # 3. 获取 OCR 结果
            ocr_result = await db.execute(
                select(OCRTaskModel)
                .where(OCRTaskModel.assignment_id == assignment.id)
                .order_by(OCRTaskModel.created_at.desc())
            )
            ocr_task = ocr_result.scalar_one_or_none()
            
            if not ocr_task or not ocr_task.markdown:
                raise ValueError("OCR 结果不存在")
            
            # 4. 调用豆包 Seed1.8 分析
            settings.validate_required_for_ai()  # 校验配置
            
            provider = DoubaoSeedProvider(
                api_key=settings.doubao_seed_api_key,
                model=settings.doubao_seed_model,
                base_url=settings.doubao_seed_base_url,
            )
            
            # 准备图片：把原始上传图片转为 base64 data URI 传给 AI
            images = []
            storage_url = assignment.storage_url or ""
            # 本地文件路径（file:// 前缀或绝对路径）
            local_path = storage_url.removeprefix("file://")
            if local_path and __import__("os").path.isfile(local_path):
                import base64, mimetypes
                mime = assignment.mime_type or mimetypes.guess_type(local_path)[0] or "image/jpeg"
                with open(local_path, "rb") as _f:
                    _b64 = base64.b64encode(_f.read()).decode()
                images.append(f"data:{mime};base64,{_b64}")
            
            try:
                # 记录 AI 分析开始时间
                import time
                import logging
                logger = logging.getLogger(__name__)
                
                ai_start_time = time.time()
                logger.info(f"AI 分析开始 - assignment_id={assignment_id}")
                
                # 调用 AI 分析（使用 analyze_question 方法）
                analysis_result = provider.analyze_question(
                    question_text=ocr_task.raw_text or "",
                    question_markdown=ocr_task.markdown,
                    image_urls=images[:5] if images else None,  # 最多 5 张图片
                )
                
                # 记录 AI 分析结束时间和耗时
                ai_end_time = time.time()
                ai_duration = ai_end_time - ai_start_time
                logger.info(
                    f"AI 分析完成 - assignment_id={assignment_id}, "
                    f"耗时={ai_duration:.2f}秒"
                )
                
                # analyze_question 已经返回解析好的字典，不需要再解析 JSON
                # 但为了兼容旧的 prompt 格式，我们需要调整返回结构
                # 假设 AI 返回的是单个题目的分析，我们需要包装成 questions 数组
                questions_data = [{
                    "question_text": ocr_task.raw_text or ocr_task.markdown,
                    "question_type": analysis_result.get("question_type", "unknown"),
                    "difficulty": analysis_result.get("difficulty", 3),
                    "knowledge_points": analysis_result.get("knowledge_points", []),
                    "subject": analysis_result.get("subject"),
                    "grade": analysis_result.get("grade"),
                }]
                created_questions = []
                
                for idx, q_data in enumerate(questions_data):
                    # AI 返回整数 1-5，兼容旧字符串格式
                    raw_diff = q_data.get("difficulty", 3)
                    if isinstance(raw_diff, str):
                        difficulty_int = {"easy": 1, "medium": 3, "hard": 5}.get(raw_diff, 3)
                    else:
                        difficulty_int = int(raw_diff)
                    
                    question = Question(
                        assignment_id=assignment.id,
                        raw_text=q_data.get("question_text", ""),  # 使用 raw_text
                        markdown=q_data.get("question_text", ""),  # 使用 markdown
                        question_type=q_data.get("question_type", "unknown"),
                        difficulty=difficulty_int,  # 使用整数
                        knowledge_points=q_data.get("knowledge_points", []),  # JSON 数组
                        image_urls=images if images else None,
                        subject=q_data.get("subject"),  # 学科
                        grade=q_data.get("grade"),  # 年级
                        need_review=True,  # 默认需要复习
                        review_priority="medium",  # 默认中等优先级
                    )
                    db.add(question)
                    created_questions.append(question)
                
                # 7. 更新 Assignment 状态（部分成功）
                assignment.status = AssignmentStatus.AI_DONE
                # 使用 processing_status 记录各环节状态（错误隔离）
                if not assignment.processing_status:
                    assignment.processing_status = {}
                assignment.processing_status["ai"] = {
                    "status": "done",
                    "questions_count": len(created_questions),
                }
                
                await db.commit()
                
                # 8. 发布 AI 完成事件（解耦）
                for question in created_questions:
                    await db.refresh(question)
                    update_student_profile.delay(
                        student_id=assignment.student_id,
                        question_id=str(question.id),
                    )
                
                return {
                    "success": True,
                    "assignment_id": assignment_id,
                    "questions_count": len(created_questions),
                    "questions": [str(q.id) for q in created_questions],
                }
                
            except Exception as e:
                # AI 分析失败（错误隔离：不影响 OCR 结果）
                if not assignment.processing_status:
                    assignment.processing_status = {}
                assignment.processing_status["ai"] = {
                    "status": "failed",
                    "error": str(e),
                    "retry_count": task.request.retries,
                }
                assignment.status = AssignmentStatus.AI_FAILED
                
                await db.commit()
                
                # 重试
                if task.request.retries < task.max_retries:
                    raise task.retry(exc=e, countdown=120)  # 2分钟后重试
                
                raise
        
        except Exception as e:
            # 其他错误
            if assignment:
                if not assignment.processing_status:
                    assignment.processing_status = {}
                assignment.processing_status["ai"] = {
                    "status": "error",
                    "error": str(e),
                }
                assignment.status = AssignmentStatus.AI_FAILED
                assignment.retry_count += 1
                await db.commit()
            
            raise


@app.task
def update_student_profile(student_id: str, question_id: str):
    """
    更新学生画像
    
    Args:
        student_id: 学生 ID
        question_id: 题目 ID
    
    流程：
    1. 获取题目的知识点
    2. 更新学生知识点掌握度
    3. 识别薄弱知识点
    """
    return asyncio.run(_update_student_profile_async(student_id, question_id))


async def _update_student_profile_async(student_id: str, question_id: str):
    """异步更新学生画像"""
    async with get_celery_session() as db:
        try:
            # 1. 获取题目
            result = await db.execute(
                select(Question).where(Question.id == UUID(question_id))
            )
            question = result.scalar_one_or_none()
            
            if not question or not question.knowledge_points:
                return {"success": False, "message": "题目或知识点不存在"}
            
            # 2. 导入知识点服务
            from src.models.knowledge_point import KnowledgePoint
            from src.services.knowledge_service import KnowledgeService
            
            knowledge_service = KnowledgeService(db)
            
            # 3. 遍历知识点
            for kp_name in question.knowledge_points:
                # 3.1 标准化知识点名称
                std_name = await knowledge_service.standardize_knowledge_point(kp_name)
                
                # 3.2 获取或创建 KnowledgePoint
                kp = await knowledge_service.get_or_create_knowledge_point(
                    name=std_name,
                    category=question.subject,  # 使用题目的学科作为分类
                )
                
                # 3.3 查询或创建 StudentKnowledgeProfile
                profile_result = await db.execute(
                    select(StudentKnowledgeProfile).where(
                        StudentKnowledgeProfile.student_id == student_id,
                        StudentKnowledgeProfile.knowledge_point_id == kp.id,
                    )
                )
                profile = profile_result.scalar_one_or_none()
                
                if not profile:
                    # 创建新画像
                    from datetime import datetime, timezone
                    profile = StudentKnowledgeProfile(
                        student_id=student_id,
                        knowledge_point_id=kp.id,
                        appear_count=1,
                        error_count=1,  # 默认认为是错题
                        mastery_score=0.3,  # 初始掌握度较低
                        review_priority="high",  # 高优先级复习
                        last_error_at=datetime.now(timezone.utc),
                    )
                    db.add(profile)
                else:
                    # 更新画像
                    from datetime import datetime, timezone
                    profile.appear_count += 1
                    profile.error_count += 1
                    profile.last_error_at = datetime.now(timezone.utc)
                    
                    # 重新计算掌握度（简化算法：1 - 错误率）
                    error_rate = profile.error_count / profile.appear_count
                    profile.mastery_score = max(0.0, 1.0 - error_rate)
                    
                    # 更新复习优先级
                    if profile.mastery_score < 0.5:
                        profile.review_priority = "high"
                    elif profile.mastery_score < 0.8:
                        profile.review_priority = "medium"
                    else:
                        profile.review_priority = "low"
                
                await db.commit()
            
            return {
                "success": True,
                "student_id": student_id,
                "question_id": question_id,
                "knowledge_points": question.knowledge_points,
            }
        
        except Exception as e:
            print(f"更新学生画像失败: {e}")
            raise
