# Kiro 实现文档

## ✅ 已完成任务

### 1. Celery + Redis 异步任务队列 ✅

**文件：**
- `src/celery_app.py` - Celery 应用配置
- `src/tasks/__init__.py` - 任务模块初始化
- `src/tasks/ocr_tasks.py` - OCR 异步任务
- `src/tasks/ai_tasks.py` - AI 分析异步任务

**功能：**
- ✅ Celery 应用配置（Redis 作为 broker 和 backend）
- ✅ 任务序列化配置（JSON）
- ✅ 任务超时和重试配置
- ✅ 任务路由（OCR 队列和 AI 队列）

**启动方式：**
```bash
# 启动 Redis
docker run -d -p 6379:6379 redis:alpine

# 启动 Celery Worker
celery -A src.celery_app worker --loglevel=info --pool=solo

# 或使用批处理脚本
start_celery.bat
```

---

### 2. OCR 异步任务 ✅

**文件：** `src/tasks/ocr_tasks.py`

**功能：**
- ✅ `process_ocr(assignment_id)` - 处理 OCR 任务
  - 更新 Assignment 状态为 `ocr_running`
  - 创建 OCRTask 记录
  - 调用 PaddleOCR API
  - 保存 OCR 结果（raw_text, markdown, images）
  - 更新状态为 `ocr_done`
  - 自动触发 AI 分析任务

- ✅ `check_ocr_status(assignment_id)` - 检查 OCR 状态

**错误处理：**
- ✅ OCR 失败自动重试（最多 3 次）
- ✅ 重试间隔 60 秒
- ✅ 失败后更新 Assignment 状态为 `failed`

**集成：**
- ✅ 在 `src/api/upload.py` 中，文件上传成功后自动触发 OCR 任务

---

### 3. AI 分析异步任务 ✅

**文件：** `src/tasks/ai_tasks.py`

**功能：**
- ✅ `process_ai_analysis(assignment_id)` - 处理 AI 分析任务
  - 更新 Assignment 状态为 `ai_running`
  - 获取 OCR 结果
  - 调用豆包 Seed1.8 分析题目
  - 解析 AI 返回的 JSON 结果
  - 创建 Question 记录
  - 更新状态为 `ai_done`
  - 触发学生画像更新

- ✅ `update_student_profile(student_id, question_id)` - 更新学生画像
  - 获取题目的知识点
  - 更新学生知识点掌握度
  - 计算掌握度（correct_count / total_count）

**AI 分析提示词：**
```
请分析以下作业内容，识别其中的题目和知识点。

作业内容（Markdown 格式）：
{ocr_markdown}

请以 JSON 格式返回分析结果，格式如下：
{
    "questions": [
        {
            "question_text": "题目内容",
            "question_type": "选择题/填空题/解答题/判断题",
            "difficulty": "easy/medium/hard",
            "knowledge_points": ["知识点1", "知识点2"],
            "solution": "解题思路",
            "answer": "参考答案"
        }
    ]
}
```

**错误处理：**
- ✅ AI 分析失败自动重试（最多 3 次）
- ✅ 重试间隔 120 秒
- ✅ JSON 解析失败时尝试提取 JSON 部分

---

### 4. 知识点标签系统 ✅

**文件：** `src/services/knowledge_service.py`

**功能：**
- ✅ `standardize_knowledge_point(raw_point)` - 标准化单个知识点
- ✅ `standardize_knowledge_points(raw_points)` - 批量标准化知识点
- ✅ `get_or_create_knowledge_point(name, category, parent_id)` - 获取或创建知识点
- ✅ `get_parent_knowledge_point(name)` - 获取父知识点
- ✅ `get_children_knowledge_points(name)` - 获取子知识点
- ✅ `search_knowledge_points(keyword, limit)` - 搜索知识点

**知识点映射表：**
```python
KNOWLEDGE_POINT_MAPPING = {
    "一元二次方程": "二次方程",
    "二次方程求解": "二次方程",
    "解二次方程": "二次方程",
    # ... 更多映射
}
```

**知识点层级：**
```python
KNOWLEDGE_HIERARCHY = {
    "代数": ["二次方程", "一次函数", "二次函数", "反比例函数"],
    "几何": ["三角形", "圆", "立体几何"],
    "三角函数": ["正弦函数", "余弦函数", "正切函数"],
    "概率统计": ["概率", "统计", "排列组合"],
}
```

---

### 5. 学生画像服务 ✅

**文件：** `src/services/student_profile_service.py`

**功能：**
- ✅ `get_profile(student_id)` - 获取学生完整画像
  - 返回所有知识点掌握情况
  - 计算总体正确率
  - 识别薄弱知识点

- ✅ `get_weak_points(student_id, limit, threshold)` - 获取薄弱知识点
  - 默认阈值 0.6（掌握度低于 60% 认为薄弱）
  - 按掌握度升序排序

- ✅ `get_progress(student_id, days)` - 获取学习进度
  - 统计最近 N 天的题目数量
  - 计算每日正确率
  - 返回每日统计数据

- ✅ `update_profile(student_id, question_id, is_correct)` - 更新画像
  - 使用指数移动平均计算掌握度
  - 给最近的表现更高权重（alpha = 0.3）

- ✅ `get_review_suggestions(student_id, max_tasks)` - 生成复习建议
  - 基于薄弱知识点生成复习任务
  - 计算优先级（high/medium/low）
  - 推荐题目数量（掌握度越低推荐越多）
  - 估算复习时间

**掌握度计算公式：**
```python
# 指数移动平均（EMA）
new_mastery = alpha * new_score + (1 - alpha) * old_mastery

# alpha = 0.3：给最近表现 30% 权重，历史表现 70% 权重
```

---

## 🔄 完整流程

### 用户上传作业 → AI 分析 → 学生画像更新

```
1. 用户上传图片
   ↓
2. POST /api/upload
   - 文件校验
   - 计算 hash
   - 存储文件
   - 创建 Assignment 记录
   - 触发 OCR 任务 ✅
   ↓
3. Celery: process_ocr(assignment_id)
   - 调用 PaddleOCR API
   - 保存 OCR 结果
   - 触发 AI 分析任务 ✅
   ↓
4. Celery: process_ai_analysis(assignment_id)
   - 调用豆包 Seed1.8
   - 解析题目和知识点
   - 创建 Question 记录
   - 触发学生画像更新 ✅
   ↓
5. Celery: update_student_profile(student_id, question_id)
   - 更新知识点掌握度
   - 计算掌握度（EMA）
   ↓
6. 用户查询学生画像
   GET /api/students/{id}/profile (Claude Code 实现)
   - 返回知识点掌握情况
   - 返回薄弱知识点
   - 返回复习建议
```

---

## 🧪 测试

### 单元测试

**文件：** `tests/test_celery_tasks.py`

```bash
# 运行测试
pytest tests/test_celery_tasks.py -v
```

### 集成测试

**手动测试流程：**

1. 启动 Redis
```bash
docker run -d -p 6379:6379 redis:alpine
```

2. 启动 Celery Worker
```bash
celery -A src.celery_app worker --loglevel=info --pool=solo
```

3. 启动 FastAPI 服务
```bash
uvicorn src.main:app --reload
```

4. 上传测试图片
```bash
curl -X POST http://localhost:8000/api/upload \
  -F "file=@test_homework.jpg"
```

5. 查询任务状态
```bash
curl http://localhost:8000/api/assignments/{assignment_id}
```

---

## 📊 数据库迁移

### 生成迁移文件

```bash
alembic revision --autogenerate -m "add celery tasks support"
```

### 运行迁移

```bash
alembic upgrade head
```

---

## 🔧 配置

### 环境变量

**.env 文件：**
```env
# Redis
REDIS_URL=redis://localhost:6379/0

# PaddleOCR
PADDLEOCR_TOKEN=your_token_here

# 豆包 Seed1.8
DOUBAO_SEED_API_KEY=your_api_key_here
DOUBAO_SEED_MODEL=ep-20260518173637-nhzdp
DOUBAO_SEED_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/ai_review_system
```

---

## 🚀 部署

### 生产环境配置

**Celery Worker 配置：**
```bash
# 启动多个 worker（根据 CPU 核心数）
celery -A src.celery_app worker \
  --loglevel=info \
  --concurrency=4 \
  --max-tasks-per-child=1000

# 启动 Flower 监控（可选）
celery -A src.celery_app flower --port=5555
```

**Supervisor 配置：**
```ini
[program:celery_worker]
command=celery -A src.celery_app worker --loglevel=info --concurrency=4
directory=/path/to/ai_review_system
user=www-data
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/celery/worker.log
```

---

## 📝 待优化

### 性能优化

- [ ] 添加 Redis 缓存（OCR 结果缓存）
- [ ] 批量处理题目（减少数据库查询）
- [ ] 异步数据库连接池优化

### 功能增强

- [ ] 题图多模态分析服务（使用豆包 Seed1.8 分析图片块）
- [ ] 复习计划生成算法优化（艾宾浩斯遗忘曲线）
- [ ] 知识点关联推荐（相似知识点推荐）

### 监控和告警

- [ ] Celery 任务监控（Flower）
- [ ] 任务失败告警（邮件/钉钉）
- [ ] 性能指标监控（Prometheus + Grafana）

---

## 🤝 与 Claude Code 的协作接口

### Kiro 提供的服务（Claude Code 可以调用）

```python
# 学生画像服务
from src.services.student_profile_service import StudentProfileService

service = StudentProfileService(db)

# 获取学生画像
profile = await service.get_profile(student_id)

# 获取薄弱知识点
weak_points = await service.get_weak_points(student_id, limit=5)

# 获取学习进度
progress = await service.get_progress(student_id, days=30)

# 获取复习建议
suggestions = await service.get_review_suggestions(student_id, max_tasks=5)
```

### Claude Code 需要实现的 API

- `GET /api/students/{student_id}/profile` - 调用 `get_profile()`
- `GET /api/students/{student_id}/weak-points` - 调用 `get_weak_points()`
- `GET /api/students/{student_id}/progress` - 调用 `get_progress()`
- `GET /api/students/{student_id}/review-tasks` - 调用 `get_review_suggestions()`

---

## 📚 参考文档

- [Celery 官方文档](https://docs.celeryproject.org/)
- [Redis 官方文档](https://redis.io/documentation)
- [SQLAlchemy 异步文档](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)

---

**实现完成！准备与 Claude Code 协作！** 🎉
