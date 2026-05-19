"""
AI 分析服务测试

测试驱动开发（TDD）原则：先写测试，再写代码
"""

import json
import pytest
import requests
from unittest.mock import Mock, patch

from src.services.ai_analysis_service import (
    AIAnalysisService,
    OpenAIProvider,
    QuestionAnalysis,
    AIAnalysisException,
    Subject,
    QuestionType,
    ReviewPriority,
)


@pytest.fixture
def mock_openai_response():
    """模拟 OpenAI API 响应"""
    return {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "subject": "物理",
                    "grade": "八年级",
                    "question_type": "选择题",
                    "knowledge_points": ["浮力", "阿基米德原理"],
                    "prerequisites": ["密度", "重力"],
                    "difficulty": 3,
                    "likely_error_causes": ["概念混淆", "条件判断错误"],
                    "review_priority": "high",
                    "need_review": True,
                    "confidence": 0.9
                }, ensure_ascii=False)
            }
        }]
    }


@pytest.fixture
def openai_provider():
    """创建 OpenAI Provider 实例"""
    return OpenAIProvider(
        api_key="test_key",
        model="gpt-4o-mini",
    )


@pytest.fixture
def ai_service(openai_provider):
    """创建 AI 分析服务实例"""
    return AIAnalysisService(provider=openai_provider)


class TestOpenAIProvider:
    """OpenAI Provider 测试"""
    
    def test_init(self, openai_provider):
        """测试初始化"""
        assert openai_provider.api_key == "test_key"
        assert openai_provider.model == "gpt-4o-mini"
        assert openai_provider.temperature == 0.1
        assert openai_provider.max_tokens == 2000
    
    @patch('src.services.ai_analysis_service.requests.post')
    def test_analyze_question_success(
        self, mock_post, openai_provider, mock_openai_response
    ):
        """测试成功分析题目"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_openai_response
        
        result = openai_provider.analyze_question(
            "计算浮力大小",
            "# 题目\n\n计算浮力大小"
        )
        
        assert result["subject"] == "物理"
        assert result["grade"] == "八年级"
        assert "浮力" in result["knowledge_points"]
        assert result["difficulty"] == 3
        assert result["confidence"] == 0.9
    
    @patch('src.services.ai_analysis_service.requests.post')
    def test_analyze_question_api_error(self, mock_post, openai_provider):
        """测试 API 错误"""
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "Internal Server Error"
        
        with pytest.raises(AIAnalysisException) as exc_info:
            openai_provider.analyze_question("test", "test")
        
        assert "OpenAI API error" in str(exc_info.value)
        assert "500" in str(exc_info.value)
    
    @patch('src.services.ai_analysis_service.requests.post')
    def test_analyze_question_invalid_json(self, mock_post, openai_provider):
        """测试无效 JSON 响应"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "choices": [{
                "message": {
                    "content": "这不是有效的 JSON"
                }
            }]
        }
        
        with pytest.raises(AIAnalysisException) as exc_info:
            openai_provider.analyze_question("test", "test")
        
        assert "Failed to parse AI response" in str(exc_info.value)


class TestAIAnalysisService:
    """AI 分析服务测试"""
    
    def test_init(self, ai_service, openai_provider):
        """测试初始化"""
        assert ai_service.provider == openai_provider
        assert ai_service.enable_cache is True
        assert ai_service.cache_ttl == 86400
    
    @patch('src.services.ai_analysis_service.requests.post')
    def test_analyze_question_success(
        self, mock_post, ai_service, mock_openai_response
    ):
        """测试成功分析题目"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_openai_response
        
        analysis = ai_service.analyze_question(
            "计算浮力大小",
            "# 题目\n\n计算浮力大小"
        )
        
        assert isinstance(analysis, QuestionAnalysis)
        assert analysis.subject == "物理"
        assert analysis.grade == "八年级"
        assert analysis.question_type == "选择题"
        assert "浮力" in analysis.knowledge_points
        assert "阿基米德原理" in analysis.knowledge_points
        assert "密度" in analysis.prerequisites
        assert analysis.difficulty == 3
        assert "概念混淆" in analysis.likely_error_causes
        assert analysis.review_priority == "high"
        assert analysis.need_review is True
        assert analysis.confidence == 0.9
    
    @patch('src.services.ai_analysis_service.requests.post')
    def test_analyze_question_with_cache(
        self, mock_post, ai_service, mock_openai_response
    ):
        """测试缓存功能"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_openai_response
        
        question_text = "计算浮力大小"
        question_markdown = "# 题目\n\n计算浮力大小"
        
        # 第一次调用
        analysis1 = ai_service.analyze_question(question_text, question_markdown)
        
        # 第二次调用（应该使用缓存）
        analysis2 = ai_service.analyze_question(question_text, question_markdown)
        
        # 应该只调用一次 API
        assert mock_post.call_count == 1
        
        # 两次结果应该相同
        assert analysis1.subject == analysis2.subject
        assert analysis1.knowledge_points == analysis2.knowledge_points
    
    @patch('src.services.ai_analysis_service.requests.post')
    def test_analyze_question_cache_disabled(
        self, mock_post, openai_provider, mock_openai_response
    ):
        """测试禁用缓存"""
        service = AIAnalysisService(provider=openai_provider, enable_cache=False)
        
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_openai_response
        
        question_text = "计算浮力大小"
        question_markdown = "# 题目\n\n计算浮力大小"
        
        # 调用两次
        service.analyze_question(question_text, question_markdown)
        service.analyze_question(question_text, question_markdown)
        
        # 应该调用两次 API
        assert mock_post.call_count == 2
    
    @patch('src.services.ai_analysis_service.requests.post')
    def test_analyze_question_skip_cache(
        self, mock_post, ai_service, mock_openai_response
    ):
        """测试跳过缓存"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_openai_response
        
        question_text = "计算浮力大小"
        question_markdown = "# 题目\n\n计算浮力大小"
        
        # 第一次调用
        ai_service.analyze_question(question_text, question_markdown)
        
        # 第二次调用，跳过缓存
        ai_service.analyze_question(question_text, question_markdown, use_cache=False)
        
        # 应该调用两次 API
        assert mock_post.call_count == 2
    
    def test_get_cache_key(self, ai_service):
        """测试缓存 key 生成"""
        text1 = "计算浮力大小"
        text2 = "计算浮力大小"
        text3 = "计算重力大小"
        
        key1 = ai_service._get_cache_key(text1)
        key2 = ai_service._get_cache_key(text2)
        key3 = ai_service._get_cache_key(text3)
        
        # 相同文本应该生成相同 key
        assert key1 == key2
        
        # 不同文本应该生成不同 key
        assert key1 != key3
        
        # key 应该是 64 位十六进制字符串（SHA256）
        assert len(key1) == 64
    
    def test_parse_analysis(self, ai_service):
        """测试解析分析结果"""
        raw_result = {
            "subject": "物理",
            "grade": "八年级",
            "question_type": "选择题",
            "knowledge_points": ["浮力"],
            "prerequisites": ["密度"],
            "difficulty": 3,
            "likely_error_causes": ["概念混淆"],
            "review_priority": "high",
            "need_review": True,
            "confidence": 0.9
        }
        
        analysis = ai_service._parse_analysis(raw_result)
        
        assert isinstance(analysis, QuestionAnalysis)
        assert analysis.subject == "物理"
        assert analysis.difficulty == 3
        assert analysis.confidence == 0.9
    
    def test_parse_analysis_with_defaults(self, ai_service):
        """测试解析结果（使用默认值）"""
        raw_result = {}
        
        analysis = ai_service._parse_analysis(raw_result)
        
        assert analysis.subject == "未知"
        assert analysis.grade == "未知"
        assert analysis.question_type == "未知"
        assert analysis.knowledge_points == []
        assert analysis.difficulty == 3
        assert analysis.confidence == 0.8
    
    def test_clear_cache(self, ai_service):
        """测试清空缓存"""
        # 添加一些缓存
        ai_service._cache["key1"] = Mock()
        ai_service._cache["key2"] = Mock()
        
        assert ai_service.get_cache_size() == 2
        
        # 清空缓存
        ai_service.clear_cache()
        
        assert ai_service.get_cache_size() == 0
    
    def test_get_cache_size(self, ai_service):
        """测试获取缓存大小"""
        assert ai_service.get_cache_size() == 0
        
        ai_service._cache["key1"] = Mock()
        assert ai_service.get_cache_size() == 1
        
        ai_service._cache["key2"] = Mock()
        assert ai_service.get_cache_size() == 2


class TestQuestionAnalysis:
    """QuestionAnalysis 测试"""
    
    def test_creation(self):
        """测试创建 QuestionAnalysis"""
        analysis = QuestionAnalysis(
            subject="物理",
            grade="八年级",
            question_type="选择题",
            knowledge_points=["浮力"],
            prerequisites=["密度"],
            difficulty=3,
            likely_error_causes=["概念混淆"],
            review_priority="high",
            need_review=True,
            confidence=0.9,
        )
        
        assert analysis.subject == "物理"
        assert analysis.grade == "八年级"
        assert analysis.difficulty == 3
        assert analysis.confidence == 0.9
        assert analysis.raw_response is None


class TestEnums:
    """枚举测试"""
    
    def test_subject_enum(self):
        """测试学科枚举"""
        assert Subject.MATH == "数学"
        assert Subject.PHYSICS == "物理"
        assert Subject.CHEMISTRY == "化学"
    
    def test_question_type_enum(self):
        """测试题型枚举"""
        assert QuestionType.CHOICE == "选择题"
        assert QuestionType.FILL_BLANK == "填空题"
        assert QuestionType.CALCULATION == "计算题"
    
    def test_review_priority_enum(self):
        """测试复习优先级枚举"""
        assert ReviewPriority.HIGH == "high"
        assert ReviewPriority.MEDIUM == "medium"
        assert ReviewPriority.LOW == "low"


class TestEdgeCases:
    """边界情况测试 - 补充覆盖率"""
    
    @patch('src.services.ai_analysis_service.requests.post')
    def test_analyze_question_provider_exception(self, mock_post, ai_service):
        """测试 Provider 抛出异常（覆盖第 227-228 行）"""
        mock_post.side_effect = Exception("Network error")
        
        with pytest.raises(AIAnalysisException) as exc_info:
            ai_service.analyze_question("test", "test")
        
        assert "AI analysis failed" in str(exc_info.value)
        assert "Network error" in str(exc_info.value)
    
    def test_parse_analysis_invalid_data(self, ai_service):
        """测试解析无效数据（覆盖第 268-269 行）"""
        # difficulty 不是数字
        raw_result = {
            "difficulty": "invalid",
        }
        
        with pytest.raises(AIAnalysisException) as exc_info:
            ai_service._parse_analysis(raw_result)
        
        assert "Failed to parse analysis result" in str(exc_info.value)
    
    @patch('src.services.ai_analysis_service.requests.post')
    def test_analyze_question_timeout(self, mock_post, ai_service):
        """测试请求超时（覆盖第 87 行）"""
        mock_post.side_effect = requests.exceptions.Timeout("Request timeout")
        
        with pytest.raises(AIAnalysisException) as exc_info:
            ai_service.analyze_question("test", "test")
        
        assert "AI analysis failed" in str(exc_info.value)
