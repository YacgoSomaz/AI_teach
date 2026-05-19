"""
知识点标签系统服务

负责：
1. 知识点标准化（统一命名）
2. 知识点层级关系管理
3. 知识点映射和归档
"""

from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.knowledge_point import KnowledgePoint


class KnowledgeService:
    """知识点服务"""
    
    # 知识点标准化映射表（示例）
    KNOWLEDGE_POINT_MAPPING = {
        # 代数
        "一元二次方程": "二次方程",
        "二次方程求解": "二次方程",
        "解二次方程": "二次方程",
        "一次函数": "一次函数",
        "二次函数": "二次函数",
        "反比例函数": "反比例函数",
        
        # 几何
        "三角形": "三角形",
        "直角三角形": "三角形",
        "等腰三角形": "三角形",
        "相似三角形": "三角形",
        "圆": "圆",
        "圆的性质": "圆",
        "立体几何": "立体几何",
        
        # 三角函数
        "三角函数": "三角函数",
        "正弦函数": "三角函数",
        "余弦函数": "三角函数",
        "正切函数": "三角函数",
        
        # 概率统计
        "概率": "概率",
        "统计": "统计",
        "排列组合": "排列组合",
    }
    
    # 知识点层级关系（父子关系）
    KNOWLEDGE_HIERARCHY = {
        "代数": ["二次方程", "一次函数", "二次函数", "反比例函数"],
        "几何": ["三角形", "圆", "立体几何"],
        "三角函数": ["正弦函数", "余弦函数", "正切函数"],
        "概率统计": ["概率", "统计", "排列组合"],
    }
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def standardize_knowledge_point(self, raw_point: str) -> str:
        """
        标准化知识点名称
        
        Args:
            raw_point: 原始知识点名称
        
        Returns:
            str: 标准化后的知识点名称
        """
        # 去除空格和标点
        cleaned = raw_point.strip().replace("、", "").replace("，", "")
        
        # 查找映射表
        return self.KNOWLEDGE_POINT_MAPPING.get(cleaned, cleaned)
    
    async def standardize_knowledge_points(
        self,
        raw_points: List[str]
    ) -> List[str]:
        """
        批量标准化知识点
        
        Args:
            raw_points: 原始知识点列表
        
        Returns:
            List[str]: 标准化后的知识点列表（去重）
        """
        standardized = set()
        for point in raw_points:
            std_point = await self.standardize_knowledge_point(point)
            standardized.add(std_point)
        
        return list(standardized)
    
    async def get_or_create_knowledge_point(
        self,
        name: str,
        category: Optional[str] = None,
        parent_id: Optional[str] = None,
    ) -> KnowledgePoint:
        """
        获取或创建知识点
        
        Args:
            name: 知识点名称
            category: 分类（代数/几何/函数等）
            parent_id: 父知识点 ID
        
        Returns:
            KnowledgePoint: 知识点对象
        """
        # 标准化名称
        std_name = await self.standardize_knowledge_point(name)
        
        # 查询是否存在
        result = await self.db.execute(
            select(KnowledgePoint).where(KnowledgePoint.name == std_name)
        )
        kp = result.scalar_one_or_none()
        
        if kp:
            return kp
        
        # 创建新知识点
        # 自动推断分类
        if not category:
            category = self._infer_category(std_name)
        
        kp = KnowledgePoint(
            name=std_name,
            category=category,
            parent_id=parent_id,
        )
        self.db.add(kp)
        await self.db.commit()
        await self.db.refresh(kp)
        
        return kp
    
    def _infer_category(self, name: str) -> str:
        """
        推断知识点分类
        
        Args:
            name: 知识点名称
        
        Returns:
            str: 分类名称
        """
        for category, points in self.KNOWLEDGE_HIERARCHY.items():
            if name in points:
                return category
        
        return "其他"
    
    async def get_parent_knowledge_point(self, name: str) -> Optional[str]:
        """
        获取父知识点
        
        Args:
            name: 知识点名称
        
        Returns:
            Optional[str]: 父知识点名称
        """
        for parent, children in self.KNOWLEDGE_HIERARCHY.items():
            if name in children:
                return parent
        
        return None
    
    async def get_children_knowledge_points(self, name: str) -> List[str]:
        """
        获取子知识点
        
        Args:
            name: 知识点名称
        
        Returns:
            List[str]: 子知识点列表
        """
        return self.KNOWLEDGE_HIERARCHY.get(name, [])
    
    async def search_knowledge_points(
        self,
        keyword: str,
        limit: int = 10
    ) -> List[KnowledgePoint]:
        """
        搜索知识点
        
        Args:
            keyword: 搜索关键词
            limit: 返回数量限制
        
        Returns:
            List[KnowledgePoint]: 知识点列表
        """
        result = await self.db.execute(
            select(KnowledgePoint)
            .where(KnowledgePoint.name.like(f"%{keyword}%"))
            .limit(limit)
        )
        return list(result.scalars().all())
