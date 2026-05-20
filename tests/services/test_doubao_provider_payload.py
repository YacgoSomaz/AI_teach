"""
测试豆包 Provider 的 payload 不包含 reasoning 参数
"""

import pytest
from unittest.mock import patch, MagicMock
import json

from src.services.ai_analysis_service import DoubaoSeedProvider, AIAnalysisException


def test_doubao_payload_no_reasoning():
    """测试豆包 Provider 的 payload 不包含 reasoning/thinking 参数"""
    provider = DoubaoSeedProvider(
        api_key="test_key",
        model="test_model",
    )
    
    # Mock requests.post
    with patch("src.services.ai_analysis_service.requests.post") as mock_post:
        # 模拟成功响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({
                                "subject": "数学",
                                "grade": "九年级",
                                "question_type": "计算题",
                                "knowledge_points": ["二次方程"],
                                "prerequisites": [],
                                "difficulty": 3,
                                "likely_error_causes": [],
                                "review_priority": "medium",
                                "need_review": True,
                                "confidence": 0.9,
                            })
                        }
                    ]
                }
            ]
        }
        mock_post.return_value = mock_response
        
        # 调用 analyze_question
        result = provider.analyze_question(
            question_text="解方程 x^2 + 2x + 1 = 0",
            question_markdown="## 题目\n\n解方程 $x^2 + 2x + 1 = 0$",
        )
        
        # 验证 requests.post 被调用
        assert mock_post.called
        
        # 获取调用参数
        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        
        # 验证 payload 不包含 reasoning/thinking 参数
        assert "reasoning" not in payload
        assert "thinking" not in payload
        assert "enable_reasoning" not in payload
        assert "enable_thinking" not in payload
        
        # 验证 payload 包含必需字段
        assert "model" in payload
        assert "input" in payload
        assert "max_output_tokens" in payload
        
        # 验证返回结果
        assert result["subject"] == "数学"
        assert result["grade"] == "九年级"


def test_doubao_prompt_emphasizes_json_only():
    """测试豆包 Provider 的 prompt 强调只输出 JSON"""
    provider = DoubaoSeedProvider(
        api_key="test_key",
        model="test_model",
    )
    
    # Mock requests.post
    with patch("src.services.ai_analysis_service.requests.post") as mock_post:
        # 模拟成功响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "text",
                            "text": '{"subject": "数学", "grade": "九年级", "question_type": "计算题", "knowledge_points": ["二次方程"], "prerequisites": [], "difficulty": 3, "likely_error_causes": [], "review_priority": "medium", "need_review": true, "confidence": 0.9}'
                        }
                    ]
                }
            ]
        }
        mock_post.return_value = mock_response
        
        # 调用 analyze_question
        result = provider.analyze_question(
            question_text="解方程 x^2 + 2x + 1 = 0",
            question_markdown="## 题目\n\n解方程 $x^2 + 2x + 1 = 0$",
        )
        
        # 获取调用参数
        call_args = mock_post.call_args
        payload = call_args.kwargs["json"]
        
        # 获取 prompt 文本
        user_content = payload["input"][0]["content"]
        text_content = None
        for item in user_content:
            if item.get("type") == "input_text":
                text_content = item.get("text")
                break
        
        assert text_content is not None
        
        # 验证 prompt 强调只输出 JSON
        assert "只输出 JSON" in text_content
        assert "不要输出思考过程" in text_content
        assert "不要输出解释" in text_content
        assert "不要输出 markdown 代码块包裹" in text_content
        assert "不要其他内容" in text_content
