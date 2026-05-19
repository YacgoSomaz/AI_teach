"""
知识点归档服务

负责：
1. 将 AI 分析输出的知识点标准化并写入 knowledge_points 表
2. 防止同一知识点被用多种名称存储（如"一次函数"vs"线性函数"）
3. 将题目与知识点关联
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.knowledge_point import KnowledgePoint
from src.models.question import Question
from src.services.knowledge_service import KnowledgeService


class KnowledgeArchivalService:
    """
    知识点归档服务
    
    将 AI 分析输出的原始知识点名称标准化，
    查找或创建 KnowledgePoint 记录，
    并将题目与知识点关联。
    """
    
    def __init__(self, db: AsyncSession):
        """
        初始化服务
        
        Args:
            db: 数据库会话
        """
        self.db = db
        self.knowledge_service = KnowledgeService(db)
    
    async def standardize_and_archive(
        self,
        raw_knowledge_points: List[str],
        subject: str,
        grade: Optional[str] = None,
    ) -> List[KnowledgePoint]:
        """
        标准化并归档知识点
        
        Args:
            raw_knowledge_points: AI 分析输出的原始知识点列表
            subject: 学科（数学/物理/化学等）
            grade: 年级（可选）
            
        Returns:
            List[KnowledgePoint]: 标准化后的知识点列表
        """
        if not raw_knowledge_points:
            return []
        
        # 1. 标准化知识点名称（去重）
        standardized_names = await self.knowledge_service.standardize_knowledge_points(
            raw_knowledge_points
        )
        
        # 2. 查找或创建知识点记录
        knowledge_points: List[KnowledgePoint] = []
        
        for name in standardized_names:
            # 获取或创建知识点
            kp = await self.knowledge_service.get_or_create_knowledge_point(
                name=name,
                category=subject,  # 使用 subject 作为 category
                parent_id=None,  # 暂不处理父子关系
            )
            knowledge_points.append(kp)
        
        # 3. 提交事务（确保所有知识点都已持久化）
        await self.db.flush()
        
        return knowledge_points
    
    async def link_question_to_knowledge_points(
        self,
        question_id: str,
        knowledge_points: List[KnowledgePoint],
    ) -> None:
        """
        将题目与知识点关联
        
        Args:
            question_id: 题目 ID
            knowledge_points: 知识点列表
            
        Raises:
            KnowledgeArchivalException: 当题目不存在时
        """
        # 查询题目
        result = await self.db.execute(
            select(Question).where(Question.id == UUID(question_id))
        )
        question = result.scalar_one_or_none()
        
        if not question:
            raise KnowledgeArchivalException(f"Question not found: {question_id}")
        
        # 如果知识点列表为空，直接返回
        if not knowledge_points:
            return
        
        # 更新题目的 knowledge_points JSONB 字段
        # 存储知识点名称列表（去重）
        existing_points = set(question.knowledge_points or [])
        new_points = {kp.name for kp in knowledge_points}
        question.knowledge_points = list(existing_points | new_points)
        
        # 刷新到数据库（由外层调用方统一 commit）
        await self.db.flush()
    
    async def archive_and_link(
        self,
        question_id: str,
        raw_knowledge_points: List[str],
        subject: str,
        grade: Optional[str] = None,
    ) -> List[KnowledgePoint]:
        """
        一站式归档：标准化知识点 + 关联题目
        
        Args:
            question_id: 题目 ID
            raw_knowledge_points: AI 分析输出的原始知识点列表
            subject: 学科
            grade: 年级（可选）
            
        Returns:
            List[KnowledgePoint]: 标准化后的知识点列表
        """
        # 支持空 knowledge_points，不报错
        if not raw_knowledge_points:
            return []
        
        # 1. 标准化并归档知识点
        knowledge_points = await self.standardize_and_archive(
            raw_knowledge_points=raw_knowledge_points,
            subject=subject,
            grade=grade,
        )
        
        # 2. 关联题目
        await self.link_question_to_knowledge_points(
            question_id=question_id,
            knowledge_points=knowledge_points,
        )
        
        return knowledge_points


class KnowledgeArchivalException(Exception):
    """知识点归档异常"""
    pass
