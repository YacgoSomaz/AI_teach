# 架构深度 Review：模块化与解耦分析

## 执行摘要

**当前状态**：系统存在多处紧耦合问题，"坏一个地方就坏一大片"的风险较高。

**主要问题**：
1. ❌ **任务链强耦合**：OCR → AI → 学生画像形成硬编码调用链
2. ❌ **数据库连接重复创建**：每个任务模块独立创建引擎，资源浪费
3. ❌ **错误传播无隔离**：一个环节失败导致整个链路中断
4. ❌ **服务层缺少接口抽象**：直接依赖具体实现，难以替换和测试
5. ❌ **配置硬编码**：环境变量散落各处，缺少统一管理

**风险等级**：🔴 **高风险** - 需要立即重构

---

## 详细问题分析

### 1. 任务链强耦合（Critical）

**问题代码**：`src/tasks/ocr_tasks.py:95-96`

```python
# 7. 触发 AI 分析任务
from src.tasks.ai_tasks import process_ai_analysis
process_ai_analysis.delay(assignment_id)
```

**问题代码**：`src/tasks/ai_tasks.py:145-150`

```python
# 8. 触发学生画像更新
for question in created_questions:
    await db.refresh(question)
    update_student_profile.delay(
        student_id=assignment.student_id,
        question_id=str(question.id),
    )
```

**问题**：
- OCR 任务直接导入并调用 AI 任务
- AI 任务直接导入并调用学生画像任务
- 形成 `OCR → AI → Profile` 硬编码调用链
- 任何一个环节失败，整个链路中断
- 无法独立测试、无法灵活编排

**影响**：
- 🔴 **单点故障**：AI 服务挂了，OCR 结果无法保存
- 🔴 **无法回滚**：中间环节失败，前面的工作白做
- 🔴 **难以扩展**：新增环节需要修改多处代码

---

### 2. 数据库连接重复创建（High）

**问题代码**：`src/tasks/ocr_tasks.py:28-31` 和 `src/tasks/ai_tasks.py:28-31`

```python
# OCR 任务模块
DATABASE_URL = os.getenv("DATABASE_URL", "...")
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# AI 任务模块（完全相同的代码）
DATABASE_URL = os.getenv("DATABASE_URL", "...")
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

**问题**：
- 每个任务模块独立创建数据库引擎
- 连接池重复创建，资源浪费
- 配置不一致风险（如果某个模块改了参数）

**影响**：
- 🟡 **资源浪费**：多个连接池占用内存
- 🟡 **维护困难**：修改配置需要改多处
- 🟡 **性能下降**：连接池未共享

---

### 3. 错误传播无隔离（Critical）

**问题代码**：`src/tasks/ocr_tasks.py:87-91`

```python
except OCRException as e:
    # OCR 失败
    ocr_task.status = OCRTaskStatus.FAILED
    assignment.status = AssignmentStatus.FAILED  # ❌ 直接标记整个作业失败
    assignment.error_message = f"OCR 失败: {e}"
```

**问题代码**：`src/tasks/ai_tasks.py:137-141`

```python
except Exception as e:
    # AI 分析失败
    assignment.status = AssignmentStatus.FAILED  # ❌ 直接标记整个作业失败
    assignment.error_message = f"AI 分析失败: {e}"
```

**问题**：
- 任何环节失败，直接标记整个 Assignment 为 FAILED
- 没有部分成功的概念
- 无法重试单个环节
- 用户看不到已完成的部分（如 OCR 成功但 AI 失败）

**影响**：
- 🔴 **用户体验差**：OCR 成功了，但因为 AI 失败，用户看不到 OCR 结果
- 🔴 **重试成本高**：重试需要重新 OCR（浪费时间和钱）
- 🔴 **数据丢失**：中间结果可能丢失

---

### 4. 服务层缺少接口抽象（Medium）

**问题代码**：`src/tasks/ocr_tasks.py:62-63`

```python
adapter = PaddleOCRAdapter(token=paddleocr_token)
ocr_result = adapter.process_file(...)
```

**问题代码**：`src/tasks/ai_tasks.py:78-82`

```python
provider = DoubaoSeedProvider(
    api_key=api_key,
    model=model,
    base_url=base_url,
)
```

**问题**：
- 任务直接依赖具体实现（`PaddleOCRAdapter`, `DoubaoSeedProvider`）
- 没有接口抽象（如 `OCRProvider`, `AIProvider`）
- 切换供应商需要修改任务代码
- 难以 mock 测试

**影响**：
- 🟡 **难以测试**：无法 mock OCR/AI 服务
- 🟡 **难以切换**：换供应商需要改任务代码
- 🟡 **违反依赖倒置**：高层模块依赖低层模块

---

### 5. 配置硬编码（Medium）

**问题代码**：散落在多个文件

```python
# src/tasks/ocr_tasks.py:59
paddleocr_token = os.getenv("PADDLEOCR_TOKEN")

# src/tasks/ai_tasks.py:75-77
api_key = os.getenv("DOUBAO_SEED_API_KEY")
model = os.getenv("DOUBAO_SEED_MODEL")
base_url = os.getenv("DOUBAO_SEED_BASE_URL")

# src/celery_app.py:11
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
```

**问题**：
- 环境变量读取散落各处
- 缺少统一配置管理
- 没有配置校验
- 默认值不一致

**影响**：
- 🟡 **维护困难**：配置分散，难以管理
- 🟡 **容易出错**：忘记配置某个变量
- 🟡 **难以测试**：无法统一 mock 配置

---

## 重构方案

### 方案 1：事件驱动架构（推荐）

**核心思想**：解耦任务链，使用事件总线

```
OCR 完成 → 发布 "OCR_COMPLETED" 事件
AI 任务监听 "OCR_COMPLETED" 事件 → 执行分析 → 发布 "AI_COMPLETED" 事件
Profile 任务监听 "AI_COMPLETED" 事件 → 更新画像
```

**优点**：
- ✅ 完全解耦：任务之间不知道彼此存在
- ✅ 容错性强：某个环节失败不影响其他环节
- ✅ 易于扩展：新增环节只需监听事件
- ✅ 可重试：每个环节独立重试

**实现**：
1. 创建事件总线（使用 Celery 的 `send_task` 或 Redis Pub/Sub）
2. 每个任务完成后发布事件
3. 其他任务监听事件并执行

---

### 方案 2：工作流编排（Celery Chain/Chord）

**核心思想**：使用 Celery 的工作流原语

```python
from celery import chain

# 定义工作流
workflow = chain(
    process_ocr.s(assignment_id),
    process_ai_analysis.s(),
    update_student_profile.s(),
)
workflow.apply_async()
```

**优点**：
- ✅ Celery 原生支持
- ✅ 自动错误处理和重试
- ✅ 可视化监控（Flower）

**缺点**：
- ⚠️ 仍然是线性链路，灵活性不如事件驱动
- ⚠️ 需要修改任务签名（使用 `.s()` 传递参数）

---

### 方案 3：Saga 模式（补偿事务）

**核心思想**：每个步骤有对应的补偿操作

```
OCR 成功 → AI 失败 → 回滚 OCR（标记为待重试）
```

**优点**：
- ✅ 支持部分成功
- ✅ 可回滚
- ✅ 数据一致性强

**缺点**：
- ⚠️ 实现复杂
- ⚠️ 需要设计补偿逻辑

---

## 推荐重构计划

### Phase 1：紧急修复（1-2 天）

1. **统一数据库连接**
   - 创建 `src/db/celery_session.py`
   - 所有任务共享同一个引擎

2. **错误隔离**
   - 引入 `processing_status` 字段（JSON）
   - 记录每个环节的状态：`{"ocr": "done", "ai": "failed"}`
   - 允许部分成功

3. **配置统一管理**
   - 创建 `src/config.py`
   - 统一读取和校验环境变量

### Phase 2：架构重构（3-5 天）

4. **事件驱动改造**
   - 创建事件总线 `src/events/bus.py`
   - 改造任务为事件监听器
   - 解耦任务链

5. **接口抽象**
   - 定义 `OCRProvider` 接口
   - 定义 `AIProvider` 接口
   - 依赖注入

### Phase 3：增强（可选）

6. **重试策略优化**
   - 指数退避
   - 死信队列

7. **监控和告警**
   - 任务失败告警
   - 性能监控

---

## 立即行动项

### 🔴 Critical（必须立即修复）

1. **解耦任务链**：使用事件驱动或 Celery Chain
2. **错误隔离**：允许部分成功，记录每个环节状态

### 🟡 High（本周内修复）

3. **统一数据库连接**：共享引擎和连接池
4. **配置统一管理**：创建 `config.py`

### 🟢 Medium（下周修复）

5. **接口抽象**：定义 Provider 接口
6. **单元测试**：为每个模块添加测试

---

## 测试策略

### 当前问题
- ❌ 任务紧耦合，无法独立测试
- ❌ 依赖外部服务（OCR/AI），测试困难
- ❌ 数据库操作难以 mock

### 改进方案
1. **依赖注入**：通过参数传递依赖，而非硬编码
2. **接口抽象**：使用 mock 实现替换真实服务
3. **集成测试**：使用 pytest-asyncio + 测试数据库

---

## 总结

**当前架构评分**：⭐⭐ (2/5)

**主要风险**：
- 🔴 任务链强耦合，单点故障风险高
- 🔴 错误传播无隔离，用户体验差
- 🟡 资源管理混乱，性能和维护性差

**重构后预期**：⭐⭐⭐⭐ (4/5)
- ✅ 任务解耦，容错性强
- ✅ 错误隔离，部分成功可见
- ✅ 资源共享，性能提升
- ✅ 易于测试和扩展

**建议**：立即启动 Phase 1 紧急修复，然后逐步推进 Phase 2 架构重构。
