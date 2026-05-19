# AI 复习导航系统 - 任务分配方案

## 📊 项目完成度总览

### ✅ 已完成模块（70%）

1. **OCR 适配器** - 100% ✅
   - PaddleOCR-VL-1.5 集成
   - 异步任务处理
   - 测试覆盖率 100%

2. **AI 分析服务** - 100% ✅
   - 豆包 Seed1.8 多模态模型接入
   - DoubaoSeedProvider 实现
   - 支持图文混合分析

3. **文件上传服务** - 100% ✅
   - 文件校验（类型、大小、扩展名）
   - SHA-256 hash 去重
   - 本地存储实现
   - 测试覆盖率 100%

4. **数据库模型** - 100% ✅
   - Assignment（作业记录）
   - OCRTask（OCR 任务）
   - Question（题目）
   - KnowledgePoint（知识点）
   - StudentKnowledgeProfile（学生画像）

5. **API 路由** - 50% ✅
   - POST /api/upload - 文件上传 ✅
   - GET /api/assignments/{id} - 查询状态 ✅

---

## 🔄 待完成模块（30%）

### 核心链路缺失部分

```
✅ 拍作业/错题 → ❌ OCR识别 → ❌ AI题目分析 → ❌ 知识点归档 → ❌ 学生画像更新 → ❌ 生成复习任务 → ❌ 报告可视化
```

---

## 📋 任务分配方案

### 方案 A：按模块功能分配（推荐）

#### 🤖 Kiro 负责：后端核心业务逻辑

**任务组 1：异步任务队列（高优先级）**
- [ ] 配置 Celery + Redis
- [ ] 实现 OCR 异步任务
- [ ] 实现 AI 分析异步任务
- [ ] 任务状态更新机制
- [ ] 任务失败重试逻辑

**任务组 2：题图多模态分析服务**
- [ ] 创建 `src/services/image_semantic_service.py`
- [ ] 使用 DoubaoSeedProvider 分析 OCR 提取的图片块
- [ ] 输出结构化的图片语义描述
- [ ] 集成到 AI 分析流程

**任务组 3：知识点标签系统**
- [ ] 知识点标准化服务
- [ ] 知识点映射和归档
- [ ] 知识点层级关系管理

**任务组 4：学生画像服务**
- [ ] 学生知识点掌握度计算
- [ ] 画像更新逻辑
- [ ] 薄弱知识点识别

---

#### 👨‍💻 Claude Code 负责：前端可视化 + 报告系统

**任务组 1：数据可视化 API（高优先级）**
- [ ] GET /api/students/{id}/profile - 学生画像查询
- [ ] GET /api/students/{id}/weak-points - 薄弱知识点
- [ ] GET /api/students/{id}/progress - 学习进度
- [ ] GET /api/students/{id}/review-tasks - 复习任务列表

**任务组 2：报告生成服务**
- [ ] 学生报告生成（JSON/PDF）
- [ ] 家长报告生成（周报/月报）
- [ ] 教师报告生成（班级分析）
- [ ] 报告模板设计

**任务组 3：前端可视化页面（可选）**
- [ ] 学生画像可视化（雷达图、进度条）
- [ ] 知识点掌握度热力图
- [ ] 复习任务日历视图
- [ ] 错题本展示

**任务组 4：数据导出功能**
- [ ] 导出学生报告（PDF/Excel）
- [ ] 导出错题集
- [ ] 导出知识点分析

---

### 方案 B：按技术栈分配

#### 🤖 Kiro 负责：Python 后端

- [ ] Celery 任务队列
- [ ] 异步 OCR 处理
- [ ] 异步 AI 分析
- [ ] 知识点标签系统
- [ ] 学生画像计算
- [ ] 复习计划生成算法

#### 👨‍💻 Claude Code 负责：API + 可视化

- [ ] RESTful API 设计和实现
- [ ] 数据查询接口
- [ ] 报告生成接口
- [ ] 前端可视化（可选）
- [ ] 数据导出功能

---

## 🎯 推荐分配：方案 A（按模块功能）

### 理由：
1. **职责清晰**：Kiro 专注核心业务逻辑，Claude Code 专注用户界面
2. **并行开发**：两个模块依赖少，可以同时开发
3. **技能匹配**：Kiro 擅长异步任务和算法，Claude Code 擅长 API 和可视化
4. **易于合并**：接口约定清晰，PR 合并简单

---

## 📝 接口约定（Contract）

### Kiro 提供的服务接口

```python
# src/services/ocr_service.py
class OCRService:
    async def process_assignment(self, assignment_id: str) -> OCRResult:
        """处理作业 OCR"""
        pass

# src/services/ai_analysis_service.py
class AIAnalysisService:
    async def analyze_question(self, question_text: str, images: list) -> AnalysisResult:
        """分析题目"""
        pass

# src/services/knowledge_service.py
class KnowledgeService:
    async def standardize_knowledge_points(self, raw_points: list) -> list[KnowledgePoint]:
        """标准化知识点"""
        pass

# src/services/student_profile_service.py
class StudentProfileService:
    async def update_profile(self, student_id: str, question_id: str) -> None:
        """更新学生画像"""
        pass
    
    async def get_weak_points(self, student_id: str) -> list[KnowledgePoint]:
        """获取薄弱知识点"""
        pass
```

### Claude Code 需要实现的 API

```python
# src/api/student.py
@router.get("/api/students/{student_id}/profile")
async def get_student_profile(student_id: str):
    """获取学生画像"""
    pass

@router.get("/api/students/{student_id}/weak-points")
async def get_weak_points(student_id: str):
    """获取薄弱知识点"""
    pass

@router.get("/api/students/{student_id}/review-tasks")
async def get_review_tasks(student_id: str):
    """获取复习任务"""
    pass

# src/api/report.py
@router.get("/api/reports/student/{student_id}")
async def generate_student_report(student_id: str, format: str = "json"):
    """生成学生报告"""
    pass

@router.get("/api/reports/parent/{student_id}")
async def generate_parent_report(student_id: str, period: str = "week"):
    """生成家长报告"""
    pass
```

---

## 🚀 开发流程

### 第一阶段：核心链路打通（本周）

**Kiro：**
1. 实现 Celery 任务队列
2. 实现 OCR 异步任务
3. 实现 AI 分析异步任务
4. 完成端到端测试

**Claude Code：**
1. 设计 API 接口规范
2. 实现学生画像查询 API
3. 实现薄弱知识点查询 API
4. 编写 API 文档

### 第二阶段：功能完善（下周）

**Kiro：**
1. 实现知识点标签系统
2. 实现学生画像服务
3. 实现复习计划生成

**Claude Code：**
1. 实现报告生成服务
2. 实现数据可视化 API
3. 实现数据导出功能

### 第三阶段：优化和测试（第三周）

**共同：**
1. 集成测试
2. 性能优化
3. 文档完善
4. 部署准备

---

## 📦 PR 合并策略

### 分支策略

```
main (生产)
  ↑
develop (开发)
  ↑
  ├── feature/kiro-celery-tasks (Kiro)
  ├── feature/kiro-ai-analysis (Kiro)
  ├── feature/claude-api-design (Claude Code)
  └── feature/claude-reports (Claude Code)
```

### PR 规范

**Kiro 的 PR：**
- `feature/kiro-*` → `develop`
- 必须包含单元测试
- 必须通过 pytest
- 必须更新 CHANGELOG.md

**Claude Code 的 PR：**
- `feature/claude-*` → `develop`
- 必须包含 API 文档
- 必须通过集成测试
- 必须更新 API.md

---

## 🔧 开发环境配置

### Kiro 环境

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 Redis（Celery 需要）
docker run -d -p 6379:6379 redis:alpine

# 启动 Celery Worker
celery -A src.celery_app worker --loglevel=info

# 运行测试
pytest tests/ -v
```

### Claude Code 环境

```bash
# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
uvicorn src.main:app --reload --port 8000

# 运行 API 测试
pytest tests/api/ -v

# 生成 API 文档
python scripts/generate_api_docs.py
```

---

## 📊 进度跟踪

### Kiro 任务清单

- [ ] Celery + Redis 配置
- [ ] OCR 异步任务实现
- [ ] AI 分析异步任务实现
- [ ] 题图多模态分析服务
- [ ] 知识点标签系统
- [ ] 学生画像服务
- [ ] 复习计划生成

### Claude Code 任务清单

- [ ] API 接口设计
- [ ] 学生画像查询 API
- [ ] 薄弱知识点查询 API
- [ ] 复习任务查询 API
- [ ] 学生报告生成
- [ ] 家长报告生成
- [ ] 数据可视化实现
- [ ] 数据导出功能

---

## 🤝 协作约定

### 沟通方式

1. **接口变更**：提前在 GitHub Issue 讨论
2. **依赖更新**：在 PR 中说明
3. **数据库变更**：需要双方确认
4. **API 变更**：需要更新 API.md

### Code Review

1. **Kiro Review Claude Code 的 PR**：检查 API 设计和数据库查询
2. **Claude Code Review Kiro 的 PR**：检查接口兼容性和文档

### 测试策略

1. **单元测试**：各自负责自己模块
2. **集成测试**：共同编写端到端测试
3. **性能测试**：Kiro 负责后端性能，Claude Code 负责 API 性能

---

## 📚 参考文档

- [项目 README](README.md)
- [技术架构文档](../ai-review-navigation-architecture.md)
- [OCR Adapter 文档](docs/OCR_ADAPTER.md)
- [AI Analysis Service 文档](docs/AI_ANALYSIS_SERVICE.md)

---

## 🎉 预期成果

### 第一阶段完成后

- ✅ 用户可以上传作业图片
- ✅ 系统自动 OCR 识别
- ✅ 系统自动 AI 分析题目
- ✅ 系统记录知识点
- ✅ 用户可以查询学生画像

### 第二阶段完成后

- ✅ 系统生成复习任务
- ✅ 系统生成学生报告
- ✅ 系统生成家长报告
- ✅ 数据可视化展示

### 最终目标

**告诉学生"今天该复习哪里"！** 🎯

---

**让我们开始协作吧！** 🚀
