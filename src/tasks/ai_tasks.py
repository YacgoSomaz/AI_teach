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
            
            # 构建分析提示词
            prompt = f"""请分析以下作业内容，识别其中的题目和知识点。

作业内容（Markdown 格式）：
{ocr_task.markdown}

请以 JSON 格式返回分析结果，格式如下：
{{
    "questions": [
        {{
            "question_text": "题目内容",
            "question_type": "选择题/填空题/解答题/判断题",
            "difficulty": "easy/medium/hard",
            "knowledge_points": ["知识点1", "知识点2"],
            "solution": "解题思路",
            "answer": "参考答案"
        }}
    ]
}}"""
            
            # 准备图片（如果有）
            images = []
            if ocr_task.images:
                for img_path, img_url in ocr_task.images.items():
                    # 将本地路径转换为可访问的 URL
                    # 这里简化处理，实际应该生成临时访问 URL
                    images.append(img_url)
            
            try:
                # 调用 AI 分析
                ai_response = provider.analyze(
                    prompt=prompt,
                    images=images[:5] if images else None,  # 最多 5 张图片
                )
                
                # 5. 解析 AI 返回结果
                try:
                    analysis_result = json.loads(ai_response)
                except json.JSONDecodeError:
                    # 如果返回不是 JSON，尝试提取 JSON 部分
                    import re
                    json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
                    if json_match:
                        analysis_result = json.loads(json_match.group())
                    else:
                        raise ValueError("AI 返回格式错误")
                
                # 6. 创建 Question 记录
                questions_data = analysis_result.get("questions", [])
                created_questions = []
                
                for idx, q_data in enumerate(questions_data):
                    question = Question(
                        assignment_id=assignment.id,
                        question_number=idx + 1,
                        question_text=q_data.get("question_text", ""),
                        question_type=q_data.get("question_type", "unknown"),
                        difficulty=q_data.get("difficulty", "medium"),
                        knowledge_points=q_data.get("knowledge_points", []),
                        solution=q_data.get("solution"),
                        answer=q_data.get("answer"),
                        image_urls=images if images else None,
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
            
            # 2. 更新学生知识点画像
            from src.models.student_profile import StudentKnowledgeProfile
            
            for kp_name in question.knowledge_points:
                # 查询或创建知识点画像
                profile_result = await db.execute(
                    select(StudentKnowledgeProfile).where(
                        StudentKnowledgeProfile.student_id == student_id,
                        StudentKnowledgeProfile.knowledge_point == kp_name,
                    )
                )
                profile = profile_result.scalar_one_or_none()
                
                if not profile:
                    # 创建新画像
                    profile = StudentKnowledgeProfile(
                        student_id=student_id,
                        knowledge_point=kp_name,
                        total_questions=1,
                        correct_questions=0,  # 默认认为是错题，后续可以标记正确
                        mastery_level=0.0,
                    )
                    db.add(profile)
                else:
                    # 更新画像
                    profile.total_questions += 1
                    # 重新计算掌握度（简化算法）
                    profile.mastery_level = profile.correct_questions / profile.total_questions
                
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
