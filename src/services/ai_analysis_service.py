"""
AI 分析服务

负责分析 OCR 识别的题目，提取知识点、难度、错因等信息。

设计原则：
1. 支持多种大模型（OpenAI、Claude、国产模型）
2. 结构化输出（JSON Schema）
3. 成本控制（缓存、模型路由）
4. 质量评估（置信度）
5. 失败重试
"""

import json
import hashlib
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from abc import ABC, abstractmethod

import requests


class Subject(str, Enum):
    """学科"""
    MATH = "数学"
    PHYSICS = "物理"
    CHEMISTRY = "化学"
    BIOLOGY = "生物"
    CHINESE = "语文"
    ENGLISH = "英语"
    HISTORY = "历史"
    GEOGRAPHY = "地理"
    POLITICS = "政治"


class QuestionType(str, Enum):
    """题型"""
    CHOICE = "选择题"
    FILL_BLANK = "填空题"
    SHORT_ANSWER = "简答题"
    CALCULATION = "计算题"
    PROOF = "证明题"
    EXPERIMENT = "实验题"
    READING = "阅读理解"
    WRITING = "写作题"


class ReviewPriority(str, Enum):
    """复习优先级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class QuestionAnalysis:
    """题目分析结果"""
    subject: str  # 学科
    grade: str  # 年级
    question_type: str  # 题型
    knowledge_points: List[str]  # 知识点列表
    prerequisites: List[str]  # 前置知识
    difficulty: int  # 难度（1-5）
    likely_error_causes: List[str]  # 可能错因
    review_priority: str  # 复习优先级
    need_review: bool  # 是否需要复习
    confidence: float  # 置信度
    raw_response: Optional[str] = None  # 原始 AI 响应


class AIProvider(ABC):
    """AI 提供商抽象基类"""
    
    @abstractmethod
    def analyze_question(self, question_text: str, question_markdown: str) -> Dict[str, Any]:
        """
        分析题目
        
        Args:
            question_text: 题目纯文本
            question_markdown: 题目 Markdown 格式
            
        Returns:
            Dict: 分析结果
        """
        pass


class OpenAIProvider(AIProvider):
    """OpenAI 提供商"""
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def analyze_question(self, question_text: str, question_markdown: str) -> Dict[str, Any]:
        """使用 OpenAI API 分析题目"""
        
        system_prompt = """你是一个专业的教育分析助手，负责分析学生作业和错题。

请分析题目并输出 JSON 格式的结果，包含以下字段：
- subject: 学科（数学/物理/化学/生物/语文/英语/历史/地理/政治）
- grade: 年级（如：七年级、八年级、高一）
- question_type: 题型（选择题/填空题/简答题/计算题/证明题/实验题/阅读理解/写作题）
- knowledge_points: 知识点列表（数组）
- prerequisites: 前置知识列表（数组）
- difficulty: 难度（1-5，1最简单，5最难）
- likely_error_causes: 可能的错因列表（数组）
- review_priority: 复习优先级（high/medium/low）
- need_review: 是否需要复习（true/false）
- confidence: 分析置信度（0-1）

只输出 JSON，不要其他内容。"""
        
        user_prompt = f"""请分析以下题目：

{question_markdown}

输出 JSON 格式的分析结果。"""
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},  # 强制 JSON 输出
        }
        
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        
        if response.status_code != 200:
            raise AIAnalysisException(
                f"OpenAI API error: {response.status_code} - {response.text}"
            )
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        try:
            analysis = json.loads(content)
            return analysis
        except json.JSONDecodeError as e:
            raise AIAnalysisException(f"Failed to parse AI response as JSON: {e}")


class DoubaoProvider(AIProvider):
    """豆包（字节跳动）提供商 - 支持多模态"""
    
    def __init__(
        self,
        api_key: str,
        model: str = "doubao-pro-32k",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def analyze_question(self, question_text: str, question_markdown: str, image_urls: List[str] = None) -> Dict[str, Any]:
        """
        使用豆包 API 分析题目（支持多模态）
        
        Args:
            question_text: 题目纯文本
            question_markdown: 题目 Markdown 格式
            image_urls: 图片 URL 列表（用于多模态分析）
        """
        
        system_prompt = """你是一个专业的教育分析助手，负责分析学生作业和错题。

请分析题目并输出 JSON 格式的结果，包含以下字段：
- subject: 学科（数学/物理/化学/生物/语文/英语/历史/地理/政治）
- grade: 年级（如：七年级、八年级、高一）
- question_type: 题型（选择题/填空题/简答题/计算题/证明题/实验题/阅读理解/写作题）
- knowledge_points: 知识点列表（数组）
- prerequisites: 前置知识列表（数组）
- difficulty: 难度（1-5，1最简单，5最难）
- likely_error_causes: 可能的错因列表（数组）
- review_priority: 复习优先级（high/medium/low）
- need_review: 是否需要复习（true/false）
- confidence: 分析置信度（0-1）

只输出 JSON，不要其他内容。"""
        
        # 构建用户消息（支持多模态）
        user_content = []
        
        # 添加文本
        user_content.append({
            "type": "text",
            "text": f"请分析以下题目：\n\n{question_markdown}\n\n输出 JSON 格式的分析结果。"
        })
        
        # 添加图片（如果有）
        if image_urls:
            for img_url in image_urls:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": img_url}
                })
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        
        if response.status_code != 200:
            raise AIAnalysisException(
                f"Doubao API error: {response.status_code} - {response.text}"
            )
        
        result = response.json()
        content = result["choices"][0]["message"]["content"]
        
        # 尝试提取 JSON（豆包可能返回 markdown 格式的 JSON）
        try:
            # 如果是 markdown 格式，提取 JSON 部分
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            
            analysis = json.loads(content)
            return analysis
        except json.JSONDecodeError as e:
            raise AIAnalysisException(f"Failed to parse AI response as JSON: {e}\nResponse: {content}")


class DoubaoSeedProvider(AIProvider):
    """
    豆包 Seed1.8 提供商（火山引擎 Responses API）

    使用 /api/v3/responses 接口，支持多模态（文本 + 图片）。
    不使用深度思考模式，直接输出结构化 JSON。

    与 DoubaoProvider 的区别：
    - 接口路径：/responses（而非 /chat/completions）
    - 消息格式：input_text / input_image（而非 text / image_url）
    - 不支持 temperature 参数
    """

    def __init__(
        self,
        api_key: str,
        model: str = "ep-20260518173637-nhzdp",
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        max_tokens: int = 2000,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens

    def analyze_question(
        self,
        question_text: str,
        question_markdown: str,
        image_urls: List[str] = None,
    ) -> Dict[str, Any]:
        """
        使用豆包 Seed1.8 Responses API 分析题目（支持多模态）

        Args:
            question_text: 题目纯文本
            question_markdown: 题目 Markdown 格式
            image_urls: 图片 URL 列表（用于多模态分析）

        Returns:
            Dict: 分析结果
        """
        system_prompt = """你是一个专业的教育分析助手，负责分析学生作业和错题。

请分析题目并输出 JSON 格式的结果，包含以下字段：
- subject: 学科（数学/物理/化学/生物/语文/英语/历史/地理/政治）
- grade: 年级（如：七年级、八年级、高一）
- question_type: 题型（选择题/填空题/简答题/计算题/证明题/实验题/阅读理解/写作题）
- knowledge_points: 知识点列表（数组）
- prerequisites: 前置知识列表（数组）
- difficulty: 难度（1-5，1最简单，5最难）
- likely_error_causes: 可能的错因列表（数组）
- review_priority: 复习优先级（high/medium/low）
- need_review: 是否需要复习（true/false）
- confidence: 分析置信度（0-1）

只输出 JSON，不要其他内容。"""

        # 构建 Responses API 的 content 列表
        # 格式：先放图片（如有），再放文本
        content: List[Dict] = []

        if image_urls:
            for img_url in image_urls:
                content.append({
                    "type": "input_image",
                    "image_url": img_url,
                })

        content.append({
            "type": "input_text",
            "text": (
                f"系统指令：{system_prompt}\n\n"
                f"请分析以下题目：\n\n{question_markdown}\n\n"
                "只输出 JSON，不要其他内容。"
            ),
        })

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
            "max_new_tokens": self.max_tokens,
        }

        response = requests.post(
            f"{self.base_url}/responses",
            headers=headers,
            json=payload,
            timeout=120,
        )

        if response.status_code != 200:
            raise AIAnalysisException(
                f"DoubaoSeed API error: {response.status_code} - {response.text}"
            )

        result = response.json()

        # Responses API 输出结构：result.output[].content[].text
        try:
            output_text = result["output"][0]["content"][0]["text"]
        except (KeyError, IndexError) as e:
            raise AIAnalysisException(
                f"Unexpected DoubaoSeed response structure: {e}\nResponse: {result}"
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

            analysis = json.loads(text)
            return analysis
        except json.JSONDecodeError as e:
            raise AIAnalysisException(
                f"Failed to parse DoubaoSeed response as JSON: {e}\nResponse: {output_text}"
            )


class MinimaxProvider(AIProvider):
    """MiniMax 提供商 - 支持多模态"""
    
    def __init__(
        self,
        api_key: str,
        group_id: str,
        model: str = "abab6.5s-chat",
        base_url: str = "https://api.minimax.chat/v1",
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ):
        self.api_key = api_key
        self.group_id = group_id
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def analyze_question(self, question_text: str, question_markdown: str, image_urls: List[str] = None) -> Dict[str, Any]:
        """
        使用 MiniMax API 分析题目（支持多模态）
        
        Args:
            question_text: 题目纯文本
            question_markdown: 题目 Markdown 格式
            image_urls: 图片 URL 列表（用于多模态分析）
        """
        
        system_prompt = """你是一个专业的教育分析助手，负责分析学生作业和错题。

请分析题目并输出 JSON 格式的结果，包含以下字段：
- subject: 学科（数学/物理/化学/生物/语文/英语/历史/地理/政治）
- grade: 年级（如：七年级、八年级、高一）
- question_type: 题型（选择题/填空题/简答题/计算题/证明题/实验题/阅读理解/写作题）
- knowledge_points: 知识点列表（数组）
- prerequisites: 前置知识列表（数组）
- difficulty: 难度（1-5，1最简单，5最难）
- likely_error_causes: 可能的错因列表（数组）
- review_priority: 复习优先级（high/medium/low）
- need_review: 是否需要复习（true/false）
- confidence: 分析置信度（0-1）

只输出 JSON，不要其他内容。"""
        
        # 构建用户消息（支持多模态）
        user_content = f"请分析以下题目：\n\n{question_markdown}\n\n输出 JSON 格式的分析结果。"
        
        # 如果有图片，添加到消息中
        if image_urls:
            user_content += "\n\n图片："
            for img_url in image_urls:
                user_content += f"\n{img_url}"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        
        # MiniMax 需要 group_id
        url = f"{self.base_url}/text/chatcompletion_v2?GroupId={self.group_id}"
        
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=60,
        )
        
        if response.status_code != 200:
            raise AIAnalysisException(
                f"MiniMax API error: {response.status_code} - {response.text}"
            )
        
        result = response.json()
        
        # MiniMax 响应格式
        if "choices" in result and len(result["choices"]) > 0:
            content = result["choices"][0]["message"]["content"]
        else:
            raise AIAnalysisException(f"Invalid MiniMax response: {result}")
        
        # 尝试提取 JSON
        try:
            # 如果是 markdown 格式，提取 JSON 部分
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            
            analysis = json.loads(content)
            return analysis
        except json.JSONDecodeError as e:
            raise AIAnalysisException(f"Failed to parse AI response as JSON: {e}\nResponse: {content}")


class AIAnalysisService:
    """
    AI 分析服务
    
    用法:
        service = AIAnalysisService(provider=OpenAIProvider(api_key="..."))
        analysis = service.analyze_question(ocr_result)
    """
    
    def __init__(
        self,
        provider: AIProvider,
        enable_cache: bool = True,
        cache_ttl: int = 86400,  # 24 小时
    ):
        """
        初始化 AI 分析服务
        
        Args:
            provider: AI 提供商
            enable_cache: 是否启用缓存
            cache_ttl: 缓存过期时间（秒）
        """
        self.provider = provider
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, QuestionAnalysis] = {}
    
    def analyze_question(
        self,
        question_text: str,
        question_markdown: str,
        image_urls: List[str] = None,
        use_cache: bool = True,
    ) -> QuestionAnalysis:
        """
        分析题目
        
        Args:
            question_text: 题目纯文本
            question_markdown: 题目 Markdown 格式
            image_urls: 图片 URL 列表（用于多模态分析）
            use_cache: 是否使用缓存
            
        Returns:
            QuestionAnalysis: 分析结果
            
        Raises:
            AIAnalysisException: 分析失败
        """
        # 检查缓存
        if self.enable_cache and use_cache:
            cache_key = self._get_cache_key(question_text)
            if cache_key in self._cache:
                return self._cache[cache_key]
        
        # 调用 AI 分析
        try:
            # 检查 provider 是否支持多模态
            if image_urls and hasattr(self.provider, 'analyze_question'):
                # 尝试传递 image_urls 参数
                import inspect
                sig = inspect.signature(self.provider.analyze_question)
                if 'image_urls' in sig.parameters:
                    raw_result = self.provider.analyze_question(
                        question_text, question_markdown, image_urls=image_urls
                    )
                else:
                    # 不支持多模态，只传文本
                    raw_result = self.provider.analyze_question(question_text, question_markdown)
            else:
                raw_result = self.provider.analyze_question(question_text, question_markdown)
        except Exception as e:
            raise AIAnalysisException(f"AI analysis failed: {e}")
        
        # 解析结果
        analysis = self._parse_analysis(raw_result)
        
        # 写入缓存
        if self.enable_cache:
            cache_key = self._get_cache_key(question_text)
            self._cache[cache_key] = analysis
        
        return analysis
    
    def _get_cache_key(self, question_text: str) -> str:
        """生成缓存 key（使用文本 hash）"""
        return hashlib.sha256(question_text.encode()).hexdigest()
    
    def _parse_analysis(self, raw_result: Dict[str, Any]) -> QuestionAnalysis:
        """
        解析 AI 分析结果
        
        Args:
            raw_result: 原始 AI 响应
            
        Returns:
            QuestionAnalysis: 解析后的分析结果
        """
        try:
            return QuestionAnalysis(
                subject=raw_result.get("subject", "未知"),
                grade=raw_result.get("grade", "未知"),
                question_type=raw_result.get("question_type", "未知"),
                knowledge_points=raw_result.get("knowledge_points", []),
                prerequisites=raw_result.get("prerequisites", []),
                difficulty=int(raw_result.get("difficulty", 3)),
                likely_error_causes=raw_result.get("likely_error_causes", []),
                review_priority=raw_result.get("review_priority", "medium"),
                need_review=raw_result.get("need_review", True),
                confidence=float(raw_result.get("confidence", 0.8)),
                raw_response=json.dumps(raw_result, ensure_ascii=False),
            )
        except (KeyError, ValueError, TypeError) as e:
            raise AIAnalysisException(f"Failed to parse analysis result: {e}")
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
    
    def get_cache_size(self) -> int:
        """获取缓存大小"""
        return len(self._cache)


class AIAnalysisException(Exception):
    """AI 分析异常"""
    pass
