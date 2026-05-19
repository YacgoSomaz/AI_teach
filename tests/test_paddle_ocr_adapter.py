"""
PaddleOCR Adapter 测试

测试驱动开发（TDD）原则：先写测试，再写代码
"""

import pytest
from unittest.mock import Mock, patch, mock_open
from src.adapters.ocr.paddle_ocr_adapter import (
    PaddleOCRAdapter,
    OCRResult,
    OCRJobState,
    OCRException,
)


@pytest.fixture
def adapter():
    """创建 PaddleOCR Adapter 实例"""
    return PaddleOCRAdapter(
        token="test_token",
        poll_interval=0.1,  # 测试时使用更短的轮询间隔
        timeout=10,
    )


@pytest.fixture
def mock_job_response():
    """模拟任务提交响应"""
    return {
        "data": {
            "jobId": "test_job_123"
        }
    }


@pytest.fixture
def mock_job_done_response():
    """模拟任务完成响应"""
    return {
        "data": {
            "state": "done",
            "extractProgress": {
                "extractedPages": 1,
                "startTime": "2024-01-01T00:00:00Z",
                "endTime": "2024-01-01T00:00:10Z",
            },
            "resultUrl": {
                "jsonUrl": "https://example.com/result.jsonl"
            }
        }
    }


@pytest.fixture
def mock_jsonl_content():
    """模拟 JSONL 结果内容"""
    return '''{"result": {"layoutParsingResults": [{"markdown": {"text": "# 题目\\n\\n1. 计算浮力大小", "images": {"img1.jpg": "https://example.com/img1.jpg"}}}]}}'''


class TestPaddleOCRAdapter:
    """PaddleOCR Adapter 测试类"""
    
    def test_init(self, adapter):
        """测试初始化"""
        assert adapter.token == "test_token"
        assert adapter.model == "PaddleOCR-VL-1.5"
        assert adapter.max_retries == 3
        assert adapter.poll_interval == 0.1
        assert adapter.timeout == 10
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.post')
    def test_submit_job_with_url(self, mock_post, adapter, mock_job_response):
        """测试提交 URL 模式的任务"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_job_response
        
        job_id = adapter._submit_job(
            "https://example.com/image.jpg",
            {"useDocOrientationClassify": False}
        )
        
        assert job_id == "test_job_123"
        assert mock_post.called
        
        # 验证请求参数
        call_args = mock_post.call_args
        assert "fileUrl" in call_args[1]["json"]
        assert call_args[1]["json"]["fileUrl"] == "https://example.com/image.jpg"
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.post')
    @patch('builtins.open', new_callable=mock_open, read_data=b'fake image data')
    @patch('os.path.exists', return_value=True)
    def test_submit_job_with_local_file(
        self, mock_exists, mock_file, mock_post, adapter, mock_job_response
    ):
        """测试提交本地文件模式的任务"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_job_response
        
        job_id = adapter._submit_job(
            "/path/to/image.jpg",
            {"useDocOrientationClassify": False}
        )
        
        assert job_id == "test_job_123"
        assert mock_post.called
        assert mock_file.called
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.post')
    def test_submit_job_failure(self, mock_post, adapter):
        """测试任务提交失败"""
        mock_post.return_value.status_code = 400
        mock_post.return_value.text = "Bad Request"
        
        with pytest.raises(OCRException) as exc_info:
            adapter._submit_job(
                "https://example.com/image.jpg",
                {"useDocOrientationClassify": False}
            )
        
        assert "Failed to submit OCR job" in str(exc_info.value)
    
    def test_submit_job_file_not_found(self, adapter):
        """测试本地文件不存在"""
        with pytest.raises(OCRException) as exc_info:
            adapter._submit_job(
                "/nonexistent/file.jpg",
                {"useDocOrientationClassify": False}
            )
        
        assert "File not found" in str(exc_info.value)
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    def test_poll_job_result_success(
        self, mock_get, adapter, mock_job_done_response
    ):
        """测试轮询任务成功"""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_job_done_response
        
        result = adapter._poll_job_result("test_job_123")
        
        assert result["state"] == "done"
        assert result["extractProgress"]["extractedPages"] == 1
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    @patch('time.sleep', return_value=None)  # 跳过实际睡眠
    def test_poll_job_result_with_pending_state(
        self, mock_sleep, mock_get, adapter, mock_job_done_response
    ):
        """测试轮询任务（先 pending 再 done）"""
        # 第一次返回 pending，第二次返回 done
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.side_effect = [
            {"data": {"state": "pending"}},
            mock_job_done_response,
        ]
        
        result = adapter._poll_job_result("test_job_123")
        
        assert result["state"] == "done"
        assert mock_get.call_count == 2
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    def test_poll_job_result_failed(self, mock_get, adapter):
        """测试任务失败"""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "data": {
                "state": "failed",
                "errorMsg": "OCR processing failed"
            }
        }
        
        with pytest.raises(OCRException) as exc_info:
            adapter._poll_job_result("test_job_123")
        
        assert "OCR job failed" in str(exc_info.value)
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    @patch('time.time')
    def test_poll_job_result_timeout(self, mock_time, mock_get, adapter):
        """测试任务超时"""
        # 模拟超时
        mock_time.side_effect = [0, 1000]  # 第二次调用返回超时时间
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "data": {"state": "running"}
        }
        
        with pytest.raises(OCRException) as exc_info:
            adapter._poll_job_result("test_job_123")
        
        assert "timeout" in str(exc_info.value)
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    def test_parse_result(
        self, mock_get, adapter, mock_job_done_response, mock_jsonl_content
    ):
        """测试解析结果"""
        mock_get.return_value.text = mock_jsonl_content
        mock_get.return_value.raise_for_status = Mock()
        
        result = adapter._parse_result("file_123", mock_job_done_response["data"])
        
        assert isinstance(result, OCRResult)
        assert result.file_id == "file_123"
        assert result.provider == "PaddleOCR-VL-1.5"
        assert result.extracted_pages == 1
        assert "题目" in result.markdown
        assert "浮力" in result.raw_text
        assert len(result.images) > 0
    
    def test_extract_raw_text(self, adapter):
        """测试提取纯文本"""
        markdown = """
# 题目

1. 计算**浮力**大小

![图片](image.jpg)

[链接](https://example.com)

`代码`

```python
print("hello")
```
        """
        
        raw_text = adapter._extract_raw_text(markdown)
        
        assert "题目" in raw_text
        assert "浮力" in raw_text
        assert "![" not in raw_text  # 图片标记已移除
        assert "**" not in raw_text  # 粗体标记已移除
        assert "```" not in raw_text  # 代码块已移除
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.post')
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    def test_process_file_end_to_end(
        self,
        mock_get,
        mock_post,
        adapter,
        mock_job_response,
        mock_job_done_response,
        mock_jsonl_content,
    ):
        """测试完整流程"""
        # Mock 任务提交
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = mock_job_response
        
        # Mock 任务查询
        mock_get_responses = [
            Mock(status_code=200, json=lambda: mock_job_done_response),  # 任务状态查询
            Mock(text=mock_jsonl_content, raise_for_status=Mock()),  # JSONL 下载
        ]
        mock_get.side_effect = mock_get_responses
        
        result = adapter.process_file(
            "https://example.com/image.jpg",
            "file_123"
        )
        
        assert isinstance(result, OCRResult)
        assert result.file_id == "file_123"
        assert result.extracted_pages == 1
        assert len(result.markdown) > 0
        assert len(result.raw_text) > 0


class TestOCRResult:
    """OCR 结果测试"""
    
    def test_ocr_result_creation(self):
        """测试创建 OCR 结果"""
        result = OCRResult(
            file_id="test_123",
            raw_text="测试文本",
            markdown="# 测试",
            images={"img1.jpg": "https://example.com/img1.jpg"},
            blocks=[],
            confidence=0.95,
            total_pages=1,
            extracted_pages=1,
        )
        
        assert result.file_id == "test_123"
        assert result.confidence == 0.95
        assert result.provider == "paddleocr-vl-1.5"


class TestEdgeCases:
    """边界情况测试 - 补充覆盖率"""
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    def test_poll_job_query_failure(self, mock_get, adapter):
        """测试轮询时查询失败（覆盖第 205 行）"""
        mock_get.return_value.status_code = 500
        mock_get.return_value.text = "Internal Server Error"
        
        with pytest.raises(OCRException) as exc_info:
            adapter._poll_job_result("test_job_123")
        
        assert "Failed to query OCR job" in str(exc_info.value)
        assert "500" in str(exc_info.value)
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    def test_poll_job_unknown_state(self, mock_get, adapter):
        """测试未知任务状态（覆盖第 221 行）"""
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "data": {"state": "unknown_state"}
        }
        
        with pytest.raises(OCRException) as exc_info:
            adapter._poll_job_result("test_job_123")
        
        assert "Unknown OCR job state" in str(exc_info.value)
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    def test_parse_result_with_blocks(self, mock_get, adapter):
        """测试解析包含 blocks 的结果（覆盖第 259 行）"""
        mock_jsonl_content = '''{"result": {"layoutParsingResults": [{"markdown": {"text": "# 测试", "images": {}}, "blocks": [{"type": "text", "content": "测试"}]}]}}'''
        
        mock_get.return_value.text = mock_jsonl_content
        mock_get.return_value.raise_for_status = Mock()
        
        result_data = {
            "extractProgress": {
                "extractedPages": 1,
                "startTime": "2024-01-01T00:00:00Z",
                "endTime": "2024-01-01T00:00:10Z",
            },
            "resultUrl": {
                "jsonUrl": "https://example.com/result.jsonl"
            }
        }
        
        result = adapter._parse_result("file_123", result_data)
        
        assert len(result.blocks) == 1
        assert result.blocks[0]["type"] == "text"
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    def test_parse_result_with_confidence(self, mock_get, adapter):
        """测试解析包含置信度的结果（覆盖第 275 行）"""
        mock_jsonl_content = '''{"result": {"layoutParsingResults": [{"markdown": {"text": "# 测试", "images": {}}, "confidence": 0.88}]}}'''
        
        mock_get.return_value.text = mock_jsonl_content
        mock_get.return_value.raise_for_status = Mock()
        
        result_data = {
            "extractProgress": {
                "extractedPages": 1,
                "startTime": "2024-01-01T00:00:00Z",
                "endTime": "2024-01-01T00:00:10Z",
            },
            "resultUrl": {
                "jsonUrl": "https://example.com/result.jsonl"
            }
        }
        
        result = adapter._parse_result("file_123", result_data)
        
        assert result.confidence == 0.88
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    def test_parse_result_no_confidence(self, mock_get, adapter):
        """测试解析不包含置信度的结果（覆盖第 279-280 行）"""
        mock_jsonl_content = '''{"result": {"layoutParsingResults": [{"markdown": {"text": "# 测试", "images": {}}}]}}'''
        
        mock_get.return_value.text = mock_jsonl_content
        mock_get.return_value.raise_for_status = Mock()
        
        result_data = {
            "extractProgress": {
                "extractedPages": 1,
                "startTime": "2024-01-01T00:00:00Z",
                "endTime": "2024-01-01T00:00:10Z",
            },
            "resultUrl": {
                "jsonUrl": "https://example.com/result.jsonl"
            }
        }
        
        result = adapter._parse_result("file_123", result_data)
        
        # 当没有置信度时，应该使用默认值 0.9
        assert result.confidence == 0.9
    
    @patch('src.adapters.ocr.paddle_ocr_adapter.requests.get')
    def test_parse_result_empty_lines(self, mock_get, adapter):
        """测试解析包含空行的 JSONL"""
        mock_jsonl_content = '''{"result": {"layoutParsingResults": [{"markdown": {"text": "# 测试1", "images": {}}}]}}

{"result": {"layoutParsingResults": [{"markdown": {"text": "# 测试2", "images": {}}}]}}'''
        
        mock_get.return_value.text = mock_jsonl_content
        mock_get.return_value.raise_for_status = Mock()
        
        result_data = {
            "extractProgress": {
                "extractedPages": 2,
                "startTime": "2024-01-01T00:00:00Z",
                "endTime": "2024-01-01T00:00:10Z",
            },
            "resultUrl": {
                "jsonUrl": "https://example.com/result.jsonl"
            }
        }
        
        result = adapter._parse_result("file_123", result_data)
        
        assert result.extracted_pages == 2
        assert "测试1" in result.markdown
        assert "测试2" in result.markdown
