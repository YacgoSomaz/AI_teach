"""
AI 分析服务测试（带缓存）
"""

import pytest
from unittest.mock import Mock, MagicMock
from src.services.ai_analysis_service import (
    AIAnalysisService,
    AIProvider,
    QuestionAnalysis,
    AIAnalysisException,
)
from src.services.ai_cache_service import AICacheService


class MockAIProvider(AIProvider):
    """Mock AI 提供商"""
    
    def __init__(self, response=None, should_fail=False):
        self.response = response or {
            "subject": "数学",
            "grade": "八年级",
            "question_type": "计算题",
            "knowledge_points": ["一次函数", "函数图像"],
            "prerequisites": ["坐标系"],
            "difficulty": 3,
            "likely_error_causes": ["计算错误", "理解不足"],
            "review_priority": "medium",
            "need_review": True,
            "confidence": 0.85,
        }
        self.should_fail = should_fail
        self.call_count = 0
    
    def analyze_question(self, question_text: str, question_markdown: str, image_urls=None):
        self.call_count += 1
        
        if self.should_fail:
            raise Exception("Mock AI provider failed")
        
        return self.response


class TestAIAnalysisServiceWithCache:
    """AI 分析服务缓存测试"""
    
    def test_cache_hit(self):
        """测试：缓存命中，不调用 AI"""
        provider = MockAIProvider()
        cache_service = AICacheService()
        service = AIAnalysisService(provider=provider, cache_service=cache_service)
        
        question_text = "求函数 y=2x+1 的图像"
        question_markdown = "**题目**：求函数 y=2x+1 的图像"
        
        # 第一次调用，应该调用 AI
        result1 = service.analyze_question(
            question_text=question_text,
            question_markdown=question_markdown,
            subject="数学",
            grade="八年级",
        )
        
        assert provider.call_count == 1
        assert result1.subject == "数学"
        assert "一次函数" in result1.knowledge_points
        
        # 第二次调用相同题目，应该命中缓存
        result2 = service.analyze_question(
            question_text=question_text,
            question_markdown=question_markdown,
            subject="数学",
            grade="八年级",
        )
        
        # AI 不应该被再次调用
        assert provider.call_count == 1
        
        # 结果应该相同
        assert result2.subject == result1.subject
        assert result2.knowledge_points == result1.knowledge_points
    
    def test_cache_miss_different_input(self):
        """测试：不同输入，缓存未命中，调用 AI"""
        provider = MockAIProvider()
        cache_service = AICacheService()
        service = AIAnalysisService(provider=provider, cache_service=cache_service)
        
        # 第一次调用
        service.analyze_question(
            question_text="题目1",
            question_markdown="题目1",
            subject="数学",
        )
        assert provider.call_count == 1
        
        # 不同题目，应该再次调用 AI
        service.analyze_question(
            question_text="题目2",
            question_markdown="题目2",
            subject="数学",
        )
        assert provider.call_count == 2
        
        # 相同题目但不同学科，应该再次调用 AI
        service.analyze_question(
            question_text="题目1",
            question_markdown="题目1",
            subject="物理",
        )
        assert provider.call_count == 3
    
    def test_cache_disabled(self):
        """测试：禁用缓存，每次都调用 AI"""
        provider = MockAIProvider()
        cache_service = AICacheService()
        service = AIAnalysisService(
            provider=provider,
            cache_service=cache_service,
            enable_cache=False,
        )
        
        question_text = "题目1"
        question_markdown = "题目1"
        
        # 第一次调用
        service.analyze_question(question_text, question_markdown)
        assert provider.call_count == 1
        
        # 第二次调用相同题目，缓存禁用，应该再次调用 AI
        service.analyze_question(question_text, question_markdown)
        assert provider.call_count == 2
    
    def test_skip_caching_empty_knowledge_points(self):
        """测试：不缓存 knowledge_points 为空的结果"""
        # AI 返回空知识点
        provider = MockAIProvider(response={
            "subject": "数学",
            "grade": "八年级",
            "question_type": "计算题",
            "knowledge_points": [],  # 空
            "prerequisites": [],
            "difficulty": 3,
            "likely_error_causes": [],
            "review_priority": "medium",
            "need_review": True,
            "confidence": 0.85,
        })
        cache_service = AICacheService()
        service = AIAnalysisService(provider=provider, cache_service=cache_service)
        
        question_text = "题目1"
        question_markdown = "题目1"
        
        # 第一次调用
        result1 = service.analyze_question(question_text, question_markdown)
        assert provider.call_count == 1
        assert result1.knowledge_points == []
        
        # 第二次调用，因为第一次结果未缓存，应该再次调用 AI
        result2 = service.analyze_question(question_text, question_markdown)
        assert provider.call_count == 2
    
    def test_skip_caching_unknown_subject(self):
        """测试：不缓存 subject 为"未知"的结果"""
        provider = MockAIProvider(response={
            "subject": "未知",
            "grade": "八年级",
            "question_type": "计算题",
            "knowledge_points": ["知识点1"],
            "prerequisites": [],
            "difficulty": 3,
            "likely_error_causes": [],
            "review_priority": "medium",
            "need_review": True,
            "confidence": 0.85,
        })
        cache_service = AICacheService()
        service = AIAnalysisService(provider=provider, cache_service=cache_service)
        
        question_text = "题目1"
        question_markdown = "题目1"
        
        # 第一次调用
        service.analyze_question(question_text, question_markdown)
        assert provider.call_count == 1
        
        # 第二次调用，因为第一次结果未缓存，应该再次调用 AI
        service.analyze_question(question_text, question_markdown)
        assert provider.call_count == 2
    
    def test_skip_caching_low_confidence(self):
        """测试：不缓存置信度过低的结果"""
        provider = MockAIProvider(response={
            "subject": "数学",
            "grade": "八年级",
            "question_type": "计算题",
            "knowledge_points": ["知识点1"],
            "prerequisites": [],
            "difficulty": 3,
            "likely_error_causes": [],
            "review_priority": "medium",
            "need_review": True,
            "confidence": 0.2,  # 低置信度
        })
        cache_service = AICacheService()
        service = AIAnalysisService(provider=provider, cache_service=cache_service)
        
        question_text = "题目1"
        question_markdown = "题目1"
        
        # 第一次调用
        service.analyze_question(question_text, question_markdown)
        assert provider.call_count == 1
        
        # 第二次调用，因为第一次结果未缓存，应该再次调用 AI
        service.analyze_question(question_text, question_markdown)
        assert provider.call_count == 2
    
    def test_cache_failure_fallback(self):
        """测试：缓存服务失败时降级，不影响主流程"""
        provider = MockAIProvider()
        
        # Mock 一个会失败的缓存服务
        cache_service = Mock(spec=AICacheService)
        cache_service.generate_cache_key.side_effect = Exception("Cache service failed")
        cache_service.get.side_effect = Exception("Cache service failed")
        cache_service.set.side_effect = Exception("Cache service failed")
        
        service = AIAnalysisService(provider=provider, cache_service=cache_service)
        
        # 即使缓存失败，分析应该正常进行
        result = service.analyze_question(
            question_text="题目1",
            question_markdown="题目1",
        )
        
        assert result.subject == "数学"
        assert provider.call_count == 1
    
    def test_ai_provider_failure(self):
        """测试：AI 提供商失败时抛出异常"""
        provider = MockAIProvider(should_fail=True)
        cache_service = AICacheService()
        service = AIAnalysisService(provider=provider, cache_service=cache_service)
        
        with pytest.raises(AIAnalysisException) as exc_info:
            service.analyze_question(
                question_text="题目1",
                question_markdown="题目1",
            )
        
        assert "AI analysis failed" in str(exc_info.value)
    
    def test_clear_cache(self):
        """测试：清空缓存"""
        provider = MockAIProvider()
        cache_service = AICacheService()
        service = AIAnalysisService(provider=provider, cache_service=cache_service)
        
        # 调用一次，写入缓存
        service.analyze_question("题目1", "题目1")
        assert provider.call_count == 1
        
        # 再次调用，命中缓存
        service.analyze_question("题目1", "题目1")
        assert provider.call_count == 1
        
        # 清空缓存
        service.clear_cache()
        
        # 再次调用，缓存已清空，应该调用 AI
        service.analyze_question("题目1", "题目1")
        assert provider.call_count == 2
    
    def test_get_cache_stats(self):
        """测试：获取缓存统计信息"""
        provider = MockAIProvider()
        cache_service = AICacheService()
        service = AIAnalysisService(provider=provider, cache_service=cache_service)
        
        # 调用几次
        for i in range(3):
            service.analyze_question(f"题目{i}", f"题目{i}")
        
        stats = service.get_cache_stats()
        
        assert stats["backend"] == "memory"
        assert stats["total_keys"] == 3
    
    def test_with_image_urls(self):
        """测试：带图片 URL 的分析"""
        provider = MockAIProvider()
        cache_service = AICacheService()
        service = AIAnalysisService(provider=provider, cache_service=cache_service)
        
        question_text = "题目1"
        question_markdown = "题目1"
        image_urls = ["http://img1.jpg", "http://img2.jpg"]
        
        # 第一次调用
        result1 = service.analyze_question(
            question_text=question_text,
            question_markdown=question_markdown,
            image_urls=image_urls,
        )
        assert provider.call_count == 1
        
        # 相同题目和图片，命中缓存
        result2 = service.analyze_question(
            question_text=question_text,
            question_markdown=question_markdown,
            image_urls=image_urls,
        )
        assert provider.call_count == 1
        
        # 相同题目但不同图片，未命中缓存
        result3 = service.analyze_question(
            question_text=question_text,
            question_markdown=question_markdown,
            image_urls=["http://img3.jpg"],
        )
        assert provider.call_count == 2
