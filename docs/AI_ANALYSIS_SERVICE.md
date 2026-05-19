# AI 分析服务设计文档

## 1. 设计目标

AI 分析服务负责分析 OCR 识别的题目，提取知识点、难度、错因等结构化信息。

### 核心设计原则

1. **支持多种 AI 提供商** - OpenAI、豆包、MiniMax 等
2. **支持多模态分析** - 文本 + 图片（几何图形、图表等）
3. **结构化输出** - JSON Schema，便于后续处理
4. **成本控制** - 缓存、模型路由
5. **质量评估** - 置信度评分

---

## 2. 架构设计

```
OCR Result (文本 + 图片)
    ↓
AI Analysis Service
    ↓
AI Provider (OpenAI / 豆包 / MiniMax)
    ↓
QuestionAnalysis (结构化结果)
```

---

## 3. 支持的 AI 提供商

### 3.1 OpenAI

- **模型**: gpt-4o-mini, gpt-4o
- **特点**: 质量高，成本较高
- **多模态**: 支持（gpt-4o）
- **JSON 输出**: 原生支持

### 3.2 豆包（字节跳动）⭐ 推荐

- **模型**: doubao-pro-32k
- **特点**: 国产模型，性价比高
- **多模态**: ✅ 支持
- **JSON 输出**: 需要提取

**为什么推荐豆包？**
- ✅ 支持多模态（文本 + 图片）
- ✅ 国产模型，访问稳定
- ✅ 成本较低
- ✅ 中文理解能力强

### 3.3 MiniMax ⭐ 推荐

- **模型**: abab6.5s-chat
- **特点**: 国产模型，性价比高
- **多模态**: ✅ 支持
- **JSON 输出**: 需要提取

**为什么推荐 MiniMax？**
- ✅ 支持多模态（文本 + 图片）
- ✅ 国产模型，访问稳定
- ✅ 成本较低
- ✅ 中文理解能力强

---

## 4. 多模态分析

### 4.1 为什么需要多模态？

OCR 识别的题目中，经常包含：
- 几何图形（三角形、圆形等）
- 物理图（电路图、受力图等）
- 化学结构式
- 图表、表格

这些图形信息无法完全用文本表达，需要 AI 直接"看"图片。

### 4.2 多模态工作流程

```
1. OCR 识别
   ├─ 提取文本
   └─ 提取图片 URL

2. AI 分析
   ├─ 输入：文本 + 图片 URL
   └─ 输出：结构化分析结果

3. 知识点归档
```

### 4.3 示例

**题目：** "如图所示，求三角形 ABC 的面积"

**OCR 输出：**
- 文本：`"如图所示，求三角形 ABC 的面积"`
- 图片：`["https://oss.example.com/triangle.jpg"]`

**AI 分析：**
- 输入：文本 + 图片
- 输出：
  ```json
  {
    "subject": "数学",
    "knowledge_points": ["三角形面积", "勾股定理"],
    "difficulty": 2
  }
  ```

---

## 5. 输出格式

### 5.1 QuestionAnalysis

```python
@dataclass
class QuestionAnalysis:
    subject: str              # 学科
    grade: str                # 年级
    question_type: str        # 题型
    knowledge_points: List[str]  # 知识点列表
    prerequisites: List[str]     # 前置知识
    difficulty: int              # 难度（1-5）
    likely_error_causes: List[str]  # 可能错因
    review_priority: str         # 复习优先级
    need_review: bool            # 是否需要复习
    confidence: float            # 置信度
```

### 5.2 示例输出

```json
{
  "subject": "物理",
  "grade": "八年级",
  "question_type": "选择题",
  "knowledge_points": ["浮力", "阿基米德原理"],
  "prerequisites": ["密度", "重力"],
  "difficulty": 3,
  "likely_error_causes": ["概念混淆", "条件判断错误"],
  "review_priority": "high",
  "need_review": true,
  "confidence": 0.9
}
```

---

## 6. 使用示例

### 6.1 使用豆包（推荐）

```python
from src.services.ai_analysis_service import AIAnalysisService, DoubaoProvider

# 创建豆包 Provider
provider = DoubaoProvider(
    api_key="your_doubao_api_key",
    model="doubao-pro-32k",
)

# 创建 AI 分析服务
service = AIAnalysisService(provider=provider)

# 分析题目（支持多模态）
analysis = service.analyze_question(
    question_text="如图所示，求三角形面积",
    question_markdown="# 题目\n\n如图所示，求三角形面积",
    image_urls=["https://oss.example.com/triangle.jpg"],
)

print(f"学科: {analysis.subject}")
print(f"知识点: {analysis.knowledge_points}")
```

### 6.2 使用 MiniMax

```python
from src.services.ai_analysis_service import AIAnalysisService, MinimaxProvider

# 创建 MiniMax Provider
provider = MinimaxProvider(
    api_key="your_minimax_api_key",
    group_id="your_group_id",
    model="abab6.5s-chat",
)

# 创建 AI 分析服务
service = AIAnalysisService(provider=provider)

# 分析题目（支持多模态）
analysis = service.analyze_question(
    question_text="如图所示，求三角形面积",
    question_markdown="# 题目\n\n如图所示，求三角形面积",
    image_urls=["https://oss.example.com/triangle.jpg"],
)
```

### 6.3 完整流程（OCR + AI）

```python
from src.adapters.ocr import PaddleOCRAdapter
from src.services.ai_analysis_service import AIAnalysisService, DoubaoProvider

# 1. OCR 识别
ocr_adapter = PaddleOCRAdapter(token="your_token")
ocr_result = ocr_adapter.process_file("homework.jpg", "hw_001")

# 2. AI 分析（自动使用 OCR 提取的图片）
provider = DoubaoProvider(api_key="your_key")
ai_service = AIAnalysisService(provider=provider)

analysis = ai_service.analyze_question(
    question_text=ocr_result.raw_text,
    question_markdown=ocr_result.markdown,
    image_urls=list(ocr_result.images.values()),  # 传递图片
)

# 3. 使用结果
print(f"学科: {analysis.subject}")
print(f"知识点: {', '.join(analysis.knowledge_points)}")
print(f"难度: {analysis.difficulty}/5")
```

---

## 7. 成本控制

### 7.1 缓存策略

```python
# 启用缓存（默认）
service = AIAnalysisService(
    provider=provider,
    enable_cache=True,  # 启用缓存
    cache_ttl=86400,    # 24 小时
)

# 相同题目不会重复调用 AI
analysis1 = service.analyze_question(text, markdown)
analysis2 = service.analyze_question(text, markdown)  # 使用缓存

# 查看缓存大小
print(f"缓存大小: {service.get_cache_size()}")

# 清空缓存
service.clear_cache()
```

### 7.2 模型选择

| 模型 | 成本 | 质量 | 多模态 | 推荐场景 |
|------|------|------|--------|----------|
| gpt-4o-mini | 中 | 高 | ✅ | 预算充足 |
| doubao-pro-32k | 低 | 中高 | ✅ | 生产环境 ⭐ |
| abab6.5s-chat | 低 | 中高 | ✅ | 生产环境 ⭐ |

---

## 8. 质量评估

### 8.1 置信度

每个分析结果都包含置信度（0-1）：
- `>= 0.9`: 高置信度，可直接使用
- `0.7-0.9`: 中等置信度，建议人工确认
- `< 0.7`: 低置信度，需要人工修正

### 8.2 人工校正闭环

```python
# 1. AI 分析
analysis = service.analyze_question(text, markdown)

# 2. 检查置信度
if analysis.confidence < 0.7:
    # 低置信度，进入人工校正
    corrected_analysis = human_review(analysis)
    
    # 3. 校正结果回写样本库
    save_to_training_data(text, corrected_analysis)
```

---

## 9. 测试

### 9.1 单元测试

```bash
# 运行测试
pytest tests/test_ai_analysis_service.py -v

# 查看覆盖率
pytest tests/test_ai_analysis_service.py --cov=src/services --cov-report=html
```

### 9.2 测试覆盖率

- ✅ 单元测试：21 个
- ✅ 覆盖率：99%
- ✅ 边界测试：完整

---

## 10. 环境变量配置

```bash
# 豆包（推荐）
DOUBAO_API_KEY=your_doubao_api_key
DOUBAO_MODEL=doubao-pro-32k
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

# MiniMax（推荐）
MINIMAX_API_KEY=your_minimax_api_key
MINIMAX_GROUP_ID=your_group_id
MINIMAX_MODEL=abab6.5s-chat

# OpenAI（可选）
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
```

---

## 11. 注意事项

### 11.1 多模态限制

- 图片必须是公网可访问的 URL
- 图片大小建议 < 5MB
- 支持格式：JPG、PNG

### 11.2 成本控制

- ✅ 启用缓存，避免重复分析
- ✅ 使用国产模型（豆包、MiniMax）
- ✅ 记录每次调用成本

### 11.3 安全性

- ⚠️ API Key 使用环境变量
- ⚠️ 图片 URL 使用临时 URL
- ⚠️ 不在日志中打印 API Key

---

## 12. 后续优化

### 12.1 模型路由

```python
# 简单题目用低成本模型
if is_simple_question(text):
    provider = DoubaoProvider(...)
else:
    provider = OpenAIProvider(model="gpt-4o")
```

### 12.2 批量分析

```python
# 批量分析多个题目
questions = [...]
analyses = []

for q in questions:
    analysis = service.analyze_question(q.text, q.markdown)
    analyses.append(analysis)
```

---

## 13. 参考资料

- [豆包 API 文档](https://www.volcengine.com/docs/82379)
- [MiniMax API 文档](https://www.minimaxi.com/document)
- [OpenAI API 文档](https://platform.openai.com/docs)
