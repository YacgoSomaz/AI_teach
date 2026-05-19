# CLAUDE.md — Claude Code 专属约束

> 本文件仅约束 **Claude Code**。  
> 请先阅读 `AGENTS.md`（共同约束），再阅读本文件（Claude 专属细节）。

---

## 一、我负责的模块

详见 `AGENTS.md` 第二节"Claude Code 负责"部分。

简述：我负责 **API 层 + 报告层**，即调用 Kiro 服务后对外暴露接口：

```
（调用 Kiro 的服务） → API 查询接口 → 报告生成 → 数据导出
```

对应文件：
- `src/api/student.py` — 学生画像查询 API
- `src/api/review.py` — 复习任务查询 API
- `src/services/report_service.py` — 报告生成服务
- `src/api/report.py` — 报告 API
- `src/api/export.py` — 数据导出 API（JSON/CSV/Excel）
- `src/api/visualization.py` — 可视化数据 API（P2，可选）
- 对应测试文件

---

## 二、我不动的文件

以下文件由 Kiro 负责，我**不做任何修改**（包括格式、注释、变量名）：

```
src/adapters/
src/services/ai_analysis_service.py
src/services/file_service.py
src/services/image_semantic_service.py
src/services/knowledge_archival_service.py
src/services/student_profile_service.py
src/services/review_plan_service.py
src/models/
src/db/
src/api/upload.py
src/tasks/
alembic/
```

唯一例外：`src/main.py` 和 `requirements.txt` 是共享文件，我可以**追加**内容（注册路由、添加依赖），但不修改 Kiro 已写的行。

如果我的任务需要 Kiro 的文件做出改动，我会在回复中明确说明，等待用户确认后由 Kiro 处理。

---

## 三、我的服务层设计原则

### 只读模型，不改模型

我的服务层直接使用 Kiro 定义的 SQLAlchemy 模型（`StudentKnowledgeProfile`、`KnowledgePoint`、`Question`）。  
如果我的业务逻辑需要新字段，我会提出需求，由 Kiro 在模型文件和迁移文件里处理，不自行修改。

### 纯函数优先

掌握度计算、复习优先级排序、时间衰减公式等核心算法，写成纯函数（无副作用，无数据库依赖），方便单元测试。

### 异步数据库操作

所有数据库查询使用 `async/await` + `AsyncSession`（与 Kiro 的 `get_db` 依赖一致），不引入同步 DB 调用。

### 服务层不直接返回 ORM 对象

服务层返回 `dataclass` 或 Pydantic 模型，不把 SQLAlchemy ORM 对象传到 API 层。

---

## 四、我的 API 设计原则

### 每个端点必须有 response_model

```python
@router.get("/review-plans/today", response_model=TodayReviewPlanResponse)
async def get_today_review_plan(...):
    ...
```

### 错误响应格式统一

```python
raise HTTPException(
    status_code=404,
    detail="未找到该学生的复习计划",
)
```

### 学生身份来自依赖，不来自请求参数

```python
# 正确：student_id 从鉴权依赖提取
async def get_today_plan(
    student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
):
```

MVP 阶段如果鉴权尚未实现，使用 stub 依赖并在代码里加 `# TODO: 接入真实 JWT 鉴权`，不直接接受用户传入的 student_id。

---

## 五、我的测试要求

### TDD 流程

每个服务必须先写测试（RED），再写实现（GREEN），再优化（IMPROVE）。

### 测试结构

```python
class TestReviewPlanService:
    def test_<具体场景>(self):
        # Arrange
        ...
        # Act
        ...
        # Assert
        ...
```

### 核心算法单元测试

掌握度计算、时间衰减、优先级排序等纯函数，每个至少 3 个测试用例：正常路径、边界值、异常输入。

### 数据库操作使用 SQLite 内存库

集成测试使用 SQLite 内存数据库，不依赖外部 PostgreSQL：

```python
@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        yield session
```

### AI 输出测试

涉及 AI 分析结果的功能，必须 mock AI 服务并提供至少 3 个固定测试用例说明预期行为。

---

## 六、我如何通知 Kiro 接口有变化

如果我的实现需要 Kiro 提供新字段、新方法、或对已有接口有依赖，我会：

1. 在回复中明确列出：**"需要 Kiro 提供的接口"**
2. 写出期望的函数签名或数据结构
3. 等待用户确认后再继续

---

## 七、提交前自查清单

- [ ] 所有新文件都有对应测试
- [ ] `pytest --cov=src` 覆盖率 ≥ 80%
- [ ] 没有修改 Kiro 负责的任何文件
- [ ] 新增的 API 端点都有 `response_model`
- [ ] 没有硬编码 `student_id`，使用依赖注入
- [ ] `src/main.py` 里新路由的注册不与 Kiro 的代码冲突
- [ ] 新增环境变量已更新 `.env.example`
- [ ] PR 描述包含：改了什么 / 为什么改 / 怎么测试 / 剩余风险
