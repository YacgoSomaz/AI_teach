# OCR Adapter 设计文档

## 1. 设计目标

OCR Adapter 是 AI 复习导航系统的入口模块，负责将学生拍摄的作业/错题图片转换为结构化文本。

### 核心设计原则

1. **屏蔽第三方 API 细节** - 业务代码不直接调用 PaddleOCR API
2. **支持后续替换 OCR 服务** - 统一接口，方便切换其他 OCR 服务
3. **支持失败重试** - 网络不稳定时自动重试
4. **记录 OCR 质量** - 记录置信度，用于后续质量评估
5. **缓存 OCR 结果** - 避免重复处理相同图片
6. **统一输出格式** - 标准化的 OCRResult 对象

## 2. 架构设计

```
业务代码
    ↓
OCR Adapter (统一接口)
    ↓
PaddleOCR API
```

### 为什么需要 Adapter？

**不使用 Adapter 的问题：**
- 业务代码直接调用 PaddleOCR API
- 如果要换 OCR 服务，需要修改所有调用点
- 重试、缓存、质量记录等逻辑散落在各处
- 难以测试（依赖真实 API）

**使用 Adapter 的好处：**
- 业务代码只依赖 Adapter 接口
- 切换 OCR 服务只需实现新的 Adapter
- 重试、缓存、质量记录集中管理
- 易于测试（Mock Adapter）

## 3. 接口设计

### 3.1 核心类

#### PaddleOCRAdapter

```python
class PaddleOCRAdapter:
    def __init__(
        self,
        token: str,
        model: str = "PaddleOCR-VL-1.5",
        max_retries: int = 3,
        poll_interval: int = 5,
        timeout: int = 300,
    ):
        """初始化 Adapter"""
        pass
    
    def process_file(
        self,
        file_path: str,
        file_id: str,
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        use_chart_recognition: bool = False,
    ) -> OCRResult:
        """处理文件（本地文件或 URL）"""
        pass
```

#### OCRResult

```python
@dataclass
class OCRResult:
    """OCR 统一输出格式"""
    file_id: str                    # 文件 ID
    raw_text: str                   # 纯文本
    markdown: str                   # Markdown 格式
    images: Dict[str, str]          # 图片映射
    blocks: List[Dict]              # 原始 OCR 块
    confidence: float               # 置信度
    provider: str                   # OCR 提供商
    total_pages: int                # 总页数
    extracted_pages: int            # 已提取页数
    start_time: Optional[str]       # 开始时间
    end_time: Optional[str]         # 结束时间
```

### 3.2 异常设计

```python
class OCRException(Exception):
    """OCR 异常基类"""
    pass
```

## 4. 工作流程

### 4.1 完整流程

```
1. 提交任务
   ├─ URL 模式：直接提交 URL
   └─ 本地文件模式：上传文件

2. 轮询结果
   ├─ pending → 继续轮询
   ├─ running → 继续轮询
   ├─ done → 下载结果
   └─ failed → 抛出异常

3. 解析结果
   ├─ 下载 JSONL 文件
   ├─ 解析 Markdown
   ├─ 提取图片
   ├─ 计算置信度
   └─ 返回 OCRResult
```

### 4.2 状态机

```
created → pending → running → done
                            ↘ failed
```

## 5. 使用示例

### 5.1 基本使用

```python
from src.adapters.ocr import PaddleOCRAdapter

# 创建 Adapter
adapter = PaddleOCRAdapter(token="your_token")

# 处理文件
result = adapter.process_file(
    file_path="homework.jpg",
    file_id="hw_001"
)

# 使用结果
print(f"置信度: {result.confidence}")
print(f"文本: {result.raw_text}")
print(f"Markdown: {result.markdown}")
```

### 5.2 批量处理

```python
files = [
    ("hw_001.jpg", "file_001"),
    ("hw_002.jpg", "file_002"),
]

results = []
for file_path, file_id in files:
    result = adapter.process_file(file_path, file_id)
    results.append(result)
```

### 5.3 错误处理

```python
from src.adapters.ocr import OCRException

try:
    result = adapter.process_file("homework.jpg", "hw_001")
except OCRException as e:
    print(f"OCR 失败: {e}")
    # 降级处理：允许用户手动输入
```

## 6. 测试策略

### 6.1 单元测试

使用 Mock 模拟 PaddleOCR API 响应：

```python
@patch('requests.post')
def test_submit_job(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "data": {"jobId": "test_123"}
    }
    
    adapter = PaddleOCRAdapter(token="test")
    job_id = adapter._submit_job("test.jpg", {})
    
    assert job_id == "test_123"
```

### 6.2 集成测试

使用真实 API 测试（需要 Token）：

```python
def test_real_ocr():
    adapter = PaddleOCRAdapter(token=os.getenv("PADDLEOCR_TOKEN"))
    result = adapter.process_file("test_homework.jpg", "test_001")
    
    assert result.confidence > 0.8
    assert len(result.raw_text) > 0
```

### 6.3 测试覆盖率目标

- 单元测试覆盖率：≥ 90%
- 集成测试覆盖率：≥ 70%

## 7. 性能优化

### 7.1 缓存策略

```python
# 使用图片 hash 作为缓存 key
import hashlib

def get_file_hash(file_path: str) -> str:
    with open(file_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

# 检查缓存
cache_key = f"ocr:{get_file_hash(file_path)}"
cached_result = redis.get(cache_key)

if cached_result:
    return OCRResult(**json.loads(cached_result))

# 调用 OCR
result = adapter.process_file(file_path, file_id)

# 写入缓存
redis.setex(cache_key, 86400, json.dumps(result.__dict__))
```

### 7.2 成本控制

```python
# 记录每次 OCR 调用
ocr_log = {
    "file_id": file_id,
    "file_size": os.path.getsize(file_path),
    "pages": result.extracted_pages,
    "cost": calculate_cost(result.extracted_pages),
    "timestamp": datetime.now(),
}

db.save_ocr_log(ocr_log)
```

## 8. 后续扩展

### 8.1 支持其他 OCR 服务

```python
class OCRAdapterInterface(ABC):
    @abstractmethod
    def process_file(self, file_path: str, file_id: str) -> OCRResult:
        pass

class PaddleOCRAdapter(OCRAdapterInterface):
    # 当前实现
    pass

class TesseractOCRAdapter(OCRAdapterInterface):
    # 新的实现
    pass

# 工厂模式
def create_ocr_adapter(provider: str) -> OCRAdapterInterface:
    if provider == "paddleocr":
        return PaddleOCRAdapter(...)
    elif provider == "tesseract":
        return TesseractOCRAdapter(...)
```

### 8.2 质量评估

```python
def evaluate_ocr_quality(result: OCRResult) -> Dict:
    """评估 OCR 质量"""
    return {
        "confidence": result.confidence,
        "text_length": len(result.raw_text),
        "has_images": len(result.images) > 0,
        "quality_score": calculate_quality_score(result),
    }
```

## 9. 注意事项

### 9.1 安全性

- ⚠️ **Token 不要写死在代码中**，使用环境变量
- ⚠️ **图片 URL 使用临时 URL**，设置过期时间
- ⚠️ **记录日志时不要打印 Token**

### 9.2 可靠性

- ✅ 支持失败重试（最多 3 次）
- ✅ 支持超时控制（默认 5 分钟）
- ✅ 支持降级处理（OCR 失败时允许手动输入）

### 9.3 成本

- 💰 每次 OCR 调用都有成本
- 💰 使用缓存避免重复处理
- 💰 记录每次调用成本，便于后续优化

## 10. 参考资料

- [PaddleOCR-VL-1.5 API 文档](https://paddleocr.aistudio-app.com)
- [项目技术架构文档](../ai-review-navigation-architecture.md)
