# AI 复习导航系统

> 这不是一个 OCR 工具或搜题工具，而是一个 **AI 复习导航系统**。

## 核心目标

告诉学生"今天该复习哪里"。

## 核心链路

```
拍作业/错题 → OCR识别 → AI题目分析 → 知识点归档 → 学生画像更新 → 生成复习任务 → 课后/考前复习 → 家长/老师报告
```

## 项目结构

```
ai_review_system/
├── src/
│   ├── adapters/          # 第三方服务适配器
│   │   └── ocr/          # OCR 适配器
│   ├── services/         # 业务服务
│   ├── models/           # 数据模型
│   ├── api/              # API 路由
│   └── utils/            # 工具函数
├── tests/                # 测试
├── docs/                 # 文档
└── config/               # 配置
```

## 技术栈

- Python 3.10+
- FastAPI
- PostgreSQL
- Redis
- PaddleOCR-VL-1.5

## 开发原则

1. **测试驱动开发（TDD）** - 先写测试，再写代码
2. **安全第一** - 面向未成年人产品，安全和隐私前置
3. **成本控制** - OCR 和 AI 调用成本跟踪和优化
4. **异步优先** - 上传立即返回，OCR 和 AI 异步处理
5. **服务边界清晰** - 即使 MVP 是单体应用，也保持清晰的服务边界

## 快速开始

### Docker Compose（推荐）

```bash
# 1. 配置环境变量（至少填写 POSTGRES_PASSWORD 和 AI API Key）
cp .env.example .env

# 2. 构建并启动所有服务（postgres / redis / migrate / api / worker）
docker compose up -d --build

# 3. 验证服务正常
curl http://localhost:8000/health
curl http://localhost:8000/health/ready
```

详细说明见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

### 本地开发（裸机）

```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
python -m pytest tests/api tests/integration/test_report_flow.py -q

# 启动开发服务器
uvicorn src.main:app --reload
```
