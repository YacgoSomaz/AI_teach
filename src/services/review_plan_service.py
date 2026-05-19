"""
复习计划生成服务

负责：
1. 生成每日复习计划
2. 基于学生画像推荐复习任务
3. 计算复习优先级和时间估算
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.student_profile import StudentKnowledgeProfile
from src.services.student_profile_service import StudentProfileService


@dataclass
class ReviewTaskItem:
    """复习任务项（公开契约）"""
    knowledge_point_id: str
    knowledge_point_name: str
    subject: str
    grade: Optional[str]
    mastery_score: float
    priority: str              # high / medium / low
    reason: str                # 为什么要复习
    recommended_count: int     # 建议练习题目数
    estimated_minutes: int     # 预计用时


@dataclass
class DailyReviewPlan:
    """每日复习计划"""
    student_id: str
    date: str                  # YYYY-MM-DD
    tasks: List[ReviewTaskItem]
    total_minutes: int


class ReviewPlanService:
    """
    复习计划生成服务
    
    生成每日复习计划（规则引擎，第一版）
    规则：
    1. 取掌握度 < 0.6 的知识点
    2. 按掌握度升序排序（越低越先复习）
    3. 超过 7 天未练习的权重加成
    4. 每日限 3-5 个知识点
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.student_profile_service = StudentProfileService(db)
    
    async def generate_today_plan(
        self,
        student_id: str,
        max_tasks: int = 5,
    ) -> DailyReviewPlan:
        """
        生成今日复习计划
        
        Args:
            student_id: 学生 ID
            max_tasks: 最大任务数（默认 5）
        
        Returns:
            DailyReviewPlan: 今日复习计划
        """
        # 1. 获取薄弱知识点（掌握度 < 0.6）
        result = await self.db.execute(
            select(StudentKnowledgeProfile)
            .options(selectinload(StudentKnowledgeProfile.knowledge_point))
            .where(
                StudentKnowledgeProfile.student_id == student_id,
                StudentKnowledgeProfile.mastery_score < 0.6,
            )
            .order_by(StudentKnowledgeProfile.mastery_score.asc())
        )
        weak_profiles = list(result.scalars().all())
        
        if not weak_profiles:
            # 没有薄弱知识点，返回空计划
            return DailyReviewPlan(
                student_id=student_id,
                date=datetime.now().date().isoformat(),
                tasks=[],
                total_minutes=0,
            )
        
        # 2. 计算每个知识点的复习权重
        weighted_profiles = []
        from datetime import timezone
        now = datetime.now(timezone.utc)
        
        for profile in weak_profiles:
            # 基础权重：掌握度越低，权重越高
            base_weight = 1.0 - profile.mastery_score
            
            # 时间权重：超过 7 天未复习，权重加成
            time_weight = 1.0
            if profile.last_reviewed_at:
                # 确保 last_reviewed_at 有时区信息
                last_reviewed = profile.last_reviewed_at
                if last_reviewed.tzinfo is None:
                    last_reviewed = last_reviewed.replace(tzinfo=timezone.utc)
                days_since_review = (now - last_reviewed).days
                if days_since_review > 7:
                    # 每超过 7 天，权重增加 20%
                    time_weight = 1.0 + (days_since_review - 7) * 0.2
            else:
                # 从未复习过，权重加成 50%
                time_weight = 1.5
            
            # 综合权重
            total_weight = base_weight * time_weight
            
            weighted_profiles.append({
                "profile": profile,
                "weight": total_weight,
            })
        
        # 3. 按权重降序排序，取前 max_tasks 个
        weighted_profiles.sort(key=lambda x: x["weight"], reverse=True)
        selected_profiles = weighted_profiles[:max_tasks]
        
        # 4. 生成复习任务
        tasks = []
        total_minutes = 0
        
        for item in selected_profiles:
            profile = item["profile"]
            kp = profile.knowledge_point
            
            # 计算推荐题目数（掌握度越低，推荐越多）
            recommended_count = self._calculate_recommended_count(profile.mastery_score)
            
            # 估算时间（每题 3 分钟）
            estimated_minutes = recommended_count * 3
            total_minutes += estimated_minutes
            
            # 生成复习原因
            reason = self._generate_reason(profile)
            
            task = ReviewTaskItem(
                knowledge_point_id=str(profile.knowledge_point_id),
                knowledge_point_name=kp.name,
                subject=kp.subject,
                grade=kp.grade,
                mastery_score=profile.mastery_score,
                priority=profile.review_priority,
                reason=reason,
                recommended_count=recommended_count,
                estimated_minutes=estimated_minutes,
            )
            tasks.append(task)
        
        return DailyReviewPlan(
            student_id=student_id,
            date=datetime.now().date().isoformat(),
            tasks=tasks,
            total_minutes=total_minutes,
        )
    
    def _calculate_recommended_count(self, mastery_score: float) -> int:
        """
        计算推荐题目数
        
        Args:
            mastery_score: 掌握度分数 (0-1)
        
        Returns:
            int: 推荐题目数
        """
        # 掌握度越低，推荐越多题目
        # mastery_score = 0.0 → 10 题
        # mastery_score = 0.3 → 7 题
        # mastery_score = 0.6 → 4 题
        count = max(3, int((1 - mastery_score) * 10))
        return min(count, 10)  # 最多 10 题
    
    def _generate_reason(self, profile: StudentKnowledgeProfile) -> str:
        """
        生成复习原因
        
        Args:
            profile: 学生知识点画像
        
        Returns:
            str: 复习原因
        """
        from datetime import timezone
        mastery_score = profile.mastery_score
        error_rate = profile.error_count / profile.appear_count if profile.appear_count > 0 else 0
        
        reasons = []
        
        # 掌握度低
        if mastery_score < 0.4:
            reasons.append(f"掌握度较低（{mastery_score:.0%}）")
        elif mastery_score < 0.6:
            reasons.append(f"掌握度一般（{mastery_score:.0%}）")
        
        # 错误率高
        if error_rate > 0.5:
            reasons.append(f"错误率较高（{error_rate:.0%}）")
        
        # 长时间未复习
        if profile.last_reviewed_at:
            last_reviewed = profile.last_reviewed_at
            if last_reviewed.tzinfo is None:
                last_reviewed = last_reviewed.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            days_since_review = (now - last_reviewed).days
            if days_since_review > 14:
                reasons.append(f"已 {days_since_review} 天未复习")
            elif days_since_review > 7:
                reasons.append(f"已 {days_since_review} 天未复习")
        else:
            reasons.append("尚未复习过")
        
        if not reasons:
            reasons.append("需要巩固")
        
        return "，".join(reasons)
    
    async def get_review_history(
        self,
        student_id: str,
        days: int = 30,
    ) -> List[dict]:
        """
        获取复习历史（最近 N 天）
        
        Args:
            student_id: 学生 ID
            days: 天数
        
        Returns:
            List[dict]: 复习历史列表
        """
        start_date = datetime.now() - timedelta(days=days)
        
        result = await self.db.execute(
            select(StudentKnowledgeProfile)
            .options(selectinload(StudentKnowledgeProfile.knowledge_point))
            .where(
                StudentKnowledgeProfile.student_id == student_id,
                StudentKnowledgeProfile.last_reviewed_at >= start_date,
            )
            .order_by(StudentKnowledgeProfile.last_reviewed_at.desc())
        )
        profiles = list(result.scalars().all())
        
        history = []
        for profile in profiles:
            history.append({
                "knowledge_point": profile.knowledge_point.name,
                "reviewed_at": profile.last_reviewed_at.isoformat() if profile.last_reviewed_at else None,
                "mastery_score": profile.mastery_score,
                "appear_count": profile.appear_count,
                "error_count": profile.error_count,
            })
        
        return history
