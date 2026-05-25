# AI 批改模块 · 项目统筹文档

**版本：MVP v1.0 · 状态：正式开工基线**
**最后更新：2026-05-25**
**参与方：Claude（API 层）· Codex（服务层/模型层）**

---

## 目录

1. [总体立场](#一总体立场)
2. [整体架构](#二整体架构)
3. [质量检查](#三质量检查)
4. [Call 1 Output Schema](#四call-1-output-schema)
5. [Call 2 Output Schema](#五call-2-output-schema)
6. [Taxonomy 设计](#六taxonomy-设计)
7. [数据库表设计](#七数据库表设计)
8. [Mastery 聚合公式](#八mastery-聚合公式)
9. [Dispute 机制](#九dispute-机制)
10. [Golden Test Set](#十golden-test-set)
11. [Eval 验收标准](#十一eval-验收标准)
12. [Phase 计划](#十二phase-计划)
13. [MVP 明确不做](#十三mvp-明确不做)
14. [已钉死的决策](#十四已钉死的决策)
15. [实现待决问题](#十五实现待决问题)
16. [代码 Checkpoint](#十六代码-checkpoint)

---

## 一、总体立场

当前不继续直接写业务代码，先完成设计与验证地基。

AI 批改模块是一条新流水线，不是"多返回几段文本"：

```
图片上传
  → 前端压缩轻量化
  → Preflight 质量检查
  → Call 1：识题 + 解题 + 批改 + 候选知识点（多模态）
  → Post-AI 自洽检查
  → [support_status == supported] Call 2：taxonomy 映射（纯文本）
  → 数据库事务写入（grading_result + knowledge_event）
  → 同步聚合 student_knowledge_points
  → 前端展示 + 申诉入口
```

**MVP 目标：跑稳"批改 + 解题 + 知识点入库 + 可回滚的学生画像"，不做图谱可视化、记忆卡片、老师后台。**

---

## 二、整体架构

### 调用策略

- **最多 2 次 AI 调用**，不自动追加慢路径
- 不确定 → 标记 `review_required`，提示用户重拍或手动确认
- `support_status != supported` → 跳过 Call 2，不更新 mastery

### 为什么不拆成更多调用

识题、解题、批改共享同一份图像上下文，拆成多次调用：
- 速度和成本均不可接受
- 初二物理中计算题、实验题、图像题占比高，"慢路径"会变成主路径

Call 1 合并三件事是**工程取舍**，不是质量最优解。通过 eval 门槛、质量闸门、申诉机制控制风险。

> **已确认**：调整 JSON 字段输出顺序（"先 grading 后 solution"）不能解决模型内部推理污染，不作为质量修复手段。

---

## 三、质量检查

### 3.1 Preflight（AI 调用前）

便宜规则，不通过则不触发 AI：

| 检查项 | 条件 | 处理 |
|--------|------|------|
| 图片过小（可能是截图） | 压缩后 < 30KB **且** 长边 < 800px | 拒绝，提示重拍 |
| 图片尺寸异常 | 长边 < 200px | 拒绝 |
| 文件类型 | 非 image/\* | 拒绝 |
| 文件过大 | 压缩前 > 20MB | 拒绝 |
| 图片近似纯黑/纯白 | 均值像素 < 10 或 > 245 | 拒绝 |
| 低内容量（仅标记，不拒绝） | 压缩后 < 80KB | 写入 `quality_flags.low_payload_size = true` |

> **注意**：前端压缩后的清晰小图可能只有几十 KB，不能以 80KB 为拒绝门槛，避免误杀。

### 3.2 Post-AI（Call 1 返回后）

结构和自洽检查，失败项追加到 `review_reasons`：

```python
if solution.answer != grading.correct_answer:
    → review_reasons.append("answer_solution_mismatch")

if grading.student_answer is None and grading.is_correct is not None:
    → review_reasons.append("invalid_grading_without_answer")

if grading.score is not None and not (0.0 <= grading.score <= 1.0):
    → review_reasons.append("score_out_of_range")

if support_status in ("unsupported_subject", "unsupported_grade", "uncertain"):
    → review_reasons.append("unsupported_or_uncertain_subject")
    → 跳过 Call 2，不写 student_knowledge_event

if len(question_struct.stem.strip()) < 5:
    → review_reasons.append("stem_too_short")

if not question_struct 或 not solution 或 not grading:
    → review_reasons.append("incomplete_schema")
```

任一触发 → `review_required = True`。

> **注意**：不使用模型自报 `confidence` 作为主要闸门，它只作为 `KnowledgeCandidate` 的排序参考，不决定是否入库。

---

## 四、Call 1 Output Schema

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict

class QuestionStruct(BaseModel):
    subject: str                    # "physics"
    grade: str                      # "八年级"
    question_type: Literal[
        "multiple_choice",
        "fill_blank",
        "calculation",
        "experiment",
        "open_ended",
    ]
    stem: str                       # 题干文本
    options: Optional[Dict[str, str]] = None  # 选择题 {"A": "...", "B": "..."}
    diagrams: List[str] = []        # 图像/电路/实验器材的文字描述
    known_conditions: List[str] = []
    target: str                     # 题目求什么

class SolutionStep(BaseModel):
    step: int
    title: str                      # "判断受力方向"
    content: str
    used_knowledge: List[str] = []  # 自然语言，非 taxonomy ID

class Solution(BaseModel):
    answer: str                     # 最终答案
    solution_steps: List[SolutionStep]
    reasoning_summary: str          # 一句话核心思路

class Grading(BaseModel):
    student_answer: Optional[str] = None  # None = 图中无作答
    correct_answer: str
    is_correct: Optional[bool] = None     # student_answer 为 None 时必须是 None
    score: Optional[float] = None         # 0.0–1.0，计算题支持小数，None = 不可评分
    mistake_type: Optional[Literal[
        "correct",
        "concept_error",
        "calculation_error",
        "graph_reading_error",
        "experiment_design_error",
        "formula_error",
        "no_answer",
        "partial",
    ]] = None
    mistake_reason: Optional[str] = None
    feedback: Optional[str] = None

class KnowledgeCandidate(BaseModel):
    raw_name: str
    confidence: float               # 排序参考，不决定是否入库

class QualityFlags(BaseModel):
    low_payload_size: bool = False  # Preflight 标记
    missing_student_answer: bool = False
    answer_solution_mismatch: bool = False
    incomplete_schema: bool = False

class Call1Output(BaseModel):
    detected_subject: str           # "physics" / "math" / "chemistry" ...
    detected_grade: str             # "八年级" / "九年级" ...
    support_status: Literal[
        "supported",
        "unsupported_subject",
        "unsupported_grade",
        "uncertain",
    ]
    question_struct: QuestionStruct
    solution: Solution
    grading: Grading
    knowledge_candidates: List[KnowledgeCandidate] = Field(max_length=5)
    quality_flags: QualityFlags
    review_required: bool
    review_reasons: List[str] = []
```

### support_status 前端文案

| 值 | 前端提示 |
|----|---------|
| `supported` | 正常处理 |
| `unsupported_subject` | 当前知识点追踪仅支持初二物理 |
| `unsupported_grade` | 当前仅支持八年级题目 |
| `uncertain` | AI 无法确认学科，已解题但不记录知识点 |

> **两者区分**：`unsupported_subject` 是明确拒绝，`uncertain` 是 AI 没把握——用户感受不同，文案不同。

---

## 五、Call 2 Output Schema

```python
class MappedKnowledgePoint(BaseModel):
    taxonomy_id: str                # grading_taxonomy.id
    taxonomy_name: str
    confidence: float               # 排序参考
    match_method: Literal["exact", "alias", "ai_mapped"]
    role: Literal["primary", "secondary"]  # 主知识点 or 辅助知识点

class Call2Output(BaseModel):
    primary_knowledge_points: List[MappedKnowledgePoint]   # 最多 3 个
    unmapped_candidates: List[str]  # 映射失败 → 仅记日志，不进学生画像
    overall_confidence: float
```

> **`unmapped_candidates`** 写入后台日志，用于发现 taxonomy 缺口，不进入 `student_knowledge_events`。

---

## 六、Taxonomy 设计

### 存储形式

```
repo/data/taxonomy/physics_grade8.json
```

随代码版本控制，脚本导入数据库，**不允许 AI 自动新增**。

### 每条知识点结构

```json
{
  "id": "physics_g8_electricity_ohm_law_closed",
  "name": "闭合电路欧姆定律",
  "subject": "physics",
  "grade": "八年级",
  "chapter": "电学",
  "parent_id": "physics_g8_electricity",
  "level": 3,
  "aliases": [
    "闭合电路欧姆定律",
    "电源电动势和内阻",
    "路端电压关系",
    "U-I图像斜率内阻"
  ],
  "description": "理解电源电动势、内阻、路端电压与电流之间的关系，能从U-I图像读取参数。",
  "is_active": true
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✅ | 全局唯一，稳定不变，其他表外键引用此 ID |
| `name` | ✅ | 标准名称 |
| `subject` | ✅ | physics / math / chemistry |
| `grade` | ✅ | 八年级 / 九年级 |
| `chapter` | ✅ | 一级分类 |
| `parent_id` | ✅ | 上级节点，顶层为 null |
| `level` | ✅ | 1 = 章，2 = 节，3 = 知识点 |
| `aliases` | ✅ | **Call 2 映射质量的关键**，需要覆盖 AI 常用说法 |
| `description` | ✅ | 一句话定义 |
| `is_active` | ✅ | false 时不参与映射，历史 event 保留 |

> **`common_mistakes` 第一版不加**：下游用途未定，维护成本高，等错因数据积累后再补。

**MVP 规模：初二物理 60–100 条，人工维护。**

---

## 七、数据库表设计

> **2026-05-25 重要变更**：AI 批改模块的知识点表从 `knowledge_points` 更名为
> **`grading_taxonomy`**，以避免与 Kiro 已有的 `knowledge_points`（UUID 主键）冲突。
> Kiro 的 `knowledge_points` 表**不做任何修改**。两张表独立并存，MVP 阶段不合并。

### grading_taxonomy（AI 批改专用的人工维护 taxonomy 表）

```sql
CREATE TABLE grading_taxonomy (
    id          VARCHAR(128) PRIMARY KEY,  -- "physics_g8_electricity_ohm_law_closed"
    name        VARCHAR(256) NOT NULL,
    subject     VARCHAR(64)  NOT NULL,
    grade       VARCHAR(64)  NOT NULL,
    chapter     VARCHAR(128) NOT NULL,
    parent_id   VARCHAR(128) REFERENCES grading_taxonomy(id),
    level       SMALLINT     NOT NULL,     -- 1/2/3
    aliases     JSONB        NOT NULL DEFAULT '[]',
    description TEXT,
    is_active   BOOLEAN      NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

### assignment_analyses

```sql
CREATE TABLE assignment_analyses (
    id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id     UUID         NOT NULL REFERENCES assignments(id),
    student_id        VARCHAR(128) NOT NULL,
    detected_subject  VARCHAR(64),
    detected_grade    VARCHAR(64),
    support_status    VARCHAR(32),           -- supported / unsupported_* / uncertain
    question_struct   JSONB,
    review_required   BOOLEAN      NOT NULL DEFAULT false,
    review_reasons    JSONB        NOT NULL DEFAULT '[]',
    quality_flags     JSONB        NOT NULL DEFAULT '{}',
    call1_raw         JSONB,                 -- 完整 Call 1 输出，备查
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

### grading_results

```sql
CREATE TABLE grading_results (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id   UUID         NOT NULL REFERENCES assignments(id),
    student_id      VARCHAR(128) NOT NULL,
    correct_answer  TEXT         NOT NULL,
    student_answer  TEXT,                    -- null = 未作答
    is_correct      BOOLEAN,                 -- null = 不可评分
    score           NUMERIC(4,3),            -- 0.000–1.000
    max_score       NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    mistake_type    VARCHAR(64),
    mistake_reason  TEXT,
    feedback        TEXT,
    status          VARCHAR(32)  NOT NULL DEFAULT 'ai_final',
    -- ai_final / disputed / corrected / excluded
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (assignment_id)                   -- 幂等保证：同一作业只有一条批改结果
);
```

### question_knowledge_points

```sql
CREATE TABLE question_knowledge_points (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id       UUID         NOT NULL REFERENCES assignments(id),
    knowledge_point_id  VARCHAR(128) NOT NULL REFERENCES grading_taxonomy(id),
    role                VARCHAR(16)  NOT NULL DEFAULT 'primary',  -- primary / secondary
    confidence          NUMERIC(4,3) NOT NULL,
    match_method        VARCHAR(16)  NOT NULL,  -- exact / alias / ai_mapped
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

### student_knowledge_events（事实源）

```sql
CREATE TABLE student_knowledge_events (
    id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id            VARCHAR(128) NOT NULL,
    assignment_id         UUID         NOT NULL REFERENCES assignments(id),
    knowledge_point_id    VARCHAR(128) NOT NULL REFERENCES grading_taxonomy(id),

    -- 答题结果
    result                VARCHAR(16)  NOT NULL,  -- correct / wrong / partial
    score                 NUMERIC(4,3) NOT NULL,  -- 0.000–1.000
    max_score             NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    mistake_type          VARCHAR(64),

    -- 申诉状态（独立于 result）
    grading_status        VARCHAR(32)  NOT NULL DEFAULT 'ai_final',
    -- ai_final / disputed / corrected / excluded
    excluded_from_mastery BOOLEAN      NOT NULL DEFAULT false,
    -- excluded_from_mastery=true 时，无论 grading_status 是什么，权重为 0

    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),  -- 带时区，不可后补

    UNIQUE (assignment_id, knowledge_point_id)   -- 幂等：同一题同一知识点只有一条事件
);
```

> **`status_weight` 不落库**，聚合时动态计算，防止规则变更后历史数据脏掉。

### student_knowledge_points（聚合表，可重算）

```sql
CREATE TABLE student_knowledge_points (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id          VARCHAR(128) NOT NULL,
    knowledge_point_id  VARCHAR(128) NOT NULL REFERENCES grading_taxonomy(id),
    mastery             NUMERIC(5,4),        -- null = attempts < 3，显示"数据不足"
    attempts            INTEGER      NOT NULL DEFAULT 0,
    correct_count       INTEGER      NOT NULL DEFAULT 0,
    last_seen           TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (student_id, knowledge_point_id)
);
```

---

## 八、Mastery 聚合公式

### 权重映射（动态计算，不落库）

```python
GRADING_STATUS_WEIGHT = {
    "ai_final":  1.0,
    "disputed":  0.3,   # 申诉中，降权但不排除
    "corrected": 1.0,
    "excluded":  0.0,
}

def get_event_weight(event) -> float:
    # excluded_from_mastery 优先级最高
    if event.excluded_from_mastery:
        return 0.0
    return GRADING_STATUS_WEIGHT.get(event.grading_status, 1.0)
```

### 聚合算法

```python
def calc_mastery(events: List[Event]) -> Optional[float]:
    # 按时间倒序（越新权重越高）
    events = sorted(events, key=lambda e: e.created_at, reverse=True)

    total_weight = 0.0
    weighted_sum = 0.0
    decay = 1.0

    for event in events:
        status_w = get_event_weight(event)
        w = decay * status_w
        if w > 0:
            weighted_sum += w * (event.score / event.max_score)
            total_weight += w
        decay *= 0.8    # 几何衰减，每往前一条乘 0.8

    if len([e for e in events if get_event_weight(e) > 0]) < 3:
        return None     # 前端显示"数据不足"

    return weighted_sum / total_weight if total_weight > 0 else None
```

### 聚合触发时机

**事务写入 event 后同步重算**（MVP 阶段），并发高了再改异步聚合。

---

## 九、Dispute 机制

### 状态机

```
ai_final  ──[学生申诉]──▶  disputed
disputed  ──[管理员确认]──▶  corrected  (MVP 预留，无 UI)
disputed  ──[管理员排除]──▶  excluded   (MVP 预留，无 UI)
```

### MVP 行为

```
学生点击"我认为批改有误"
  → grading_results.status = "disputed"
  → student_knowledge_events.grading_status = "disputed"
  → 重新聚合该知识点 mastery（disputed 事件权重降至 0.3）
  → 前端显示"有争议"标记

corrected / excluded：
  → MVP 阶段预留字段，无管理员 UI
  → Phase D 老师端建好后启用
```

### 权限边界

| 角色 | 可操作的状态变更 |
|------|----------------|
| 学生 | `ai_final` → `disputed` |
| 管理员/老师（Phase D） | `disputed` → `corrected` 或 `excluded` |

**学生不能直接清空 mastery**：disputed 只降权（0.3），不排除（0.0）。

---

## 十、Golden Test Set

### 规模与覆盖

20–30 道真实初二物理题：

| 题型 | 数量 |
|------|------|
| 选择题 | 10 道 |
| 填空题 | 5 道 |
| 计算题 | 5 道 |
| 实验/图像题 | 5–10 道 |

### 每条样本结构

```json
{
  "id": "g8_physics_001",
  "image_path": "data/golden_set/images/g8_physics_001.jpg",
  "compressed_image_path": "data/golden_set/images/g8_physics_001_compressed.webp",
  "question_type": "multiple_choice",
  "standard_answer": "B",
  "student_answer": "A",
  "expected_is_correct": false,
  "expected_mistake_type": "concept_error",
  "expected_taxonomy_ids": [
    "physics_g8_electricity_ohm_law_closed"
  ],
  "acceptable_solution_points": [
    "能说明需要改变外电路电阻",
    "能区分电流表和电压表的作用"
  ],
  "notes": "学生混淆了电压表和电流表"
}
```

### 构建顺序

1. 先完成 taxonomy JSON（需要 taxonomy ID 才能标注 golden set）
2. 再设计 Call 1 prompt
3. 再建 golden set（有 prompt 才能跑并对比）
4. 再写 eval 脚本

---

## 十一、Eval 验收标准

### 上线门槛（功能）

| 指标 | 最低要求 | 理想目标 |
|------|---------|---------|
| `schema_parse_success` | ≥ 95% | 100% |
| `answer_accuracy` | ≥ 80% | ≥ 85% |
| `grading_accuracy` | ≥ 80% | ≥ 85% |
| `taxonomy_top1_hit` | ≥ 75% | ≥ 80% |

### 性能观测（不作为硬上线门槛）

| 指标 | 观测目标 | 说明 |
|------|---------|------|
| P50 单题耗时 | ≤ 30s | Volces 延迟波动大，不作功能门槛 |
| P90 单题耗时 | 先采样 | 首版记录基线 |
| 单题 API 成本 | 记录 | 评估长期可持续性 |

> **若 P50 > 30s**：必须进入性能优化讨论，但不自动判定功能不可上线。

### Eval 脚本必须记录

每题：调用次数、token 数量、图片大小、单题耗时、单题成本估算。

### 迭代规则

- 最多迭代 **3 轮**
- 每轮只改 **prompt** 或 **taxonomy**，不同时改两者
- 3 轮后仍不达标 → 停止 prompt 死磕，回到架构讨论（换模型 / 拆调用 / 增加 OCR）

---

## 十二、Phase 计划

### Phase A：数据地基（先于一切业务代码）

> **依赖关系**：taxonomy → grading schema → prompt → golden set → eval

| 步骤 | 任务 | 负责 |
|------|------|------|
| A1 | taxonomy schema 定义（本文档） | 已完成 |
| A2 | grading output schema 定义（本文档） | 已完成 |
| A3 | Call 1 / Call 2 prompt 设计文档 | Claude |
| A4 | 建初二物理 taxonomy JSON（60–100 条） | Codex / 双方 |
| A5 | 建 golden set schema + 20–30 道题 | Codex / 双方 |
| A6 | 写 eval 脚本 | Claude |
| A7 | 跑 eval，采集准确率 / 耗时 / 成本 | 双方 |
| A8 | 结果达标 → 进入 Phase B；不达标 → 迭代 prompt（≤ 3 轮） | 双方 |

### Phase B：核心管道

| 任务 | 说明 |
|------|------|
| 建 6 张核心表 | 含种子数据导入脚本 |
| Celery 任务 | preflight → Call 1 → 自洽检查 → Call 2 → 事务写入 → 同步聚合 |
| Dispute 状态机 | 写入 + 重算逻辑 |
| Kiro 接口对齐 | **Phase B 开始前**必须确认 student_knowledge_events 与 StudentKnowledgeProfile 的接口边界，不改 Kiro 文件 |

### Phase C：前端展示

| 组件 | 内容 |
|------|------|
| 批改结果卡片 | 是否正确 / 错因 / 得分 |
| 解题步骤 | 分步展示，含用到的知识点 |
| 知识点标签 | primary / secondary 区分 |
| review_required 提示 | 重拍引导 / 学科不支持说明 |
| 申诉按钮 | "我认为批改有误" |

### Phase D：原 Phase 3–7 收尾

Phase B 产生稳定数据后，原有模块消费新数据：

- `student.py` — 学生画像查询（读 student_knowledge_points）
- `review.py` — 复习计划（基于 mastery 生成）
- `report_service` — 学习报告
- `export.py` — 数据导出
- `visualization` — 可视化（P2，可选）

---

## 十三、MVP 明确不做

- 记忆卡片
- 知识图谱可视化
- 老师 / 管理员审核后台（UI）
- 同类题推荐（需要题库）
- 多学科支持（第一版仅初二物理）
- 艾宾浩斯 / 贝叶斯 mastery 算法
- AI 自动新增知识点
- 自动高风险慢路径（3 次调用）
- `common_mistakes` 字段

---

## 十四、已钉死的决策

| 问题 | 决策 |
|------|------|
| AI 调用次数上限 | 最多 2 次，不自动慢路径 |
| 不确定时处理 | `review_required = true`，提示用户 |
| `uncertain` 处理 | 可讲题，不入 taxonomy，不更新 mastery |
| `uncertain` vs `unsupported` 文案 | 区分，见第四节 |
| `disputed` 权重 | 0.3（先写死，有数据再调） |
| `excluded_from_mastery` 优先级 | 为 true 时，权重强制为 0，无视 grading_status |
| `status_weight` 落库 | **不落库**，聚合时动态计算 |
| 知识点新增 | 人工维护，AI 只能映射，不能创造 |
| unmapped 候选 | 仅记日志，不进学生画像 |
| mastery 数据不足 | attempts（有效权重 > 0）< 3 → 显示"数据不足" |
| taxonomy 存储 | repo 内 JSON + 版本控制 + 脚本导入 |
| 聚合触发时机 | 事务后同步重算（MVP），并发高了再改异步 |
| eval 迭代上限 | 3 轮，不达标进架构讨论 |
| P50 ≤ 30s | 性能观测目标，**不是**功能上线门槛 |
| KnowledgeCandidate.confidence | 仅排序参考，不决定是否入库 |
| 字段命名 | `question_struct`（不用 `question`） |
| event result 枚举 | `correct / wrong / partial`（无 `uncertain`） |
| student_answer 为 null | **不写** student_knowledge_event，不是写 `uncertain` |
| question_knowledge_points | 含 `role`、`confidence`、`match_method` |
| 幂等键 | `grading_results.UNIQUE(assignment_id)` / `student_knowledge_events.UNIQUE(assignment_id, knowledge_point_id)` |
| preflight 80KB | 不拒绝，仅标记 `low_payload_size` |

---

## 十五、实现待决问题

以下问题已识别，不阻塞 Phase A，实现时需明确：

| 问题 | 说明 |
|------|------|
| Celery 任务重试策略 | Call 1 超时后，是整个 assignment 重跑，还是只重试 Call 1？ |
| 聚合并发锁 | 同一学生同一知识点并发写事件时的锁策略 |
| `is_active=false` 历史处理 | 知识点下线后，已有 event 的 mastery 如何处理 |
| P50 测量条件 | 单用户还是并发？Volces 高峰延迟？需要实测 |
| Kiro 接口细节 | Phase B 开始前对齐，新增旁路表而非修改 Kiro 文件 |
| `uncertain` 触发的 support_status 下的前端 UX | 解题结果是否展示？展示时加什么提示？ |

---

## 十六、代码 Checkpoint

| 提交 | 内容 | 状态 |
|------|------|------|
| `36ad9fd` | feat: add AI grading pipeline schemas | ✅ 已合并 |
| `f6476c3` | test: add AI grading schema contract | ✅ 已合并 |
| `fc8c76e` | fix: align AI grading schema field names | ✅ 已合并 |
| `fcbf3ba` | test: align AI grading schema with MVP docs | ✅ 已合并 |
| `57afddd` | fix: align AI grading schema with MVP docs | ✅ 已合并 |
| `c4c5944` | test: define grade 8 physics taxonomy contract | ✅ 已合并 |
| `4b5bf28` | feat: add grade 8 physics taxonomy (88 条) | ✅ 已合并 |
| `e428c41` | feat: add eval script and prompt constants module | ✅ 已合并 |
| `71abe63` | test: define golden set contract | ✅ 已合并 |
| `ae41688` | feat: add golden set seed data (24 cases, synthetic_seed) | ✅ 已合并 |

**当前 schema 状态（`57afddd` 后，完全对齐文档）：**

- `KnowledgeCandidate`：`raw_name` / `confidence`（旧版 `name` / `reason` 已废弃）
- `QualityFlags`：4 个布尔字段；`review_required` / `review_reasons` 独立于 flags 之外
- `SolutionResult`：`solution_steps`（`min_length=1`）/ `reasoning_summary`
- `GradingResult`：含 `student_answer` / `correct_answer`；`score` 可为 null（0.0–1.0）
- `QuestionStruct`：不再含 `student_answer` / `correct_answer`
- `MappedKnowledgePoint`：含 `taxonomy_name` / `match_method` / `role`；`KnowledgeRole` 枚举去掉 `prerequisite`
- `KnowledgeMappingResult`：`primary_knowledge_points`（`max_length=3`）/ `unmapped_candidates: list[str]` / `overall_confidence`
- `MistakeType`：与文档对齐（含 `correct` / `formula_error` / `no_answer` / `partial`）
- `KnowledgeEventResult`：`correct / partial / wrong`（无 `uncertain`）
- `StudentKnowledgeEventPayload`：event 层保留 `score` / `max_score`（AI 输出层 `GradingResult.score` 是 0–1 比例，event 层保留原始分值，两者含义不同）
- 测试结果：**17 passed, 1 warning**

**Phase A 进度（Claude）：**

1. ✅ Call 1 / Call 2 prompt 设计文档（`docs/PROMPT_DESIGN.md`）
2. ✅ Eval 脚本（`scripts/run_eval.py`）+ prompt 常量模块（`src/prompts/grading.py`）

**Phase A 当前状态：管道全部就绪，等用户触发第一次 eval。**

```bash
# 配置好 API key 后运行（.env 里应该已有 DOUBAO_SEED_API_KEY）：
python scripts/run_eval.py --output-json results/eval_synthetic_v1.json

# ablation：对比有无 few-shot 的差异
python scripts/run_eval.py --no-few-shot --output-json results/eval_synthetic_v1_nofewshot.json
```

> **注意**：当前 golden set 全部为 `synthetic_seed`（合成图片）。
> `schema_parse_success` 和 `taxonomy_top1_hit` 结果可信；
> `answer_accuracy` 和 `grading_accuracy` 会偏乐观，**不作为最终验收依据**。
> 正式验收需补充 ≥10 张真实学生拍照样本后重跑。

**Phase A 下一步（用户 / Codex 负责）：**

1. 建 `data/taxonomy/physics_grade8.json`（60–100 条）
2. 建 golden set（20–30 道题 + 图片）

---

*文档版本由 Claude 整理，基于 Claude × Codex 多轮设计对齐。如有修改，请注明变更条目和原因。*
