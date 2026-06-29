"""学生追问聊天接口

POST /api/chat/{assignment_id}
- 把题目图片 + OCR 文本 + 批改结果一起传给豆包视觉模型
- 流式 SSE 输出
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from uuid import UUID

import requests
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_student_id
from src.config import settings
from src.db.session import get_db
from src.models.assignment import Assignment
from src.models.grading import AssignmentAnalysis, GradingResult, QuestionKnowledgePoint
from src.models.ocr_task import OCRTask
from src.services.knowledge_graph_service import get_rag_context, semantic_search_kp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

SYSTEM_PROMPT = """你是一位专业的初中物理 AI 家教老师，风格亲切、耐心。

你的职责：
1. 根据学生上传的题目图片和批改结果，解答学生的追问
2. 如果看到了题目图片，直接基于图片内容回答，不要说"我没看到题目"
3. 引导学生理解错误原因，而不是直接给答案
4. 回复简洁，控制在 220 字以内

【表达规则 — 必须严格遵守】
- 不要自我介绍，不要说"我是你的 AI 物理老师"
- 不要每次重复称呼学生
- 第一行直接进入题目判断或回答
- 每段 1-2 句话，最多 4 行
- 长解题过程必须分段输出，禁止把所有内容挤成一个长段落
- 每一步尽量用"先看..."、"再看..."、"所以..."这样的短句
- 如果问题是问模型身份，只回答"我是你的 AI 物理学习助手"，不要展开

【排版规则 — 必须严格遵守】
- 禁止使用任何 LaTeX 语法，包括 \\(...\\)、\\[...\\]、$...$、\\frac、\\sqrt 等
- 数学公式用纯文字写，例如：E=U+Ir、R=U/I、F=ma、v²=v₀²+2as
- 分数用斜杠表示，例如：U/R、m/s²
- 上标/下标可用 Unicode：v₀、v²、R₁、R₂、E₀
- 换行用正常段落，不要用 markdown 标题（###）或加粗（**）
- 选项 A/B/C/D 直接写出，不加括号嵌套

注意：
- 不要透露你是哪家公司的模型
- 使用中文回复"""


class ChatRequest(BaseModel):
    message: str


@router.post("/{assignment_id}")
async def chat_with_ai(
    assignment_id: str,
    body: ChatRequest,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """基于作业上下文 + 题目图片的流式 AI 追问接口"""

    if not body.message.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="消息不能为空")

    # ── 构建消息内容 ──────────────────────────────────────────
    # user_parts: 支持多模态（文字 + 图片）
    user_parts: list[dict] = []
    context_lines: list[str] = []
    image_b64: str | None = None
    image_mime: str = "image/jpeg"

    if assignment_id != "general":
        try:
            aid_uuid = UUID(assignment_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无效的 assignment_id")

        asgn_res = await db.execute(select(Assignment).where(Assignment.id == aid_uuid))
        assignment = asgn_res.scalar_one_or_none()
        if not assignment or assignment.student_id != current_student_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="作业不存在")

        # 读取原始图片 → base64
        storage_url = assignment.storage_url or ""
        file_path = storage_url.removeprefix("file://")
        if file_path and Path(file_path).is_file():
            try:
                image_bytes = Path(file_path).read_bytes()
                image_b64 = base64.b64encode(image_bytes).decode()
                image_mime = assignment.mime_type or "image/jpeg"
            except Exception as e:
                logger.warning(f"读取图片失败: {e}")

        # OCR 文本
        ocr_res = await db.execute(
            select(OCRTask).where(OCRTask.assignment_id == aid_uuid).order_by(OCRTask.created_at.desc())
        )
        ocr = ocr_res.scalar_one_or_none()
        if ocr and ocr.raw_text:
            context_lines.append(f"【OCR 识别文字】\n{ocr.raw_text[:600]}")

        # 批改结果
        grading_res = await db.execute(select(GradingResult).where(GradingResult.assignment_id == aid_uuid))
        grading = grading_res.scalar_one_or_none()
        if grading:
            parts = []
            if grading.is_correct is not None:
                parts.append(f"批改结论：{'正确' if grading.is_correct else '错误'}")
            if grading.feedback:
                parts.append(f"批改反馈：{grading.feedback}")
            if grading.mistake_reason:
                parts.append(f"错误原因：{grading.mistake_reason}")
            if grading.correct_answer:
                parts.append(f"正确答案：{grading.correct_answer}")
            if parts:
                context_lines.append("【批改结果】\n" + "\n".join(parts))

        # AI 分析结果
        analysis_res = await db.execute(
            select(AssignmentAnalysis).where(AssignmentAnalysis.assignment_id == aid_uuid)
        )
        analysis = analysis_res.scalar_one_or_none()
        if analysis and analysis.detected_subject:
            context_lines.append(f"【学科】{analysis.detected_subject}")

    # ── RAG: inject student mastery context ──────────────────────────────────
    rag_context = ""
    try:
        if assignment_id == "general":
            # No assignment: semantic vector search against curriculum KB
            rag_context = await semantic_search_kp(
                body.message, "物理", current_student_id, db
            )
        else:
            # Assignment-bound: exact KP lookup from grading result
            aid_uuid_for_rag = UUID(assignment_id)
            kp_rows = (
                await db.execute(
                    select(QuestionKnowledgePoint.knowledge_point_id)
                    .where(QuestionKnowledgePoint.assignment_id == aid_uuid_for_rag)
                    .limit(5)
                )
            ).scalars().all()
            if kp_rows:
                rag_context = await get_rag_context(current_student_id, list(kp_rows), db)
    except Exception as e:
        logger.debug(f"RAG context fetch skipped: {e}")

    # ── 组装多模态消息 ───────────────────────────────────────
    text_parts: list[str] = []
    if context_lines:
        text_parts.append("\n\n".join(context_lines))
    if rag_context:
        text_parts.append(rag_context)
    text_parts.append(f"学生追问：{body.message.strip()}")

    user_parts.append({"type": "text", "text": "\n\n".join(text_parts)})

    if image_b64:
        user_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{image_mime};base64,{image_b64}"},
        })

    # ── 调用豆包视觉模型（流式）──────────────────────────────
    try:
        settings.validate_required_for_ai()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    payload = {
        "model": settings.doubao_seed_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_parts},
        ],
        "max_tokens": 500,
        "temperature": 0.7,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {settings.doubao_seed_api_key}",
        "Content-Type": "application/json",
    }

    def generate():
        try:
            with requests.post(
                f"{settings.doubao_seed_base_url}/chat/completions",
                json=payload,
                headers=headers,
                stream=True,
                timeout=60,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    text = line.decode("utf-8") if isinstance(line, bytes) else line
                    if text.startswith("data:"):
                        text = text[5:].strip()
                    if text == "[DONE]":
                        break
                    try:
                        chunk = json.loads(text)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield f"data:{json.dumps({'t': content}, ensure_ascii=False)}\n\n"
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"聊天流式失败: {e}")
            yield f"data:{json.dumps({'err': 'AI 服务暂时不可用'}, ensure_ascii=False)}\n\n"
        yield "data:[DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
