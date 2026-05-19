# Kiro 任务清单

## 🎯 总体目标

负责**后端核心业务逻辑**：异步任务流水线、OCR/AI 处理、知识点标准化、学生画像计算、复习计划生成算法。

---

## 📋 任务优先级

### P0 — 高优先级（核心链路打通）

#### 任务 1：Celery 异步任务队列

**新建文件：**
- `src/tasks/__init__.py`
- `src/tasks/celery_app.py` — Celery 应用实例
- `src/tasks/ocr_tasks.py` — OCR 异步任务
- `src/tasks/ai_tasks.py` — AI 分析异步任务

**实现内容：**

```python
# src/tasks/celery_app.py
from celery import Celery
import os

celery_app = Celery(
    "ai_review",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)
```

```python
# src/tasks/ocr_tasks.py
@celery_app.task(bind=True, max_retries=3)
def run_ocr_task(self, assignment_id: str) -> dict:
    """
    处理 OCR 任务
    1. 从 DB 读取 Assignment 记录
    2. 调用 PaddleOCRAdapter 处理图片
    3. 存储 OCRTask 结果
    4. 更新 Assignment.status → ocr_done
    5. 触发 AI 分析任务
    """
    pass

@celery_app.task(bind=True, max_retries=3)
def run_ai_analysis_task(self, ocr_task_id: str) -> dict:
    """
    处理 AI 分析任务
    1. 读取 OCRTask 结果
    2. 调用 AIAnalysisService 分析题目
    3. 保存 Question 记录
    4. 触发知识点归档任务
    5. 更新 Assignment.status → ai_done
    """
    pass
```

**状态流转：**
```
Assignment.status:
  uploaded → ocr_queued → ocr_running → ocr_done
                                       → ai_queued → ai_running → ai_done
  任意阶段 → failed（记录 error_message，支持重试）
```

**测试文件：** `tests/tasks/test_ocr_tasks.py`, `tests/tasks/test_ai_tasks.py`

---

#### 任务 2：题图多模态分析服务

**新建文件：** `src/services/image_semantic_service.py`

**实现内容：**
```python
@dataclass
class ImageSemanticResult:
    image_url: str
    description: str       # 图片内容语义描述
    math_elements: list    # 图中数学元素（坐标轴、函数图像、几何图形等）
    context_hint: str      # 对 AI 分析的辅助提示

class ImageSemanticService:
    """使用 DoubaoSeedProvider 分析 OCR 提取的图片块"""

    async def analyze_image(self, image_url: str) -> ImageSemanticResult:
        """分析单张图片的语义"""
        pass

    async def analyze_batch(self, image_urls: list[str]) -> list[ImageSemanticResult]:
        """批量分析（并发处理）"""
        pass
```

**测试文件：** `tests/services/test_image_semantic_service.py`

---

#### 任务 3：知识点归档服务

**新建文件：** `src/services/knowledge_archival_service.py`

**实现内容：**
```python
class KnowledgeArchivalService:
    """
    将 AI 分析输出的知识点标准化并写入 knowledge_points 表
    防止同一知识点被用多种名称存储（如"一次函数"vs"线性函数"）
    """

    async def standardize_and_archive(
        self,
        raw_knowledge_points: list[str],
        subject: str,
        grade: str | None,
    ) -> list[KnowledgePoint]:
        """
        1. 查找已有知识点（按名称精确匹配）
        2. 未找到则创建新记录
        3. 返回标准化后的知识点列表
        """
        pass

    async def link_question_to_knowledge_points(
        self,
        question_id: str,
        knowledge_points: list[KnowledgePoint],
    ) -> None:
        """将题目与知识点关联写入 Question.knowledge_points JSONB"""
        pass
```

**测试文件：** `tests/services/test_knowledge_archival_service.py`

---

### P1 — 中优先级（画像与计划）

#### 任务 4：学生画像服务

**新建文件：** `src/services/student_profile_service.py`

**实现内容：**
```python
@dataclass
class MasteryResult:
    knowledge_point_id: str
    knowledge_point_name: str
    mastery_score: float       # 0-1，越高越熟练
    appear_count: int
    error_count: int
    last_error_at: datetime | None
    review_priority: str       # high / medium / low

class StudentProfileService:
    """
    学生知识点掌握度计算和画像更新
    掌握度公式（第一版）：
      mastery = (1 - error_rate) * time_decay_factor
      time_decay_factor = exp(-k * days_since_last_error)
    """

    async def update_after_question(
        self,
        student_id: str,
        knowledge_point_ids: list[str],
        is_correct: bool,
    ) -> None:
        """题目分析完成后更新学生画像"""
        pass

    async def get_profile(
        self,
        student_id: str,
    ) -> list[MasteryResult]:
        """获取学生所有知识点的掌握度列表"""
        pass

    async def get_weak_points(
        self,
        student_id: str,
        limit: int = 10,
        mastery_threshold: float = 0.6,
    ) -> list[MasteryResult]:
        """获取薄弱知识点（掌握度低于阈值）"""
        pass
```

**接口约定（供 Claude Code 的 API 调用）：**
- `get_profile(student_id)` → `list[MasteryResult]`
- `get_weak_points(student_id, limit, threshold)` → `list[MasteryResult]`
- `update_after_question(student_id, kp_ids, is_correct)` → `None`

**测试文件：** `tests/services/test_student_profile_service.py`

---

#### 任务 5：复习计划生成服务

**新建文件：** `src/services/review_plan_service.py`

**实现内容：**
```python
@dataclass
class ReviewTask:
    knowledge_point_id: str
    knowledge_point_name: str
    priority: str              # high / medium / low
    reason: str                # 为什么要复习
    recommended_count: int     # 建议练习题目数
    estimated_minutes: int     # 预计用时

@dataclass
class DailyReviewPlan:
    student_id: str
    date: str                  # YYYY-MM-DD
    tasks: list[ReviewTask]
    total_minutes: int

class ReviewPlanService:
    """
    生成每日复习计划（规则引擎，第一版）
    规则：
    1. 取掌握度 < 0.6 的知识点
    2. 按掌握度升序排序（越低越先复习）
    3. 超过 7 天未练习的权重加成
    4. 每日限 3-5 个知识点
    """

    async def generate_today_plan(
        self,
        student_id: str,
        max_tasks: int = 5,
    ) -> DailyReviewPlan:
        """生成今日复习计划"""
        pass
```

**接口约定（供 Claude Code 的 API 调用）：**
- `generate_today_plan(student_id, max_tasks)` → `DailyReviewPlan`

**测试文件：** `tests/services/test_review_plan_service.py`

---

### P2 — 低优先级（优化）

#### 任务 6：AI 调用缓存层

**修改文件：** `src/services/ai_analysis_service.py`（追加缓存逻辑）

- 以题目内容 hash 为 key，Redis 缓存 AI 分析结果
- 相同题目内容不重复调用 AI
- 缓存 TTL：7 天

---

## 🛠️ 技术要求

### 启动命令

```bash
# 启动 Redis
docker run -d -p 6379:6379 redis:alpine

# 启动 Celery Worker
celery -A src.tasks.celery_app worker --loglevel=info

# 监控 Celery（可选）
celery -A src.tasks.celery_app flower
```

### 测试要求

- 单元测试覆盖率 ≥ 80%
- 纯函数算法每个至少 3 个测试用例（正常、边界、异常）
- Celery 任务测试使用 `task_always_eager=True` 同步执行
- 数据库测试使用 SQLite 内存库

---

## 📝 提交前自查

- [ ] 所有新文件都有对应测试
- [ ] `pytest --cov=src` 覆盖率 ≥ 80%
- [ ] 没有修改 Claude Code 负责的 `src/api/student.py`、`src/api/review.py`、`src/api/report.py`、`src/api/export.py`
- [ ] `student_profile_service.py` 公开接口签名与本文件任务 4 约定一致
- [ ] `review_plan_service.py` 公开接口签名与本文件任务 5 约定一致
- [ ] 新增环境变量已更新 `.env.example`
- [ ] PR 描述包含：改了什么 / 为什么改 / 怎么测试 / 剩余风险

---

## 🤝 交接给 Claude Code 的接口

完成后通知用户，Claude Code 的 API 层即可接通真实数据：

| 服务 | 方法 | 状态 |
|------|------|------|
| `StudentProfileService` | `get_profile(student_id)` | ⏳ 待完成 |
| `StudentProfileService` | `get_weak_points(student_id, limit)` | ⏳ 待完成 |
| `ReviewPlanService` | `generate_today_plan(student_id)` | ⏳ 待完成 |

在这些接口完成前，Claude Code 的 API 层可先用 mock 数据开发，接口签名保持一致。
