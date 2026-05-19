"""
图片语义分析服务测试
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from src.services.image_semantic_service import (
    ImageSemanticService,
    ImageSemanticResult,
    ImageSemanticException,
)


@pytest.mark.asyncio
async def test_analyze_image_success():
    """测试：成功分析单张图片"""
    # Mock API 响应
    mock_response = {
        "output": [
            {
                "content": [
                    {
                        "text": '''```json
{
    "description": "这是一个二次函数图像，开口向上，顶点在原点附近",
    "math_elements": ["坐标轴", "抛物线", "函数图像"],
    "context_hint": "这是一个二次函数题，需要分析函数性质和图像特征"
}
```'''
                    }
                ]
            }
        ]
    }
    
    with patch.object(ImageSemanticService, '_call_doubao_api', new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_response
        
        service = ImageSemanticService(api_key="test_key")
        result = await service.analyze_image("https://example.com/image.jpg")
        
        assert result.image_url == "https://example.com/image.jpg"
        assert "二次函数" in result.description
        assert "坐标轴" in result.math_elements
        assert "抛物线" in result.math_elements
        assert "函数图像" in result.math_elements
        assert result.confidence == 0.8
        assert result.error is None


@pytest.mark.asyncio
async def test_analyze_image_with_plain_json():
    """测试：API 返回纯 JSON（无 markdown 包裹）"""
    mock_response = {
        "output": [
            {
                "content": [
                    {
                        "text": '''{
    "description": "直角三角形，标注了三条边长",
    "math_elements": ["直角三角形", "边长标注"],
    "context_hint": "这是一个几何题，可能涉及勾股定理"
}'''
                    }
                ]
            }
        ]
    }
    
    with patch.object(ImageSemanticService, '_call_doubao_api', new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_response
        
        service = ImageSemanticService(api_key="test_key")
        result = await service.analyze_image("https://example.com/triangle.jpg")
        
        assert result.image_url == "https://example.com/triangle.jpg"
        assert "直角三角形" in result.description
        assert "直角三角形" in result.math_elements
        assert result.error is None


@pytest.mark.asyncio
async def test_analyze_image_failure():
    """测试：图片分析失败（失败降级）"""
    with patch.object(ImageSemanticService, '_call_doubao_api', new_callable=AsyncMock) as mock_api:
        mock_api.side_effect = Exception("API error")
        
        service = ImageSemanticService(api_key="test_key")
        result = await service.analyze_image("https://example.com/image.jpg")
        
        # 验证：失败降级，返回错误结果但不抛出异常
        assert result.image_url == "https://example.com/image.jpg"
        assert result.description == "图片分析失败"
        assert result.math_elements == []
        assert result.context_hint == ""
        assert result.confidence == 0.0
        assert result.error is not None
        assert "API error" in result.error


@pytest.mark.asyncio
async def test_analyze_batch_success():
    """测试：批量分析图片（全部成功）"""
    mock_response = {
        "output": [
            {
                "content": [
                    {
                        "text": '''```json
{
    "description": "测试图片",
    "math_elements": ["测试元素"],
    "context_hint": "测试提示"
}
```'''
                    }
                ]
            }
        ]
    }
    
    with patch.object(ImageSemanticService, '_call_doubao_api', new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_response
        
        service = ImageSemanticService(api_key="test_key")
        image_urls = [
            "https://example.com/image1.jpg",
            "https://example.com/image2.jpg",
            "https://example.com/image3.jpg",
        ]
        
        results = await service.analyze_batch(image_urls)
        
        # 验证：返回 3 个结果
        assert len(results) == 3
        for i, result in enumerate(results):
            assert result.image_url == image_urls[i]
            assert result.error is None
            assert result.description == "测试图片"


@pytest.mark.asyncio
async def test_analyze_batch_with_max_concurrency():
    """测试：批量分析图片（带并发上限控制）"""
    call_order = []
    
    async def mock_api_call(image_url):
        # 记录调用顺序
        call_order.append(image_url)
        # 模拟延迟
        await asyncio.sleep(0.01)
        return {
            "output": [
                {
                    "content": [
                        {
                            "text": f'{{"description": "{image_url}", "math_elements": [], "context_hint": ""}}'
                        }
                    ]
                }
            ]
        }
    
    with patch.object(ImageSemanticService, '_call_doubao_api', new_callable=AsyncMock) as mock_api:
        mock_api.side_effect = mock_api_call
        
        service = ImageSemanticService(api_key="test_key")
        image_urls = [
            "https://example.com/image1.jpg",
            "https://example.com/image2.jpg",
            "https://example.com/image3.jpg",
            "https://example.com/image4.jpg",
            "https://example.com/image5.jpg",
        ]
        
        # 使用 max_concurrency=2 限制并发
        results = await service.analyze_batch(image_urls, max_concurrency=2)
        
        # 验证：返回 5 个结果
        assert len(results) == 5
        
        # 验证：结果顺序与输入顺序一致
        for i, result in enumerate(results):
            assert result.image_url == image_urls[i]
            assert result.error is None
            assert image_urls[i] in result.description


@pytest.mark.asyncio
async def test_analyze_batch_partial_failure():
    """测试：批量分析图片（部分失败，失败降级）"""
    # Mock：第 2 张图片失败，其他成功
    call_count = 0
    
    async def mock_api_call(image_url):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("Image 2 failed")
        return {
            "output": [
                {
                    "content": [
                        {
                            "text": '''{"description": "成功", "math_elements": [], "context_hint": ""}'''
                        }
                    ]
                }
            ]
        }
    
    with patch.object(ImageSemanticService, '_call_doubao_api', new_callable=AsyncMock) as mock_api:
        mock_api.side_effect = mock_api_call
        
        service = ImageSemanticService(api_key="test_key")
        image_urls = [
            "https://example.com/image1.jpg",
            "https://example.com/image2.jpg",
            "https://example.com/image3.jpg",
        ]
        
        results = await service.analyze_batch(image_urls)
        
        # 验证：返回 3 个结果
        assert len(results) == 3
        
        # 验证：第 1 张成功
        assert results[0].image_url == image_urls[0]
        assert results[0].error is None
        assert results[0].description == "成功"
        
        # 验证：第 2 张失败（失败降级）
        assert results[1].image_url == image_urls[1]
        assert results[1].error is not None
        assert "Image 2 failed" in results[1].error
        assert results[1].description == "图片分析失败"
        
        # 验证：第 3 张成功
        assert results[2].image_url == image_urls[2]
        assert results[2].error is None
        assert results[2].description == "成功"


@pytest.mark.asyncio
async def test_analyze_batch_empty():
    """测试：批量分析空列表"""
    service = ImageSemanticService(api_key="test_key")
    results = await service.analyze_batch([])
    
    assert results == []


@pytest.mark.asyncio
async def test_parse_result_with_markdown_json():
    """测试：解析 markdown 包裹的 JSON"""
    service = ImageSemanticService(api_key="test_key")
    
    api_response = {
        "output": [
            {
                "content": [
                    {
                        "text": '''```json
{
    "description": "圆的图形",
    "math_elements": ["圆", "半径"],
    "context_hint": "圆的性质题"
}
```'''
                    }
                ]
            }
        ]
    }
    
    result = service._parse_result("https://example.com/circle.jpg", api_response)
    
    assert result.image_url == "https://example.com/circle.jpg"
    assert result.description == "圆的图形"
    assert result.math_elements == ["圆", "半径"]
    assert result.context_hint == "圆的性质题"


@pytest.mark.asyncio
async def test_parse_result_invalid_json():
    """测试：解析无效 JSON（抛出异常）"""
    service = ImageSemanticService(api_key="test_key")
    
    api_response = {
        "output": [
            {
                "content": [
                    {
                        "text": "这不是 JSON"
                    }
                ]
            }
        ]
    }
    
    with pytest.raises(ImageSemanticException, match="Failed to parse"):
        service._parse_result("https://example.com/test.jpg", api_response)


@pytest.mark.asyncio
async def test_parse_result_unexpected_structure():
    """测试：解析意外的响应结构（抛出异常）"""
    service = ImageSemanticService(api_key="test_key")
    
    api_response = {
        "unexpected": "structure"
    }
    
    with pytest.raises(ImageSemanticException, match="Unexpected DoubaoSeed response structure"):
        service._parse_result("https://example.com/test.jpg", api_response)
