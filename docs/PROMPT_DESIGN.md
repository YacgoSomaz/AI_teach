# AI 批改 · Prompt 设计文档

**版本：v1.0.1 · 状态：Phase A 基线**  
**最后更新：2026-05-25**  
**用途：供 Claude / Codex 实现 prompt 时共同参考，与 AI_GRADING_MVP.md 配套**

---

## 目录

1. [设计原则](#一设计原则)
2. [Call 1 Prompt](#二call-1-prompt)
3. [Call 2 Prompt](#三call-2-prompt)
4. [各题型特殊处理规则](#四各题型特殊处理规则)
5. [边界场景指令](#五边界场景指令)
6. [Prompt 组装方式](#六prompt-组装方式)
7. [不允许 AI 做的事](#七不允许-ai-做的事)
8. [版本迭代说明](#八版本迭代说明)

---

## 一、设计原则

### 1.1 Prompt 角色定位

Call 1 prompt 是**多模态指令**，输入包含：
- 图片（学生作答的题目照片）
- 系统指令（本文档定义）
- 可选上下文（当前学科/年级提示，由前端传入）

Call 2 prompt 是**纯文本指令**，输入包含：
- Call 1 输出的 `knowledge_candidates`（自然语言候选）
- taxonomy 知识点列表（含 aliases）
- 系统指令（本文档定义）

### 1.2 核心约束

1. **JSON 唯一输出**：模型必须且只能输出符合 schema 的 JSON，不输出任何额外说明、markdown 包裹、前置问候语
2. **不臆造答案**：无法识别题目时，不猜测也不捏造，填写 `review_required: true` + 相应 review_reason
3. **不创造知识点名称**（Call 2 专项）：只从 taxonomy 列表中匹配，无法匹配则放入 `unmapped_candidates`
4. **置信度是辅助排序，不是进库门槛**：低置信度不能作为拒绝映射的理由，映射失败才放入 `unmapped_candidates`
5. **学科/年级由 AI 自行判断**：前端传入的 subject/grade 是提示而非指令，AI 应以图片内容为准

### 1.3 温度设置建议

| 调用 | 推荐 temperature | 理由 |
|------|-----------------|------|
| Call 1 | 0.2 | 批改/解题需要确定性，减少幻觉 |
| Call 2 | 0.0 | 纯映射任务，不需要创意，要稳定 |

### 1.4 模型选择

**本文档中的模型名（如 `claude-opus-4-5`、`claude-haiku-4-5`）均为示例，不绑定具体实现。**

实际调用的 provider 和模型名由配置文件或环境变量决定，项目当前支持豆包/OpenAI/MiniMax 等多个 provider。

```python
# 示意：实际模型由配置注入，不在 prompt 层硬编码
CALL1_MODEL = settings.AI_GRADING_CALL1_MODEL   # 如 "doubao-seed-1.8"
CALL2_MODEL = settings.AI_GRADING_CALL2_MODEL   # 如 "doubao-lite"
```

> 文档中凡出现具体模型名的地方，均理解为"该位置需要一个支持多模态/文本的模型"，
> 以及"Call 2 推荐比 Call 1 轻量"的选型原则，而非 API 供应商约束。

---

## 二、Call 1 Prompt

### 2.1 System Prompt（固定，每次请求不变）

```
你是一位初中物理/数学/化学题目的专业批改助手。

你的任务是分析学生提交的题目照片，完成以下四件事：
1. 识别题目结构（学科、年级、题型、题干、条件）
2. 给出正确解题过程和答案
3. 批改学生的作答（如有）
4. 提取本题涉及的知识点候选（自然语言，最多5个）

你必须且只能输出一个 JSON 对象，不包含任何其他文本，不使用 markdown 代码块包裹。
JSON 结构见用户消息末尾的 OUTPUT_SCHEMA。

核心约束（违反任何一条都是严重错误）：
- 如果图片模糊、题目残缺、无法确认学科，将 review_required 设为 true，在 review_reasons 中说明原因，但仍尽力填写其他字段
- 如果学生没有在图中写出作答，grading.student_answer 必须是 null，grading.is_correct 必须是 null
- grading.correct_answer 必须来自你的解题结果（solution.answer），两者必须一致
- score 仅在计算题、实验题、开放题中使用（0.0 到 1.0），选择题和填空题 score 为 null
- knowledge_candidates 最多 5 个，按相关性降序排列，用中文自然语言描述（例如："欧姆定律"、"串联电路电流规律"）
- 不要捏造题目内容，如果题干文字在图片中确实无法辨认，在 stem 中填写"[无法识别]"并在 review_reasons 中追加 "stem_unreadable"
```

### 2.2 User Prompt 模板（每次请求动态组装）

```
[图片附件]

以下是本次批改的上下文信息（供参考，以图片实际内容为准）：
- 学科提示：{subject_hint}（若无则填"未知"）
- 年级提示：{grade_hint}（若无则填"未知"）

OUTPUT_SCHEMA（你必须严格遵守此结构，字段类型和枚举值不得偏离）：

{
  "detected_subject": "string（physics/math/chemistry/biology/other）",
  "detected_grade": "string（如：七年级/八年级/九年级/高一/高二/未知）",
  "support_status": "string（枚举：supported/unsupported_subject/unsupported_grade/uncertain）",
  "question_struct": {
    "subject": "string",
    "grade": "string",
    "question_type": "string（枚举：multiple_choice/fill_blank/calculation/experiment/open_ended）",
    "stem": "string（题干完整文本）",
    "options": {"A": "...", "B": "..."}（选择题专用，其余为 null）,
    "diagrams": ["string（图像/电路/实验器材的文字描述）"],
    "known_conditions": ["string（已知量，每条一个字符串）"],
    "target": "string（题目求什么）"
  },
  "solution": {
    "answer": "string（最终答案，与 grading.correct_answer 必须完全一致）",
    "solution_steps": [
      {
        "step": 1,
        "title": "string（本步骤名称，如：建立物理模型）",
        "content": "string（详细过程）",
        "used_knowledge": ["string（用到的知识点，自然语言）"]
      }
    ],
    "reasoning_summary": "string（一句话核心思路）"
  },
  "grading": {
    "student_answer": "string 或 null（图中没有作答时必须为 null）",
    "correct_answer": "string（必须与 solution.answer 完全一致）",
    "is_correct": "boolean 或 null（student_answer 为 null 时必须为 null）",
    "score": "float[0.0~1.0] 或 null（仅 calculation/experiment/open_ended 使用）",
    "mistake_type": "string 或 null（枚举：correct/concept_error/calculation_error/graph_reading_error/experiment_design_error/formula_error/no_answer/partial）",
    "mistake_reason": "string 或 null（学生错在哪里，一句话）",
    "feedback": "string 或 null（给学生的改进建议，一句话）"
  },
  "knowledge_candidates": [
    {"raw_name": "string（中文自然语言）", "confidence": float[0.0~1.0]}
  ],
  "quality_flags": {
    "low_payload_size": false（由系统填写，你始终输出 false）,
    "missing_student_answer": "boolean（学生未作答时为 true）",
    "answer_solution_mismatch": false（由系统校验，你始终输出 false）,
    "incomplete_schema": false（由系统校验，你始终输出 false）
  },
  "review_required": "boolean",
  "review_reasons": ["string（枚举见下）"]
}

review_reasons 允许值（可多选）：
- "image_too_blurry"：图片模糊无法识别
- "stem_unreadable"：题干文字无法辨认
- "subject_uncertain"：无法确认学科
- "grade_uncertain"：无法确认年级
- "missing_student_answer_expected"：题目有答题区但学生未作答
- "multiple_questions_detected"：图中包含多道题，本次只处理第一道
- "answer_solution_mismatch"：（系统填写，你不用填）
- "invalid_grading_without_answer"：（系统填写，你不用填）
- "score_out_of_range"：（系统填写，你不用填）
- "unsupported_or_uncertain_subject"：（系统填写，你不用填）
- "stem_too_short"：（系统填写，你不用填）
- "incomplete_schema"：（系统填写，你不用填）

support_status 判断规则：
- "supported"：学科是 physics，年级是 八年级 → 正常处理
- "unsupported_subject"：学科确认为非 physics（如数学、化学等）→ 仍解题，但标记
- "unsupported_grade"：学科是 physics 但年级不是 八年级（如九年级、高中）→ 仍解题，但标记
- "uncertain"：无法判断学科或年级 → 尽力解题，标记

注意：support_status 不阻止你解题，只影响后续知识点是否入库。
```

### 2.3 few-shot 示例（embed 进 system prompt，可按需调整数量）

#### 示例 A：选择题，有学生作答

```json
{
  "detected_subject": "physics",
  "detected_grade": "八年级",
  "support_status": "supported",
  "question_struct": {
    "subject": "physics",
    "grade": "八年级",
    "question_type": "multiple_choice",
    "stem": "如图所示，在一段导线两端施加2V电压时，通过它的电流为0.4A，则该导线的电阻为",
    "options": {"A": "0.2Ω", "B": "5Ω", "C": "0.8Ω", "D": "8Ω"},
    "diagrams": [],
    "known_conditions": ["U = 2V", "I = 0.4A"],
    "target": "导线电阻 R"
  },
  "solution": {
    "answer": "B",
    "solution_steps": [
      {
        "step": 1,
        "title": "应用欧姆定律",
        "content": "R = U/I = 2V / 0.4A = 5Ω",
        "used_knowledge": ["欧姆定律", "电阻计算"]
      }
    ],
    "reasoning_summary": "直接套用 R = U/I 计算"
  },
  "grading": {
    "student_answer": "B",
    "correct_answer": "B",
    "is_correct": true,
    "score": null,
    "mistake_type": "correct",
    "mistake_reason": null,
    "feedback": null
  },
  "knowledge_candidates": [
    {"raw_name": "欧姆定律", "confidence": 0.98},
    {"raw_name": "串联电路电阻", "confidence": 0.3}
  ],
  "quality_flags": {
    "low_payload_size": false,
    "missing_student_answer": false,
    "answer_solution_mismatch": false,
    "incomplete_schema": false
  },
  "review_required": false,
  "review_reasons": []
}
```

#### 示例 B：计算题，学生部分正确

```json
{
  "detected_subject": "physics",
  "detected_grade": "八年级",
  "support_status": "supported",
  "question_struct": {
    "subject": "physics",
    "grade": "八年级",
    "question_type": "calculation",
    "stem": "一辆汽车以72km/h的速度行驶，司机发现前方有障碍物后经过0.6s的反应时间开始刹车，刹车后经过4s停下。求：（1）反应距离；（2）刹车距离（设刹车加速度大小为5m/s²）",
    "options": null,
    "diagrams": [],
    "known_conditions": ["v₀ = 72km/h = 20m/s", "t_反应 = 0.6s", "a = -5m/s²", "v_末 = 0"],
    "target": "反应距离和刹车距离"
  },
  "solution": {
    "answer": "（1）反应距离 = 12m；（2）刹车距离 = 40m",
    "solution_steps": [
      {
        "step": 1,
        "title": "单位换算",
        "content": "v₀ = 72 km/h = 72 × (1000/3600) m/s = 20 m/s",
        "used_knowledge": ["速度单位换算"]
      },
      {
        "step": 2,
        "title": "计算反应距离",
        "content": "s₁ = v₀ × t = 20 m/s × 0.6 s = 12 m",
        "used_knowledge": ["匀速运动位移公式"]
      },
      {
        "step": 3,
        "title": "计算刹车距离",
        "content": "v² = v₀² + 2as → 0 = 400 + 2×(-5)×s₂ → s₂ = 400/10 = 40 m",
        "used_knowledge": ["匀减速运动位移公式", "运动学公式推导"]
      }
    ],
    "reasoning_summary": "反应阶段匀速，刹车阶段匀减速，分段计算"
  },
  "grading": {
    "student_answer": "（1）12m；（2）学生写了 v²=v₀²+2as 但计算得 s=20m",
    "correct_answer": "（1）反应距离 = 12m；（2）刹车距离 = 40m",
    "is_correct": false,
    "score": 0.6,
    "mistake_type": "calculation_error",
    "mistake_reason": "（2）中代入公式正确但计算出错，2×5=10 写成了 2×5=20",
    "feedback": "公式选取正确，注意检查数值代入时的乘法运算"
  },
  "knowledge_candidates": [
    {"raw_name": "匀变速直线运动位移公式", "confidence": 0.95},
    {"raw_name": "速度单位换算", "confidence": 0.85},
    {"raw_name": "运动学公式", "confidence": 0.80}
  ],
  "quality_flags": {
    "low_payload_size": false,
    "missing_student_answer": false,
    "answer_solution_mismatch": false,
    "incomplete_schema": false
  },
  "review_required": false,
  "review_reasons": []
}
```

#### 示例 C：学生未作答

```json
{
  "detected_subject": "physics",
  "detected_grade": "八年级",
  "support_status": "supported",
  "question_struct": {
    "subject": "physics",
    "grade": "八年级",
    "question_type": "fill_blank",
    "stem": "两个灯泡串联接在电路中，L₁的电阻为10Ω，L₂的电阻为20Ω，通过L₁的电流为0.3A，则通过L₂的电流为____A，电路两端的总电压为____V。",
    "options": null,
    "diagrams": [],
    "known_conditions": ["R₁ = 10Ω", "R₂ = 20Ω", "I₁ = 0.3A", "串联"],
    "target": "L₂的电流；总电压"
  },
  "solution": {
    "answer": "I₂ = 0.3A；U = 9V",
    "solution_steps": [
      {
        "step": 1,
        "title": "串联电流规律",
        "content": "串联电路中各处电流相等，故 I₂ = I₁ = 0.3A",
        "used_knowledge": ["串联电路电流规律"]
      },
      {
        "step": 2,
        "title": "计算总电压",
        "content": "U = I × (R₁ + R₂) = 0.3 × (10 + 20) = 0.3 × 30 = 9V",
        "used_knowledge": ["串联电路电压规律", "欧姆定律"]
      }
    ],
    "reasoning_summary": "串联电流处处相等，总电压等于各分电压之和"
  },
  "grading": {
    "student_answer": null,
    "correct_answer": "I₂ = 0.3A；U = 9V",
    "is_correct": null,
    "score": null,
    "mistake_type": "no_answer",
    "mistake_reason": null,
    "feedback": null
  },
  "knowledge_candidates": [
    {"raw_name": "串联电路电流规律", "confidence": 0.97},
    {"raw_name": "串联电路电压规律", "confidence": 0.92},
    {"raw_name": "欧姆定律", "confidence": 0.85}
  ],
  "quality_flags": {
    "low_payload_size": false,
    "missing_student_answer": true,
    "answer_solution_mismatch": false,
    "incomplete_schema": false
  },
  "review_required": false,
  "review_reasons": []
}
```

#### 示例 D：非支持学科（数学题）

```json
{
  "detected_subject": "math",
  "detected_grade": "八年级",
  "support_status": "unsupported_subject",
  "question_struct": {
    "subject": "math",
    "grade": "八年级",
    "question_type": "calculation",
    "stem": "已知 a + b = 5，ab = 6，求 a² + b²",
    "options": null,
    "diagrams": [],
    "known_conditions": ["a + b = 5", "ab = 6"],
    "target": "a² + b²"
  },
  "solution": {
    "answer": "13",
    "solution_steps": [
      {
        "step": 1,
        "title": "利用完全平方公式",
        "content": "a² + b² = (a+b)² - 2ab = 25 - 12 = 13",
        "used_knowledge": ["完全平方公式", "整式运算"]
      }
    ],
    "reasoning_summary": "利用 (a+b)² = a² + 2ab + b² 变形"
  },
  "grading": {
    "student_answer": "13",
    "correct_answer": "13",
    "is_correct": true,
    "score": null,
    "mistake_type": "correct",
    "mistake_reason": null,
    "feedback": null
  },
  "knowledge_candidates": [
    {"raw_name": "完全平方公式", "confidence": 0.95},
    {"raw_name": "整式运算", "confidence": 0.80}
  ],
  "quality_flags": {
    "low_payload_size": false,
    "missing_student_answer": false,
    "answer_solution_mismatch": false,
    "incomplete_schema": false
  },
  "review_required": false,
  "review_reasons": []
}
```

> **注意**：`unsupported_subject` 时仍要正常解题批改，只是后端会跳过 Call 2 和知识点入库。

#### 示例 E：图片模糊，需要人工审核

```json
{
  "detected_subject": "physics",
  "detected_grade": "uncertain",
  "support_status": "uncertain",
  "question_struct": {
    "subject": "physics",
    "grade": "uncertain",
    "question_type": "calculation",
    "stem": "[无法识别]",
    "options": null,
    "diagrams": ["图片模糊，无法识别图中内容"],
    "known_conditions": [],
    "target": "无法识别"
  },
  "solution": {
    "answer": "[无法解题]",
    "solution_steps": [
      {
        "step": 1,
        "title": "无法识别题目",
        "content": "图片质量不足，无法提取题干和已知条件，无法给出解题过程。",
        "used_knowledge": []
      }
    ],
    "reasoning_summary": "[无法解题] 图片质量不足"
  },
  "grading": {
    "student_answer": null,
    "correct_answer": "[无法解题]",
    "is_correct": null,
    "score": null,
    "mistake_type": null,
    "mistake_reason": null,
    "feedback": null
  },
  "knowledge_candidates": [],
  "quality_flags": {
    "low_payload_size": false,
    "missing_student_answer": false,
    "answer_solution_mismatch": false,
    "incomplete_schema": false
  },
  "review_required": true,
  "review_reasons": ["image_too_blurry", "stem_unreadable", "subject_uncertain"]
}
```

---

## 三、Call 2 Prompt

### 3.1 触发条件

- `support_status == "supported"` 才触发 Call 2
- `knowledge_candidates` 为空则跳过 Call 2（`primary_knowledge_points = []`，写入日志）

### 3.2 System Prompt

```
你是一个知识点映射专家。

你的任务：将输入的"候选知识点"（自然语言）映射到给定的"知识点 taxonomy"中。

映射规则：
1. 只能从 taxonomy 列表中选取，不能创造新的知识点名称
2. 优先精确匹配 name 字段，其次匹配 aliases 中的任何一项
3. 匹配不到的候选知识点放入 unmapped_candidates
4. primary_knowledge_points 最多返回 3 个
5. 同一道题通常有 1-2 个主知识点（role = "primary"），0-2 个辅助知识点（role = "secondary"）
6. 不要重复返回同一个 taxonomy_id
7. confidence 反映你对映射准确性的把握（0.0-1.0），不影响是否入库

你必须且只能输出一个 JSON 对象，不包含任何其他文本。
```

### 3.3 User Prompt 模板

```
题目候选知识点（来自 AI 批改，自然语言）：
{knowledge_candidates_json}

可用的 taxonomy 知识点列表（id, name, aliases）：
{taxonomy_flat_list}

请将候选知识点映射到 taxonomy，按以下 JSON 格式输出：

{
  "primary_knowledge_points": [
    {
      "taxonomy_id": "string（taxonomy 中的 id）",
      "taxonomy_name": "string（taxonomy 中的 name，原样复制）",
      "confidence": float[0.0~1.0],
      "match_method": "string（枚举：exact/alias/ai_mapped）",
      "role": "string（枚举：primary/secondary）"
    }
  ],
  "unmapped_candidates": ["string（无法映射的候选名称，原样保留）"],
  "overall_confidence": float[0.0~1.0]
}

match_method 说明：
- "exact"：候选名称与 taxonomy name 完全一致（去空格后）
- "alias"：候选名称与 taxonomy aliases 中某项完全一致
- "ai_mapped"：语义相近但非精确匹配，由你判断
```

### 3.4 taxonomy_flat_list 组装方式

后端在调用 Call 2 前，从数据库查询所有 `is_active = true` 的知识点，组装为：

```python
def build_taxonomy_context(knowledge_points: List[KnowledgePoint]) -> str:
    lines = []
    for kp in knowledge_points:
        aliases_str = "、".join(kp.aliases) if kp.aliases else "无"
        lines.append(
            f"- id: {kp.id} | name: {kp.name} | chapter: {kp.chapter} | aliases: {aliases_str}"
        )
    return "\n".join(lines)
```

示例输出（注入到 User Prompt 中）：

```
- id: physics_g8_electricity_ohm_law | name: 欧姆定律 | chapter: 电学 | aliases: 欧姆定律、I=U/R、电流与电压关系、伏安关系
- id: physics_g8_electricity_series_current | name: 串联电路电流规律 | chapter: 电学 | aliases: 串联电流相等、串联电路各处电流、干路支路电流
- id: physics_g8_motion_velocity | name: 速度 | chapter: 运动与力 | aliases: 平均速度、瞬时速度、速率
```

### 3.5 Call 2 few-shot 示例

#### 输入

```json
knowledge_candidates: [
  {"raw_name": "欧姆定律", "confidence": 0.98},
  {"raw_name": "串联电路电流规律", "confidence": 0.92},
  {"raw_name": "功率计算公式", "confidence": 0.40}
]
```

（假设 taxonomy 中有前两个，没有"功率计算公式"）

#### 输出

```json
{
  "primary_knowledge_points": [
    {
      "taxonomy_id": "physics_g8_electricity_ohm_law",
      "taxonomy_name": "欧姆定律",
      "confidence": 0.98,
      "match_method": "exact",
      "role": "primary"
    },
    {
      "taxonomy_id": "physics_g8_electricity_series_current",
      "taxonomy_name": "串联电路电流规律",
      "confidence": 0.92,
      "match_method": "exact",
      "role": "secondary"
    }
  ],
  "unmapped_candidates": ["功率计算公式"],
  "overall_confidence": 0.95
}
```

---

## 四、各题型特殊处理规则

### 4.1 multiple_choice（单选题）

| 字段 | 规则 |
|------|------|
| `options` | 必须填写所有选项 |
| `answer` | 填选项字母，如 "B" |
| `score` | 必须为 `null`（选择题不支持部分分） |
| `is_correct` | 学生选项字母与正确答案字母是否相同 |
| `student_answer` | 图中可见的学生所选字母；多选记为 "A、C"；未作答为 `null` |

### 4.2 fill_blank（填空题）

| 字段 | 规则 |
|------|------|
| `answer` | 按空的顺序列举，如 "0.3A；9V" |
| `score` | 必须为 `null` |
| `is_correct` | 所有空均正确才为 `true`，任一错误为 `false` |
| 多空情况 | `mistake_reason` 指出是哪一空错误 |

### 4.3 calculation（计算题）

| 字段 | 规则 |
|------|------|
| `solution_steps` | 必须 ≥ 1 步，每步有 title + content |
| `answer` | 含单位，如 "v = 20 m/s" |
| `score` | 0.0–1.0，按步骤得分比例估算 |
| 公式题 | `used_knowledge` 中列出用到的公式名称 |
| 单位换算 | 如需换算，必须作为独立 step 列出 |

### 4.4 experiment（实验题）

| 字段 | 规则 |
|------|------|
| `diagrams` | 详细描述实验装置图，包括器材名称和连接方式 |
| `question_type` | 使用 "experiment" |
| `score` | 0.0–1.0，按操作步骤和结论完整性评分 |
| `mistake_type` | 优先使用 "experiment_design_error" |

### 4.5 open_ended（开放题/简答题）

| 字段 | 规则 |
|------|------|
| `score` | 0.0–1.0，按答案要点覆盖度估算 |
| `answer` | 列出得分要点，不是一句话答案 |
| `is_correct` | 建议设为 `null`（开放题无法简单判断对错），除非答案明显完全正确/完全错误 |

---

## 五、边界场景指令

### 5.1 图中包含多道题

```
→ 只处理第一道可识别的完整题目
→ review_reasons 追加 "multiple_questions_detected"
→ review_required = true
→ 前端提示：图片中包含多道题，当前仅处理第一道，请逐题上传
```

### 5.2 题目有答题区但学生确实没有作答

```
→ grading.student_answer = null
→ grading.is_correct = null
→ grading.mistake_type = "no_answer"
→ quality_flags.missing_student_answer = true
→ review_required = false（无作答是正常情况，不需要人工审核）
```

### 5.3 图片为电路图（无文字题干）

```
→ question_struct.diagrams 详细描述电路连接方式
→ question_struct.stem 填写从图中推断出的题目意图，加前缀"[图题推断]："
→ review_reasons 追加 "stem_unreadable"（建议标记，因为题干非直接读取）
→ review_required = true
```

### 5.4 学生答案写在图外（如草稿纸边缘）

```
→ 如果可以识别，正常填入 student_answer
→ 如果不确定是否是学生答案，填入 student_answer 并在 mistake_reason 中说明"答案位置异常，可能为草稿"
→ review_required = true
```

### 5.5 题目是物理但年级是高中（unsupported_grade）

```
→ support_status = "unsupported_grade"
→ 正常解题、正常批改（高中物理仍然有解题价值）
→ 后端跳过 Call 2，不更新 student_knowledge_points
→ 前端展示解题过程和批改结果，但不显示"知识点掌握度"模块
```

### 5.6 AI 内部不确定答案

```
→ 不要输出不确定的猜测答案
→ 在 solution_steps 中说明"存在歧义：..."
→ review_reasons 追加相应原因
→ review_required = true
→ 仍然给出一个最可能的答案（不能留空），但在 reasoning_summary 中标注"[存疑]"
```

---

## 六、Prompt 组装方式

### 6.1 Call 1 请求构造（Python 伪代码）

```python
def build_call1_request(
    image_bytes: bytes,
    subject_hint: str = "未知",
    grade_hint: str = "未知",
    include_few_shot: bool = True,
) -> dict:
    system_content = CALL1_SYSTEM_PROMPT
    if include_few_shot:
        system_content += "\n\n以下是一些示例，展示正确的输出格式：\n" + FEW_SHOT_EXAMPLES

    user_content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(image_bytes).decode(),
            },
        },
        {
            "type": "text",
            "text": CALL1_USER_TEMPLATE.format(
                subject_hint=subject_hint,
                grade_hint=grade_hint,
            ),
        },
    ]

    return {
        "model": settings.AI_GRADING_CALL1_MODEL,  # 由配置注入，不硬编码
        "max_tokens": 4096,
        "temperature": 0.2,
        "system": system_content,
        "messages": [{"role": "user", "content": user_content}],
    }
```

### 6.2 Call 2 请求构造

```python
def build_call2_request(
    candidates: List[KnowledgeCandidate],
    taxonomy_list: List[KnowledgePoint],
) -> dict:
    candidates_json = json.dumps(
        [{"raw_name": c.raw_name, "confidence": c.confidence} for c in candidates],
        ensure_ascii=False,
        indent=2,
    )
    taxonomy_context = build_taxonomy_context(taxonomy_list)

    user_text = CALL2_USER_TEMPLATE.format(
        knowledge_candidates_json=candidates_json,
        taxonomy_flat_list=taxonomy_context,
    )

    return {
        "model": settings.AI_GRADING_CALL2_MODEL,  # Call 2 是纯映射任务，用比 Call 1 更轻量的模型
        "max_tokens": 1024,
        "temperature": 0.0,
        "system": CALL2_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_text}],
    }
```

### 6.3 响应解析

```python
import json
from pydantic import ValidationError

def parse_call1_response(raw_text: str) -> Call1Output:
    """
    解析 Call 1 的原始文本输出。
    模型可能在 JSON 外有多余的空白或换行，使用 strip() 处理。
    如果模型意外用了 markdown 代码块，提取其中内容。
    """
    text = raw_text.strip()

    # 防御：如果模型用了 ```json ... ``` 包裹
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
        return Call1Output(**data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Call 1 返回了非法 JSON: {e}\n原始内容: {raw_text[:500]}")
    except ValidationError as e:
        raise ValueError(f"Call 1 JSON 结构不符合 schema: {e}")


def parse_call2_response(raw_text: str) -> Call2Output:
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
        return Call2Output(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"Call 2 解析失败: {e}")
```

---

## 七、不允许 AI 做的事

以下行为在 prompt 中已明确禁止，code 层也需要防御性校验：

| 行为 | 禁止原因 | 防御措施 |
|------|---------|---------|
| 输出 JSON 以外的文本 | 破坏解析 | `parse_call1_response` 的 markdown 剥离 + 解析失败重试 |
| `correct_answer` 与 `solution.answer` 不一致 | 自洽性违反 | Post-AI 检查 `answer_solution_mismatch` |
| 学生未作答时 `is_correct` 不为 null | 逻辑错误 | Post-AI 检查 `invalid_grading_without_answer` |
| 创造新的 taxonomy 知识点名称（Call 2）| 破坏 taxonomy 稳定性 | Call 2 的 unmapped_candidates 机制 |
| `knowledge_candidates` 超过 5 个 | 噪音太多 | `Call1Output.knowledge_candidates = Field(max_length=5)` |
| `score` 超出 0.0–1.0 | 无意义数值 | Post-AI 检查 `score_out_of_range` |
| 对选择题/填空题输出非 null 的 `score` | 题型不适用 | 代码层按 question_type 清零 |

---

## 八、版本迭代说明

### v1.0.1（当前版本）

- 强化 Call 1 知识点产出约束：即使学生未作答，也必须尽量输出 `knowledge_candidates`
- 强化 `solution_steps[].used_knowledge`：每个可识别步骤必须填写本步骤用到的知识点
- 不改 output schema，不改 AI 调用次数

### v1.0

- 支持学科：初二物理（`physics` + `八年级`）
- 支持题型：全部 5 类（multiple_choice / fill_blank / calculation / experiment / open_ended）
- few-shot：5 个示例（A~E，覆盖主要场景）
- Call 1 模型：多模态，质量优先，由 `settings.AI_GRADING_CALL1_MODEL` 注入
- Call 2 模型：纯文本，成本优先，由 `settings.AI_GRADING_CALL2_MODEL` 注入

### 待验证项（Phase A eval 后决定）

| 项目 | 当前决定 | eval 后可能调整 |
|------|---------|--------------|
| few-shot 数量 | 5 个 | 如果 eval 显示格式错误率 > 5%，增加到 8 个 |
| Call 1 temperature | 0.2 | 如果 eval 显示答案变动大，降至 0.1 |
| Call 2 模型选型 | 轻量级文本模型 | 如果映射准确率 < 85%，升级至更强的文本模型 |
| `max_tokens` Call 1 | 4096 | 如果实验题/计算题经常截断，升至 6144 |
| `grade_hint` 传入方式 | 自由文本 | 可改为枚举（避免"初二"和"八年级"混用） |

### Prompt 变更规则

1. 每次修改 system prompt 或 few-shot，必须记录在本文档版本号和变更日志中
2. 修改后必须重新跑 eval，不允许在 eval 未通过的情况下上生产
3. few-shot 示例必须是真实题目，不允许捏造数据

---

*本文档由 Claude 维护 · 配套文档：`AI_GRADING_MVP.md`*
