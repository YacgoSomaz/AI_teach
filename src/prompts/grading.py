"""
Prompt constants for the AI grading pipeline (two-call strategy).

Maintained by Claude. See docs/PROMPT_DESIGN.md for design rationale.
Imported by:
  - scripts/run_eval.py          (Phase A eval)
  - src/services/ai_grading_service.py  (Phase B, Codex)

Whenever a prompt changes:
  1. Bump PROMPT_VERSION
  2. Re-run eval: python scripts/run_eval.py
  3. Update docs/PROMPT_DESIGN.md version history
"""

from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.schemas.ai_grading import KnowledgeCandidate

# ─── Version ─────────────────────────────────────────────────────────────────

PROMPT_VERSION = "1.0.0"

# ─── Call 1 — multimodal: understand + solve + grade ─────────────────────────

CALL1_SYSTEM = """\
你是一位初中物理/数学/化学题目的专业批改助手。

你的任务是分析学生提交的题目照片，完成以下四件事：
1. 识别题目结构（学科、年级、题型、题干、条件）
2. 给出正确解题过程和答案
3. 批改学生的作答（如有）
4. 提取本题涉及的知识点候选（自然语言，最多5个）

你必须且只能输出一个 JSON 对象，不包含任何其他文本，不使用 markdown 代码块包裹。
JSON 结构见用户消息末尾的 OUTPUT_SCHEMA。

核心约束（违反任何一条都是严重错误）：
- 如果图片模糊、题目残缺、无法确认学科，将 review_required 设为 true，\
在 review_reasons 中说明原因，但仍尽力填写其他字段
- 如果学生没有在图中写出作答，grading.student_answer 必须是 null，\
grading.is_correct 必须是 null
- grading.correct_answer 必须来自你的解题结果（solution.answer），两者必须完全一致
- score 仅在计算题、实验题、开放题中使用（0.0 到 1.0），选择题和填空题 score 为 null
- knowledge_candidates 最多 5 个，按相关性降序排列，用中文自然语言描述
- 不要捏造题目内容，如果题干文字在图片中确实无法辨认，\
在 stem 中填写"[无法识别]"并在 review_reasons 中追加 "stem_unreadable"
- solution_steps 至少包含 1 步；无法识别题目时也要给出一步说明原因的步骤\
"""

# Few-shot examples — appended to CALL1_SYSTEM when include_few_shot=True.
# Helps stabilise output format, especially for edge cases.
_CALL1_FEW_SHOT_SUFFIX = """

以下是几个示例，展示正确的 JSON 输出格式：

示例 A（选择题，有作答，答对）：
{
  "detected_subject": "physics", "detected_grade": "八年级",
  "support_status": "supported",
  "question_struct": {
    "subject": "physics", "grade": "八年级",
    "question_type": "multiple_choice",
    "stem": "在一段导线两端施加2V电压时，通过它的电流为0.4A，则该导线的电阻为",
    "options": {"A": "0.2Ω", "B": "5Ω", "C": "0.8Ω", "D": "8Ω"},
    "diagrams": [], "known_conditions": ["U = 2V", "I = 0.4A"], "target": "导线电阻 R"
  },
  "solution": {
    "answer": "B",
    "solution_steps": [{"step": 1, "title": "应用欧姆定律",
      "content": "R = U/I = 2V / 0.4A = 5Ω", "used_knowledge": ["欧姆定律"]}],
    "reasoning_summary": "直接套用 R = U/I 计算"
  },
  "grading": {
    "student_answer": "B", "correct_answer": "B",
    "is_correct": true, "score": null, "mistake_type": "correct",
    "mistake_reason": null, "feedback": null
  },
  "knowledge_candidates": [{"raw_name": "欧姆定律", "confidence": 0.98}],
  "quality_flags": {"low_payload_size": false, "missing_student_answer": false,
    "answer_solution_mismatch": false, "incomplete_schema": false},
  "review_required": false, "review_reasons": []
}

示例 B（计算题，部分正确，score=0.6）：
{
  "detected_subject": "physics", "detected_grade": "八年级",
  "support_status": "supported",
  "question_struct": {
    "subject": "physics", "grade": "八年级", "question_type": "calculation",
    "stem": "一辆汽车以72km/h的速度行驶，反应时间0.6s后刹车，刹车加速度5m/s²，求反应距离和刹车距离。",
    "options": null, "diagrams": [],
    "known_conditions": ["v₀ = 72km/h = 20m/s", "t = 0.6s", "a = -5m/s²"],
    "target": "反应距离和刹车距离"
  },
  "solution": {
    "answer": "（1）反应距离 = 12m；（2）刹车距离 = 40m",
    "solution_steps": [
      {"step": 1, "title": "单位换算", "content": "v₀ = 72÷3.6 = 20 m/s",
        "used_knowledge": ["速度单位换算"]},
      {"step": 2, "title": "计算反应距离", "content": "s₁ = v₀×t = 20×0.6 = 12m",
        "used_knowledge": ["匀速运动位移"]},
      {"step": 3, "title": "计算刹车距离",
        "content": "v²=v₀²+2as → 0=400+2×(-5)×s₂ → s₂=40m",
        "used_knowledge": ["匀减速位移公式"]}
    ],
    "reasoning_summary": "反应段匀速，刹车段匀减速，分段计算"
  },
  "grading": {
    "student_answer": "（1）12m；（2）20m",
    "correct_answer": "（1）反应距离 = 12m；（2）刹车距离 = 40m",
    "is_correct": false, "score": 0.6, "mistake_type": "calculation_error",
    "mistake_reason": "（2）中 2×5 误算为 10，导致 s₂=20m",
    "feedback": "公式选取正确，注意检查数值代入时的乘法运算"
  },
  "knowledge_candidates": [
    {"raw_name": "匀变速直线运动位移公式", "confidence": 0.95},
    {"raw_name": "速度单位换算", "confidence": 0.85}
  ],
  "quality_flags": {"low_payload_size": false, "missing_student_answer": false,
    "answer_solution_mismatch": false, "incomplete_schema": false},
  "review_required": false, "review_reasons": []
}

示例 C（学生未作答，student_answer=null）：
{
  "detected_subject": "physics", "detected_grade": "八年级",
  "support_status": "supported",
  "question_struct": {
    "subject": "physics", "grade": "八年级", "question_type": "fill_blank",
    "stem": "两灯串联，L₁阻值10Ω，L₂阻值20Ω，I₁=0.3A，则I₂=____A，总电压=____V。",
    "options": null, "diagrams": [],
    "known_conditions": ["R₁=10Ω", "R₂=20Ω", "I₁=0.3A", "串联"],
    "target": "I₂和总电压U"
  },
  "solution": {
    "answer": "I₂=0.3A；U=9V",
    "solution_steps": [
      {"step": 1, "title": "串联电流规律",
        "content": "串联电路各处电流相等，I₂=I₁=0.3A",
        "used_knowledge": ["串联电路电流规律"]},
      {"step": 2, "title": "计算总电压",
        "content": "U=I×(R₁+R₂)=0.3×30=9V",
        "used_knowledge": ["串联电路电压规律", "欧姆定律"]}
    ],
    "reasoning_summary": "串联电流处处相等，总电压等于分电压之和"
  },
  "grading": {
    "student_answer": null, "correct_answer": "I₂=0.3A；U=9V",
    "is_correct": null, "score": null, "mistake_type": "no_answer",
    "mistake_reason": null, "feedback": null
  },
  "knowledge_candidates": [
    {"raw_name": "串联电路电流规律", "confidence": 0.97},
    {"raw_name": "串联电路电压规律", "confidence": 0.92}
  ],
  "quality_flags": {"low_payload_size": false, "missing_student_answer": true,
    "answer_solution_mismatch": false, "incomplete_schema": false},
  "review_required": false, "review_reasons": []
}

示例 D（非支持学科，仍正常解题）：
{
  "detected_subject": "math", "detected_grade": "八年级",
  "support_status": "unsupported_subject",
  "question_struct": {
    "subject": "math", "grade": "八年级", "question_type": "calculation",
    "stem": "已知a+b=5，ab=6，求a²+b²",
    "options": null, "diagrams": [],
    "known_conditions": ["a+b=5", "ab=6"], "target": "a²+b²"
  },
  "solution": {
    "answer": "13",
    "solution_steps": [
      {"step": 1, "title": "利用完全平方公式",
        "content": "a²+b²=(a+b)²-2ab=25-12=13",
        "used_knowledge": ["完全平方公式"]}
    ],
    "reasoning_summary": "利用(a+b)²=a²+2ab+b²变形"
  },
  "grading": {
    "student_answer": "13", "correct_answer": "13",
    "is_correct": true, "score": null, "mistake_type": "correct",
    "mistake_reason": null, "feedback": null
  },
  "knowledge_candidates": [{"raw_name": "完全平方公式", "confidence": 0.95}],
  "quality_flags": {"low_payload_size": false, "missing_student_answer": false,
    "answer_solution_mismatch": false, "incomplete_schema": false},
  "review_required": false, "review_reasons": []
}

示例 E（图片模糊，solution_steps 给出占位步骤）：
{
  "detected_subject": "physics", "detected_grade": "uncertain",
  "support_status": "uncertain",
  "question_struct": {
    "subject": "physics", "grade": "uncertain", "question_type": "calculation",
    "stem": "[无法识别]", "options": null, "diagrams": ["图片模糊，无法识别图中内容"],
    "known_conditions": [], "target": "无法识别"
  },
  "solution": {
    "answer": "[无法解题]",
    "solution_steps": [
      {"step": 1, "title": "无法识别题目",
        "content": "图片质量不足，无法提取题干和已知条件，无法给出解题过程。",
        "used_knowledge": []}
    ],
    "reasoning_summary": "[无法解题] 图片质量不足"
  },
  "grading": {
    "student_answer": null, "correct_answer": "[无法解题]",
    "is_correct": null, "score": null, "mistake_type": null,
    "mistake_reason": null, "feedback": null
  },
  "knowledge_candidates": [],
  "quality_flags": {"low_payload_size": false, "missing_student_answer": false,
    "answer_solution_mismatch": false, "incomplete_schema": false},
  "review_required": true,
  "review_reasons": ["image_too_blurry", "stem_unreadable", "subject_uncertain"]
}\
"""

# Output schema injected into the user message (keeps system prompt stable for caching)
_CALL1_OUTPUT_SCHEMA = """\
OUTPUT_SCHEMA（你必须严格遵守此结构，字段类型和枚举值不得偏离）：

{
  "detected_subject": "string（physics/math/chemistry/biology/other）",
  "detected_grade": "string（七年级/八年级/九年级/高一/高二/未知）",
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
        "title": "string（本步骤名称）",
        "content": "string（详细过程）",
        "used_knowledge": ["string（用到的知识点）"]
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
    "mistake_reason": "string 或 null",
    "feedback": "string 或 null"
  },
  "knowledge_candidates": [
    {"raw_name": "string（中文自然语言）", "confidence": float[0.0~1.0]}
  ],
  "quality_flags": {
    "low_payload_size": false,
    "missing_student_answer": "boolean",
    "answer_solution_mismatch": false,
    "incomplete_schema": false
  },
  "review_required": "boolean",
  "review_reasons": ["string"]
}

support_status 判断规则：
- "supported"：学科是 physics，年级是 八年级
- "unsupported_subject"：学科确认为非 physics（仍解题，但标记）
- "unsupported_grade"：学科是 physics 但年级不是 八年级（仍解题，但标记）
- "uncertain"：无法判断学科或年级（尽力解题，标记）\
"""

CALL1_USER_TEMPLATE = """\
以下是本次批改的上下文信息（供参考，以图片实际内容为准）：
- 学科提示：{subject_hint}（若无则填"未知"）
- 年级提示：{grade_hint}（若无则填"未知"）

{output_schema}\
"""

# ─── Call 2 — text-only: map candidates to taxonomy ──────────────────────────

CALL2_SYSTEM = """\
你是一个知识点映射专家。

你的任务：将输入的"候选知识点"（自然语言）映射到给定的"知识点 taxonomy"中。

映射规则：
1. 只能从 taxonomy 列表中选取，不能创造新的知识点名称
2. 优先精确匹配 name 字段，其次匹配 aliases 中的任何一项
3. 匹配不到的候选知识点的名称（字符串）放入 unmapped_candidates
4. primary_knowledge_points 最多返回 3 个
5. 同一道题通常有 1-2 个主知识点（role=primary），0-2 个辅助知识点（role=secondary）
6. 不要重复返回同一个 taxonomy_id
7. confidence 反映你对映射准确性的把握（0.0-1.0）

match_method 说明：
- "exact"：候选名称与 taxonomy name 完全一致（去空格后）
- "alias"：候选名称与 taxonomy aliases 中某项完全一致
- "ai_mapped"：语义相近但非精确匹配

你必须且只能输出一个 JSON 对象，不包含任何其他文本。
输出格式：
{
  "primary_knowledge_points": [
    {
      "taxonomy_id": "string",
      "taxonomy_name": "string（taxonomy 中的 name，原样复制）",
      "confidence": float[0.0~1.0],
      "match_method": "string（枚举：exact/alias/ai_mapped）",
      "role": "string（枚举：primary/secondary）"
    }
  ],
  "unmapped_candidates": ["string"],
  "overall_confidence": float[0.0~1.0]
}\
"""

CALL2_USER_TEMPLATE = """\
题目候选知识点（来自 AI 批改，自然语言）：
{candidates_json}

可用的 taxonomy 知识点列表（id, name, aliases）：
{taxonomy_list}

请将候选知识点映射到 taxonomy，按格式输出。\
"""

# ─── Builder functions ────────────────────────────────────────────────────────


def build_call1_messages(
    image_bytes: bytes,
    subject_hint: str = "未知",
    grade_hint: str = "未知",
    include_few_shot: bool = True,
    media_type: str = "image/jpeg",
) -> list[dict]:
    """
    Build the messages list for Call 1 (multimodal).

    Compatible with the OpenAI chat completions API (and compatible providers
    such as 豆包/Volces).  The caller is responsible for choosing the model
    and setting temperature / max_tokens.
    """
    system = CALL1_SYSTEM
    if include_few_shot:
        system += _CALL1_FEW_SHOT_SUFFIX

    b64 = base64.b64encode(image_bytes).decode()
    user_text = CALL1_USER_TEMPLATE.format(
        subject_hint=subject_hint,
        grade_hint=grade_hint,
        output_schema=_CALL1_OUTPUT_SCHEMA,
    )

    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64}"},
                },
                {"type": "text", "text": user_text},
            ],
        },
    ]


def build_call2_messages(
    candidates: list["KnowledgeCandidate"],
    taxonomy_entries: list[dict],
) -> list[dict]:
    """
    Build the messages list for Call 2 (text-only taxonomy mapping).

    taxonomy_entries: list of dicts with keys id, name, aliases, chapter.
    """
    candidates_json = json.dumps(
        [{"raw_name": c.raw_name, "confidence": c.confidence} for c in candidates],
        ensure_ascii=False,
        indent=2,
    )
    taxonomy_lines = [
        f"- id: {e['id']} | name: {e['name']} | chapter: {e['chapter']} "
        f"| aliases: {'、'.join(e.get('aliases', []))}"
        for e in taxonomy_entries
        if e.get("is_active", True)
    ]
    taxonomy_list = "\n".join(taxonomy_lines)

    user_text = CALL2_USER_TEMPLATE.format(
        candidates_json=candidates_json,
        taxonomy_list=taxonomy_list,
    )
    return [
        {"role": "system", "content": CALL2_SYSTEM},
        {"role": "user", "content": user_text},
    ]
