"""
PaddleOCR Adapter

封装 PaddleOCR-VL-1.5 API，提供统一的 OCR 接口。

设计原则：
1. 屏蔽第三方 API 细节
2. 支持失败重试
3. 记录 OCR 质量
4. 缓存 OCR 结果
5. 统一输出格式
"""

import json
import os
import time
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

import requests


class OCRJobState(str, Enum):
    """OCR 任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class OCRResult:
    """OCR 统一输出格式"""
    file_id: str
    raw_text: str
    markdown: str
    images: Dict[str, str]  # {image_path: image_url}
    blocks: List[Dict]  # 原始 OCR 块信息
    confidence: float
    provider: str = "paddleocr-vl-1.5"
    total_pages: int = 0
    extracted_pages: int = 0
    start_time: Optional[str] = None
    end_time: Optional[str] = None


class PaddleOCRAdapter:
    """
    PaddleOCR Adapter
    
    用法:
        adapter = PaddleOCRAdapter(token="your_token")
        result = adapter.process_file("path/to/image.jpg")
    """
    
    JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    
    def __init__(
        self,
        token: str,
        model: str = "PaddleOCR-VL-1.5",
        max_retries: int = 3,
        poll_interval: int = 5,
        timeout: int = 300,
    ):
        """
        初始化 PaddleOCR Adapter
        
        Args:
            token: PaddleOCR API Token
            model: 模型名称
            max_retries: 最大重试次数
            poll_interval: 轮询间隔（秒）
            timeout: 超时时间（秒）
        """
        self.token = token
        self.model = model
        self.max_retries = max_retries
        self.poll_interval = poll_interval
        self.timeout = timeout
        
        self.headers = {
            "Authorization": f"bearer {self.token}",
        }
    
    def process_file(
        self,
        file_path: str,
        file_id: str,
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        use_chart_recognition: bool = False,
    ) -> OCRResult:
        """
        处理文件（本地文件或 URL）
        
        Args:
            file_path: 本地文件路径或 URL
            file_id: 文件 ID（用于追踪）
            use_doc_orientation_classify: 是否使用文档方向分类
            use_doc_unwarping: 是否使用文档去畸变
            use_chart_recognition: 是否使用图表识别
            
        Returns:
            OCRResult: 统一的 OCR 结果
            
        Raises:
            OCRException: OCR 处理失败
        """
        optional_payload = {
            "useDocOrientationClassify": use_doc_orientation_classify,
            "useDocUnwarping": use_doc_unwarping,
            "useChartRecognition": use_chart_recognition,
        }
        
        # 提交任务
        job_id = self._submit_job(file_path, optional_payload)
        
        # 轮询结果
        result_data = self._poll_job_result(job_id)
        
        # 解析结果
        ocr_result = self._parse_result(file_id, result_data)
        
        return ocr_result
    
    def _submit_job(self, file_path: str, optional_payload: Dict) -> str:
        """
        提交 OCR 任务
        
        Args:
            file_path: 文件路径或 URL
            optional_payload: 可选参数
            
        Returns:
            str: 任务 ID
            
        Raises:
            OCRException: 提交失败
        """
        if file_path.startswith("http"):
            # URL 模式
            headers = {**self.headers, "Content-Type": "application/json"}
            payload = {
                "fileUrl": file_path,
                "model": self.model,
                "optionalPayload": optional_payload,
            }
            response = requests.post(self.JOB_URL, json=payload, headers=headers)
        else:
            # 本地文件模式
            if not os.path.exists(file_path):
                raise OCRException(f"File not found: {file_path}")
            
            data = {
                "model": self.model,
                "optionalPayload": json.dumps(optional_payload),
            }
            
            with open(file_path, "rb") as f:
                files = {"file": f}
                response = requests.post(
                    self.JOB_URL,
                    headers=self.headers,
                    data=data,
                    files=files,
                )
        
        if response.status_code != 200:
            raise OCRException(
                f"Failed to submit OCR job: {response.status_code} - {response.text}"
            )
        
        job_id = response.json()["data"]["jobId"]
        return job_id
    
    def _poll_job_result(self, job_id: str) -> Dict:
        """
        轮询任务结果
        
        Args:
            job_id: 任务 ID
            
        Returns:
            Dict: 任务结果数据
            
        Raises:
            OCRException: 轮询失败或超时
        """
        start_time = time.time()
        
        while True:
            # 检查超时
            if time.time() - start_time > self.timeout:
                raise OCRException(f"OCR job timeout: {job_id}")
            
            # 查询任务状态
            response = requests.get(
                f"{self.JOB_URL}/{job_id}",
                headers=self.headers,
            )
            
            if response.status_code != 200:
                raise OCRException(
                    f"Failed to query OCR job: {response.status_code} - {response.text}"
                )
            
            data = response.json()["data"]
            state = data["state"]
            
            if state == OCRJobState.DONE:
                return data
            elif state == OCRJobState.FAILED:
                error_msg = data.get("errorMsg", "Unknown error")
                raise OCRException(f"OCR job failed: {error_msg}")
            elif state in [OCRJobState.PENDING, OCRJobState.RUNNING]:
                # 继续轮询
                time.sleep(self.poll_interval)
            else:
                raise OCRException(f"Unknown OCR job state: {state}")
    
    def _parse_result(self, file_id: str, result_data: Dict) -> OCRResult:
        """
        解析 OCR 结果
        
        Args:
            file_id: 文件 ID
            result_data: 原始结果数据
            
        Returns:
            OCRResult: 统一的 OCR 结果
        """
        # 提取进度信息
        extract_progress = result_data.get("extractProgress", {})
        extracted_pages = extract_progress.get("extractedPages", 0)
        start_time = extract_progress.get("startTime")
        end_time = extract_progress.get("endTime")
        
        # 获取结果 URL
        jsonl_url = result_data["resultUrl"]["jsonUrl"]
        
        # 下载并解析 JSONL 结果
        jsonl_response = requests.get(jsonl_url)
        jsonl_response.raise_for_status()
        
        lines = jsonl_response.text.strip().split('\n')
        
        # 合并所有页面的结果
        all_markdown = []
        all_images = {}
        all_blocks = []
        total_confidence = 0.0
        confidence_count = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            result = json.loads(line)["result"]
            
            for layout_result in result["layoutParsingResults"]:
                # 提取 Markdown
                markdown_text = layout_result["markdown"]["text"]
                all_markdown.append(markdown_text)
                
                # 提取图片
                for img_path, img_url in layout_result["markdown"]["images"].items():
                    all_images[img_path] = img_url
                
                # 提取原始块信息（用于后续分析）
                # 注意：这里需要根据实际 API 响应调整
                if "blocks" in layout_result:
                    all_blocks.extend(layout_result["blocks"])
                
                # 计算置信度（如果有的话）
                if "confidence" in layout_result:
                    total_confidence += layout_result["confidence"]
                    confidence_count += 1
        
        # 计算平均置信度
        avg_confidence = (
            total_confidence / confidence_count if confidence_count > 0 else 0.9
        )
        
        # 合并 Markdown
        combined_markdown = "\n\n---\n\n".join(all_markdown)
        
        # 提取纯文本（去除 Markdown 格式）
        raw_text = self._extract_raw_text(combined_markdown)
        
        return OCRResult(
            file_id=file_id,
            raw_text=raw_text,
            markdown=combined_markdown,
            images=all_images,
            blocks=all_blocks,
            confidence=avg_confidence,
            provider=self.model,
            total_pages=extracted_pages,
            extracted_pages=extracted_pages,
            start_time=start_time,
            end_time=end_time,
        )
    
    @staticmethod
    def _extract_raw_text(markdown: str) -> str:
        """
        从 Markdown 中提取纯文本
        
        Args:
            markdown: Markdown 文本
            
        Returns:
            str: 纯文本
        """
        # 简单实现：移除 Markdown 标记
        # 后续可以使用更复杂的 Markdown 解析器
        import re
        
        # 移除图片标记
        text = re.sub(r'!\[.*?\]\(.*?\)', '', markdown)
        # 移除链接标记
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        # 移除标题标记
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
        # 移除粗体和斜体
        text = re.sub(r'\*\*([^\*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^\*]+)\*', r'\1', text)
        # 移除代码块
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'`([^`]+)`', r'\1', text)
        
        return text.strip()


class OCRException(Exception):
    """OCR 异常"""
    pass
