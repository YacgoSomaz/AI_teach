"""
题图多模态分析服务

负责：
1. 使用豆包 Seed1.8 分析 OCR 提取的图片块
2. 提取图片语义描述
3. 识别数学元素（坐标轴、函数图像、几何图形等）
4. 生成对 AI 分析的辅助提示
5. 支持批量并发处理
"""

import asyncio
import json
from dataclasses import dataclass
from typing import List, Optional

import requests

from src.config import get_settings


@dataclass
class ImageSemanticResult:
    """图片语义分析结果"""
    image_url: str
    description: str  # 图片内容语义描述
    math_elements: List[str]  # 图中数学元素（坐标轴、函数图像、几何图形等）
    context_hint: str  # 对 AI 分析的辅助提示
    confidence: float = 0.8  # 分析置信度
    error: Optional[str] = None  # 错误信息（如果分析失败）


class ImageSemanticService:
    """
    图片语义分析服务
    
    使用豆包 Seed1.8 分析 OCR 提取的图片块，
    提取图片的语义信息以辅助题目分析。
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        初始化服务
        
        Args:
            api_key: 豆包 API Key（可选，用于测试时注入 mock）
        """
        self.settings = get_settings()
        self.api_key = api_key or self.settings.doubao_seed_api_key
        self.model = self.settings.doubao_seed_model
        self.base_url = self.settings.doubao_seed_base_url.rstrip("/")
        self.max_tokens = 1000
        
        # 只在非测试环境检查 API key
        if not self.api_key and not api_key:
            raise ValueError("DOUBAO_SEED_API_KEY 未配置，图片语义分析功能无法使用")
    
    async def analyze_image(self, image_url: str) -> ImageSemanticResult:
        """
        分析单张图片的语义
        
        Args:
            image_url: 图片 URL
            
        Returns:
            ImageSemanticResult: 图片语义分析结果
        """
        try:
            # 调用豆包 Seed1.8 API
            result = await self._call_doubao_api(image_url)
            
            # 解析结果
            return self._parse_result(image_url, result)
        
        except Exception as e:
            # 分析失败，返回错误结果（失败降级）
            return ImageSemanticResult(
                image_url=image_url,
                description="图片分析失败",
                math_elements=[],
                context_hint="",
                confidence=0.0,
                error=str(e),
            )
    
    async def analyze_batch(
        self, 
        image_urls: List[str],
        max_concurrency: int = 3,
    ) -> List[ImageSemanticResult]:
        """
        批量分析图片（并发处理，带并发上限控制）
        
        Args:
            image_urls: 图片 URL 列表
            max_concurrency: 最大并发数，默认 3（避免 429 或成本失控）
            
        Returns:
            List[ImageSemanticResult]: 图片语义分析结果列表（顺序与输入一致）
        """
        if not image_urls:
            return []
        
        # 创建信号量控制并发
        semaphore = asyncio.Semaphore(max_concurrency)
        
        async def analyze_with_semaphore(url: str) -> ImageSemanticResult:
            """带信号量控制的分析函数"""
            async with semaphore:
                return await self.analyze_image(url)
        
        # 并发分析所有图片（单张失败不影响其他，保持顺序）
        tasks = [analyze_with_semaphore(url) for url in image_urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        
        return results
    
    async def _call_doubao_api(self, image_url: str) -> dict:
        """
        调用豆包 Seed1.8 Responses API
        
        Args:
            image_url: 图片 URL
            
        Returns:
            dict: API 响应结果
        """
        system_prompt = """你是一个专业的图片分析助手，负责分析题目中的图片。

请分析图片并输出 JSON 格式的结果，包含以下字段：
- description: 图片内容的详细描述（50-100字）
- math_elements: 图中的数学元素列表（如：坐标轴、函数图像、几何图形、数据表格等）
- context_hint: 对题目分析的辅助提示（如：这是一个函数图像题，需要分析函数性质）

只输出 JSON，不要其他内容。"""
        
        # 构建 Responses API 的 content 列表
        content = [
            {
                "type": "input_image",
                "image_url": image_url,
            },
            {
                "type": "input_text",
                "text": (
                    f"系统指令：{system_prompt}\n\n"
                    "请分析这张图片，识别其中的数学元素和语义信息。\n\n"
                    "只输出 JSON，不要其他内容。"
                ),
            },
        ]
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "user",
                    "content": content,
                }
            ],
            "max_output_tokens": self.max_tokens,
        }
        
        # 使用 asyncio 运行同步请求
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                f"{self.base_url}/responses",
                headers=headers,
                json=payload,
                timeout=120,
            )
        )
        
        if response.status_code != 200:
            raise ImageSemanticException(
                f"DoubaoSeed API error: {response.status_code} - {response.text}"
            )
        
        return response.json()
    
    def _parse_result(self, image_url: str, api_response: dict) -> ImageSemanticResult:
        """
        解析 API 响应
        
        Args:
            image_url: 图片 URL
            api_response: API 响应
            
        Returns:
            ImageSemanticResult: 解析后的结果
        """
        try:
            # 提取输出文本
            output_text = api_response["output"][0]["content"][0]["text"]
        except (KeyError, IndexError) as e:
            raise ImageSemanticException(
                f"Unexpected DoubaoSeed response structure: {e}\nResponse: {api_response}"
            )
        
        # 提取 JSON（模型可能返回 markdown 代码块包裹的 JSON）
        try:
            text = output_text.strip()
            if "```json" in text:
                json_start = text.find("```json") + 7
                json_end = text.find("```", json_start)
                text = text[json_start:json_end].strip()
            elif "```" in text:
                json_start = text.find("```") + 3
                json_end = text.find("```", json_start)
                text = text[json_start:json_end].strip()
            
            data = json.loads(text)
            
            return ImageSemanticResult(
                image_url=image_url,
                description=data.get("description", ""),
                math_elements=data.get("math_elements", []),
                context_hint=data.get("context_hint", ""),
                confidence=0.8,
                error=None,
            )
        
        except json.JSONDecodeError as e:
            raise ImageSemanticException(
                f"Failed to parse DoubaoSeed response as JSON: {e}\nResponse: {output_text}"
            )


class ImageSemanticException(Exception):
    """图片语义分析异常"""
    pass
