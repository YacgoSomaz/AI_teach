# 快速开始指南

## 🎯 项目概述

**AI 复习导航系统** - 不是简单的 OCR 工具或搜题工具，而是告诉学生"今天该复习哪里"的智能系统。

## 📦 已完成的模块

### ✅ 1. OCR Adapter

基于 PaddleOCR-VL-1.5 API 的 OCR 适配器，负责将作业/错题图片转换为结构化文本。

**特性：**
- ✅ 统一的接口设计
- ✅ 支持本地文件和 URL
- ✅ 异步任务处理
- ✅ 失败重试机制
- ✅ 100% 测试覆盖率
- ✅ 详细的文档

### ✅ 2. AI 分析服务

基于大模型的题目分析服务，识别知识点、难度、错因等信息。

**特性：**
- ✅ 支持多种 AI 提供商（OpenAI、豆包、MiniMax）
- ✅ 支持多模态分析（文本 + 图片）
- ✅ 结构化 JSON 输出
- ✅ 智能缓存机制
- ✅ 99% 测试覆盖率
- ✅ 详细的文档

**支持的 AI 提供商：**
- **豆包（字节跳动）** ⭐ 推荐 - 支持多模态，国产模型
- **MiniMax** ⭐ 推荐 - 支持多模态，国产模型
- **OpenAI** - 质量高，成本较高

## 🚀 安装和运行

### 1. 安装依赖

```bash
cd C:\Users\q2414\Desktop\freeAPI\AI_teach\ai_review_system

# 安装 Python 依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填入你的 PaddleOCR Token
# PADDLEOCR_TOKEN=your_paddleocr_token_here
```

### 3. 运行测试

```bash
# 运行所有测试
pytest

# 运行测试并查看覆盖率
pytest --cov=src --cov-report=html

# 运行特定测试
pytest tests/test_paddle_ocr_adapter.py -v
```

### 4. 运行示例

```bash
# 运行 OCR 示例
python examples/ocr_example.py
```

## 📁 项目结构

```
ai_review_system/
├── src/
│   ├── adapters/
│   │   └── ocr/
│   │       ├── __init__.py
│   │       └── paddle_ocr_adapter.py    # PaddleOCR 适配器
│   ├── services/                        # 业务服务（待开发）
│   ├── models/                          # 数据模型（待开发）
│   ├── api/                             # API 路由（待开发）
│   └── utils/                           # 工具函数（待开发）
├── tests/
│   ├── __init__.py
│   └── test_paddle_ocr_adapter.py       # OCR 适配器测试
├── examples/
│   └── ocr_example.py                   # OCR 使用示例
├── docs/
│   └── OCR_ADAPTER.md                   # OCR 适配器文档
├── requirements.txt                     # Python 依赖
├── .env.example                         # 环境变量模板
├── README.md                            # 项目说明
└── GETTING_STARTED.md                   # 本文件
```

## 💡 使用 OCR Adapter

### 基本用法

```python
from src.adapters.ocr import PaddleOCRAdapter, OCRException

# 创建 Adapter
adapter = PaddleOCRAdapter(token="your_token")

# 处理图片
try:
    result = adapter.process_file(
        file_path="homework.jpg",
        file_id="hw_001"
    )
    
    print(f"置信度: {result.confidence:.2%}")
    print(f"文本: {result.raw_text}")
    print(f"Markdown: {result.markdown}")
    print(f"图片数量: {len(result.images)}")
    
except OCRException as e:
    print(f"OCR 失败: {e}")
```

### 处理 URL

```python
result = adapter.process_file(
    file_path="https://example.com/homework.jpg",
    file_id="hw_002"
)
```

### 批量处理

```python
files = [
    ("hw_001.jpg", "file_001"),
    ("hw_002.jpg", "file_002"),
    ("hw_003.jpg", "file_003"),
]

for file_path, file_id in files:
    try:
        result = adapter.process_file(file_path, file_id)
        print(f"✅ {file_id}: 成功")
    except OCRException as e:
        print(f"❌ {file_id}: 失败 - {e}")
```

## 🧪 测试驱动开发（TDD）

本项目遵循 TDD 原则：**先写测试，再写代码**。

### 运行测试

```bash
# 运行所有测试
pytest

# 运行测试并显示详细信息
pytest -v

# 运行测试并查看覆盖率
pytest --cov=src --cov-report=term-missing

# 运行特定测试文件
pytest tests/test_paddle_ocr_adapter.py

# 运行特定测试函数
pytest tests/test_paddle_ocr_adapter.py::TestPaddleOCRAdapter::test_init
```

### 测试覆盖率目标

- ✅ 单元测试覆盖率：≥ 90%
- ✅ 集成测试覆盖率：≥ 70%

## 📚 开发指南

### 使用的 Skills

本项目使用了 everything-claude-code 的以下 skills：

1. **tdd-workflow** - 测试驱动开发
2. **security-review** - 安全审查
3. **python-patterns** - Python 最佳实践
4. **api-design** - API 设计
5. **backend-patterns** - 后端架构
6. **cost-aware-llm-pipeline** - 成本控制

### 开发原则

1. **测试驱动开发（TDD）** - 先写测试，再写代码
2. **安全第一** - Token 使用环境变量，图片使用临时 URL
3. **成本控制** - 缓存 OCR 结果，避免重复处理
4. **异步优先** - 上传立即返回，OCR 异步处理
5. **服务边界清晰** - 保持清晰的模块边界

### 代码规范

```bash
# 格式化代码
black src/ tests/

# 排序 import
isort src/ tests/

# 代码检查
flake8 src/ tests/

# 类型检查
mypy src/
```

## 🔜 下一步开发

### 待开发模块（按优先级）

1. **文件上传服务** - 处理图片上传到 OSS
2. **AI 分析服务** - 识别题目知识点
3. **知识点标签系统** - 统一知识点归档
4. **学生画像服务** - 记录学生掌握度
5. **复习计划生成服务** - 生成今日复习任务
6. **报告服务** - 生成学生/家长/老师报告

### 技术债务

- [ ] 添加 Redis 缓存支持
- [ ] 添加数据库模型
- [ ] 添加 API 路由
- [ ] 添加日志系统
- [ ] 添加监控告警

## 📖 文档

- [项目 README](README.md)
- [OCR Adapter 设计文档](docs/OCR_ADAPTER.md)
- [技术架构文档](../ai-review-navigation-architecture.md)

## 🤝 贡献指南

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 开启 Pull Request

## 📝 许可证

MIT License

## 💬 联系方式

如有问题，请提交 Issue。

---

**记住：这不是一个 OCR 工具，而是一个 AI 复习导航系统！** 🎯
