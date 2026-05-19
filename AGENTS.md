# AGENTS.md — 多 AI 协作约束文件

> 本文件同时约束 **Claude Code** 和 **Kiro**。  
> 任何 AI 在开始开发前必须阅读并遵守本文件。  
> 如本文件与临时指令冲突，**本文件优先**，冲突须告知用户后再行动。

---

## 一、项目目标（共识）

这是一个 **AI 复习导航系统**，不是 OCR 工具，不是搜题工具。

**核心价值主张**：告诉学生"今天该复习哪里"。

**完整链路**：
```
拍作业/错题
  → OCR 识别（PaddleOCR-VL-1.5）
  → AI 题目分析（知识点 / 难度 / 错因）
  → 知识点归档（写入 knowledge_points + questions 表）
  → 学生画像更新（student_knowledge_profiles 掌握度）
  → 生成复习任务（今日复习清单）
  → 课后/考前复习
  → 家长 / 老师报告
```

**目标用户**：中小学生及家长。产品涉及未成年人数据，**安全和隐私是强制约束，不是可选项**。

---

## 二、模块所有权

每个模块由且仅由一个 AI 主导。主导方负责该模块的实现、测试、文档。

### Kiro 负责（基础层 → 流水线层）

| 文件 / 目录 | 说明 |
|------------|------|
| `src/adapters/ocr/` | OCR 适配器（已完成） |
| `src/services/ai_analysis_service.py` | AI 分析服务（已完成） |
| `src/services/file_service.py` | 文件上传服务（已完成） |
| `src/models/` | 所有数据库模型（已完成） |
| `src/db/` | 数据库会话（已完成） |
| `src/api/upload.py` | 上传 API（已完成） |
| `src/tasks/` | Celery 异步任务队列（待做）：串联 OCR → AI → 归档 |
| `src/services/image_semantic_service.py` | 题图多模态分析服务（待做） |
| `src/services/knowledge_archival_service.py` | 知识点归档服务（待做） |
| `src/services/student_profile_service.py` | 学生画像服务：掌握度计算、画像更新（待做） |
| `src/services/review_plan_service.py` | 复习计划生成服务：规则算法（待做） |
| `alembic/` | 数据库迁移（Kiro 新增模型时维护） |

### Claude Code 负责（API 层 + 报告层）

| 文件 / 目录 | 说明 |
|------------|------|
| `src/api/student.py` | 学生画像查询 API（待做） |
| `src/api/review.py` | 复习任务查询 API（待做） |
| `src/services/report_service.py` | 报告服务：家长/学生/老师报告（待做） |
| `src/api/report.py` | 报告 API 路由（待做） |
| `src/api/export.py` | 数据导出 API（JSON/CSV/Excel）（待做） |
| `src/api/visualization.py` | 可视化数据 API（P2，可选）（待做） |
| `tests/api/test_student_api.py` | 对应测试 |
| `tests/api/test_review_api.py` | 对应测试 |
| `tests/services/test_report_service.py` | 对应测试 |
| `AGENTS.md` | 本文件（由 Claude Code 维护） |
| `CLAUDE.md` | Claude Code 专属约束（由 Claude Code 维护） |

### 共享文件（修改前必须协调）

| 文件 | 谁可以改 | 协调方式 |
|------|---------|---------|
| `src/main.py` | 两者均可（添加路由） | 改前在 PR 描述里注明，避免同行冲突 |
| `requirements.txt` | 两者均可（添加依赖） | 改前检查对方分支是否也在改，避免版本冲突 |
| `.env.example` | 两者均可 | 只追加，不删除已有条目 |
| `src/models/__init__.py` | Kiro 主导 | Claude 若需新模型，先提 Issue 让 Kiro 加 |
| `README.md` | 两者均可 | 修改对应自己负责的章节 |
| `GETTING_STARTED.md` | 两者均可 | 同上 |

---

## 三、分支命名规范

```
claude/<简短描述>    # Claude Code 的分支
kiro/<简短描述>      # Kiro 的分支
```

示例：
- `claude/student-profile-service`
- `claude/review-plan-api`
- `kiro/celery-task-pipeline`
- `kiro/knowledge-archival`

**禁止直接推送到 `main` 分支。** 所有变更通过 PR 合并。

---

## 四、PR 规范

### 每个 PR 只做一件事

一个 PR 对应一个模块或一个明确任务，不跨模块。

### PR 描述必须包含

```markdown
## 改了什么
- 新增/修改了哪些文件

## 为什么改
- 对应链路中的哪个环节

## 怎么测试
- 具体测试命令或步骤

## 剩余风险
- 依赖哪些未完成的模块
- 已知缺陷或 TODO
```

### PR 合并条件

- [ ] 所有测试通过（`pytest`）
- [ ] 单元测试覆盖率 ≥ 80%（`pytest --cov=src`）
- [ ] 没有修改对方负责的模块（除非已协调）
- [ ] 涉及 API/数据库/AI 输出结构变更时，文档已同步更新

---

## 五、禁止事项（两个 AI 均适用）

### 绝对禁止

- 直接推送到 `main`
- 删除或重写对方已有代码（除非用户明确要求并已告知对方）
- 在一个 PR 中同时修改前端、后端、数据库、AI Prompt 等多个无关区域
- 硬编码任何密钥、密码、Token（统一用环境变量）
- 在面向学生/家长的 API 响应中暴露内部错误信息、路径、堆栈
- 无鉴权地接受调用方提供的 `student_id`（IDOR 风险）

### 避免事项

- 重构对方写的代码（即使看起来可以更好，先提 Issue）
- 在不需要时引入新依赖
- 把同步 IO 操作（文件读写、网络请求）放在 `async def` 路由里不加 `asyncio.to_thread`
- 返回无 `response_model` 的 API 端点（破坏 OpenAPI 文档）

---

## 六、冲突处理流程

1. **发现对方已改动同一文件** → 停止，告知用户，不要覆盖
2. **对已有接口有修改需求** → 先提出，用户确认后再动
3. **发现对方代码有 bug** → 告知用户，由对方修，不要自行 patch 对方的文件

---

## 七、测试要求

| 测试类型 | 最低要求 | 工具 |
|---------|---------|------|
| 单元测试 | ≥ 80% 覆盖率 | `pytest --cov=src` |
| 集成测试 | 核心链路有集成测试 | `pytest -m integration` |
| AI 输出测试 | 必须提供可验证的评估样例 | 固定输入 → 预期输出断言 |

涉及 AI 输出的功能，必须在测试文件或文档里给出：
- 至少 3 个固定测试用例（输入 + 预期输出）
- 说明"什么样的输出算通过"

---

## 八、安全与成本控制

### 安全

- 涉及未成年人数据：所有 API 端点必须有鉴权（MVP 可以是 stub，但不能完全没有）
- 文件上传：MIME 类型 + 扩展名双重校验（已有），建议后续加 magic bytes 校验
- 数据库查询：不接受未经参数化的用户输入

### 成本控制

- OCR 调用：相同 `file_hash` 的图片不重复 OCR（已有 hash 去重逻辑）
- AI 调用：相同题目内容不重复分析（需要缓存层，Kiro 负责）
- 日志：记录每次 OCR/AI 调用的 token 数和费用（后续加）

---

## 九、文档同步要求

| 变更类型 | 需要同步更新的文档 |
|---------|----------------|
| 新增 API 端点 | `docs/` 下对应文档 + `GETTING_STARTED.md` |
| 数据库 schema 变更 | `alembic/` 迁移文件 + 模型注释 |
| AI Prompt 变更 | 对应 `docs/` 文档 + 评估样例 |
| 新增环境变量 | `.env.example` |
| 模块完成 | `GETTING_STARTED.md` 中的"已完成模块"列表 |

---

## 十、当前实际进度（更新于 2026-05-19）

### 已完成（Kiro）

- ✅ OCR 适配器（PaddleOCR-VL-1.5）
- ✅ AI 分析服务（豆包 Seed1.8 + OpenAI + MiniMax）
- ✅ 文件上传服务（hash 去重 + 本地存储）
- ✅ 数据库模型：`assignments`, `ocr_tasks`, `questions`, `knowledge_points`, `student_knowledge_profiles`
- ✅ FastAPI 主应用 + 上传 API
- ✅ Alembic 迁移环境

### 待完成（Kiro）

- [ ] Celery 异步任务队列：`uploaded` → OCR → AI 分析 → 知识点归档
- [ ] 知识点归档服务

### 待完成（Claude Code）

- [ ] 学生画像查询 API（`src/api/student.py`）
- [ ] 复习任务查询 API（`src/api/review.py`）
- [ ] 报告生成服务（`src/services/report_service.py`）
- [ ] 报告 API（`src/api/report.py`）
- [ ] 数据导出 API（`src/api/export.py`）

### 已知技术债（不阻塞开发，由 Kiro 评估修复时机）

- `Assignment.status` 列未用 `SQLAlchemyEnum`，枚举未在 DB 层强制
- `file_hash` 索引重复定义
- `KnowledgePoint.prerequisites/common_errors` 应改为 `JSONB`
- `OCRTask.assignment_id` 类型标注 `str` 与实际列类型 `UUID` 不一致
- 去重时全表扫 hash（应改为点查 `WHERE file_hash = ?`）
- 上传路由中 `FileService` 未走 DI
- 同步文件 IO 在 async 路由中阻塞事件循环
