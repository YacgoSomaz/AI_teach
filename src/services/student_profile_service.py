"""
学生画像服务

负责：
1. 学生知识点掌握度计算
2. 画像更新逻辑
3. 薄弱知识点识别
4. 学习进度统计
"""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.question import Question
from src.models.student_profile import StudentKnowledgeProfile
from src.models.knowledge_point import KnowledgePoint
from src.services.knowledge_service import KnowledgeService


class StudentProfileService:
    """学生画像服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.knowledge_service = KnowledgeService(db)
    
    async def get_profile(self, student_id: str) -> dict:
        """
        获取学生完整画像
        
        Args:
            student_id: 学生 ID
        
        Returns:
            dict: 学生画像数据
        """
        # 查询所有知识点画像（预加载 knowledge_point 关系）
        result = await self.db.execute(
            select(StudentKnowledgeProfile)
            .options(selectinload(StudentKnowledgeProfile.knowledge_point))
            .where(StudentKnowledgeProfile.student_id == student_id)
            .order_by(StudentKnowledgeProfile.mastery_score.asc())
        )
        profiles = list(result.scalars().all())
        
        if not profiles:
            return {
                "student_id": student_id,
                "total_questions": 0,
                "correct_rate": 0.0,
                "knowledge_points": [],
                "weak_points": [],
                "updated_at": datetime.now().isoformat(),
            }
        
        # 统计总题目数和正确率
        total_questions = sum(p.appear_count for p in profiles)
        total_correct = sum(p.appear_count - p.error_count for p in profiles)
        correct_rate = total_correct / total_questions if total_questions > 0 else 0.0
        
        # 构建知识点列表
        knowledge_points = [
            {
                "name": p.knowledge_point.name,
                "mastery_score": p.mastery_score,
                "question_count": p.appear_count,
                "error_count": p.error_count,
                "last_reviewed": p.last_reviewed_at.isoformat() if p.last_reviewed_at else None,
                "review_priority": p.review_priority,
            }
            for p in profiles
        ]
        
        # 识别薄弱知识点（掌握度 < 0.6）
        weak_points = [
            p.knowledge_point.name
            for p in profiles
            if p.mastery_score < 0.6
        ]
        
        return {
            "student_id": student_id,
            "total_questions": total_questions,
            "correct_rate": correct_rate,
            "knowledge_points": knowledge_points,
            "weak_points": weak_points,
            "updated_at": datetime.now().isoformat(),
        }
    
    async def get_weak_points(
        self,
        student_id: str,
        limit: int = 5,
        threshold: float = 0.6
    ) -> List[dict]:
        """
        获取学生薄弱知识点
        
        Args:
            student_id: 学生 ID
            limit: 返回数量限制
            threshold: 掌握度阈值（低于此值认为薄弱）
        
        Returns:
            List[dict]: 薄弱知识点列表
        """
        result = await self.db.execute(
            select(StudentKnowledgeProfile)
            .options(selectinload(StudentKnowledgeProfile.knowledge_point))
            .where(
                StudentKnowledgeProfile.student_id == student_id,
                StudentKnowledgeProfile.mastery_score < threshold,
            )
            .order_by(StudentKnowledgeProfile.mastery_score.asc())
            .limit(limit)
        )
        profiles = list(result.scalars().all())
        
        return [
            {
                "knowledge_point": p.knowledge_point.name,
                "mastery_score": p.mastery_score,
                "question_count": p.appear_count,
                "error_count": p.error_count,
                "last_reviewed": p.last_reviewed_at.isoformat() if p.last_reviewed_at else None,
                "review_priority": p.review_priority,
            }
            for p in profiles
        ]
    
    async def get_progress(
        self,
        student_id: str,
        days: int = 30
    ) -> dict:
        """
        获取学生学习进度（最近 N 天）
        
        Args:
            student_id: 学生 ID
            days: 天数
        
        Returns:
            dict: 学习进度数据
        """
        start_date = datetime.now() - timedelta(days=days)
        
        # 查询最近 N 天的题目
        result = await self.db.execute(
            select(Question)
            .join(Question.assignment)
            .where(
                Question.assignment.has(student_id=student_id),
                Question.created_at >= start_date,
            )
            .order_by(Question.created_at.asc())
        )
        questions = list(result.scalars().all())
        
        if not questions:
            return {
                "student_id": student_id,
                "period": f"{days} days",
                "total_questions": 0,
                "correct_rate": 0.0,
                "daily_stats": [],
            }
        
        # 统计每日数据
        daily_stats = {}
        for q in questions:
            date_key = q.created_at.date().isoformat()
            if date_key not in daily_stats:
                daily_stats[date_key] = {"questions": 0, "correct": 0}
            
            daily_stats[date_key]["questions"] += 1
            # 使用 is_correct 属性（如果存在）
            if hasattr(q, 'is_correct') and q.is_correct:
                daily_stats[date_key]["correct"] += 1
        
        # 转换为列表
        daily_list = [
            {
                "date": date,
                "questions": stats["questions"],
                "correct": stats["correct"],
            }
            for date, stats in sorted(daily_stats.items())
        ]
        
        # 计算总体正确率
        total_questions = len(questions)
        total_correct = sum(1 for q in questions if hasattr(q, 'is_correct') and q.is_correct)
        correct_rate = total_correct / total_questions if total_questions > 0 else 0.0
        
        return {
            "student_id": student_id,
            "period": f"{days} days",
            "total_questions": total_questions,
            "correct_rate": correct_rate,
            "daily_stats": daily_list,
        }
    
    async def update_profile(
        self,
        student_id: str,
        question_id: str,
        is_correct: bool = False
    ) -> None:
        """
        更新学生画像（当学生完成题目时调用）
        
        Args:
            student_id: 学生 ID
            question_id: 题目 ID
            is_correct: 是否正确
        """
        # 获取题目
        result = await self.db.execute(
            select(Question).where(Question.id == UUID(question_id))
        )
        question = result.scalar_one_or_none()
        
        if not question or not question.knowledge_points:
            return
        
        # 更新题目正确性
        question.is_correct = is_correct
        
        # 更新每个知识点的画像
        for kp_name in question.knowledge_points:
            # 获取或创建 KnowledgePoint
            kp = await self.knowledge_service.get_or_create_knowledge_point(
                name=kp_name,
                category=question.subject,
            )
            
            # 查询或创建画像
            profile_result = await self.db.execute(
                select(StudentKnowledgeProfile).where(
                    StudentKnowledgeProfile.student_id == student_id,
                    StudentKnowledgeProfile.knowledge_point_id == kp.id,
                )
            )
            profile = profile_result.scalar_one_or_none()
            
            if not profile:
                # 创建新画像
                profile = StudentKnowledgeProfile(
                    student_id=student_id,
                    knowledge_point_id=kp.id,
                    appear_count=1,
                    error_count=0 if is_correct else 1,
                    mastery_score=1.0 if is_correct else 0.0,
                    review_priority="low" if is_correct else "high",
                    last_reviewed_at=datetime.now(),
                    last_error_at=datetime.now() if not is_correct else None,
                )
                self.db.add(profile)
            else:
                # 更新画像
                profile.appear_count += 1
                if not is_correct:
                    profile.error_count += 1
                    profile.last_error_at = datetime.now()
                
                # 重新计算掌握度（使用指数移动平均，给最近的表现更高权重）
                alpha = 0.3  # 平滑系数
                new_score = 1.0 if is_correct else 0.0
                profile.mastery_score = (
                    alpha * new_score + (1 - alpha) * profile.mastery_score
                )
                
                # 更新复习优先级
                if profile.mastery_score < 0.4:
                    profile.review_priority = "high"
                elif profile.mastery_score < 0.6:
                    profile.review_priority = "medium"
                else:
                    profile.review_priority = "low"
                
                profile.last_reviewed_at = datetime.now()
        
        await self.db.commit()
    
    async def get_review_suggestions(
        self,
        student_id: str,
        max_tasks: int = 5
    ) -> List[dict]:
        """
        生成复习建议
        
        Args:
            student_id: 学生 ID
            max_tasks: 最大任务数
        
        Returns:
            List[dict]: 复习任务列表
        """
        # 获取薄弱知识点
        weak_points = await self.get_weak_points(student_id, limit=max_tasks)
        
        # 生成复习任务
        tasks = []
        for idx, wp in enumerate(weak_points):
            # 计算推荐题目数（掌握度越低，推荐越多）
            recommended_questions = max(3, int((1 - wp["mastery_score"]) * 10))
            
            # 估算时间（每题 3 分钟）
            estimated_time = recommended_questions * 3
            
            tasks.append({
                "task_id": f"task_{idx + 1}",
                "knowledge_point": wp["knowledge_point"],
                "priority": wp["review_priority"],
                "reason": f"掌握度低（{wp['mastery_score']:.0%}），需要重点复习",
                "recommended_questions": recommended_questions,
                "estimated_time": estimated_time,
                "current_mastery": wp["mastery_score"],
            })
        
        return tasks
