"""学生追问聊天接口

POST /api/chat/{assignment_id}
- 基于已批改作业的上下文，用豆包 AI 回答学生追问
- 无 assignment_id 时（纯闲聊）也可调用，传 "general"
"""

from __future__ import annotations

import logging

import json

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
from src.models.grading import AssignmentAnalysis, GradingResult
from src.models.ocr_task import OCRTask

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

SYSTEM_PROMPT = """你是一位专业的初中物理 AI 家教老师，风格亲切、耐心，善于用生活化的比喻帮学生理解物理概念。

你的职责：
1. 根据学生上传的题目和批改结果，解答学生的追问
2. 引导学生理解错误原因，而不是直接给答案
3. 适时鼓励学生，帮助建立学习自信
4. 回复简洁，控制在 150 字以内，必要时可以适当延长

注意：
- 如果学生问与题目无关的事，简短回答后引导回学习
- 不要透露你是哪家公司的模型，只说"我是你的 AI 物理老师"
- 使用中文回复"""


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


@router.post("/{assignment_id}", response_model=ChatResponse)
async def chat_with_ai(
    assignment_id: str,
    body: ChatRequest,
    current_student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """基于作业上下文的 AI 追问接口"""

    if not body.message.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="消息不能为空",
        )

    # 构建上下文（general 时跳过）
    context_lines: list[str] = []

    if assignment_id != "general":
        try:
            from uuid import UUID
            aid_uuid = UUID(assignment_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的 assignment_id",
            )

        asgn_res = await db.execute(
            select(Assignment).where(Assignment.id == aid_uuid)
        )
        assignment = asgn_res.scalar_one_or_none()
        if not assignment or assignment.student_id != current_student_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="作业不存在",
            )

        # OCR 文本
        ocr_res = await db.execute(
            select(OCRTask)
            .where(OCRTask.assignment_id == aid_uuid)
            .order_by(OCRTask.created_at.desc())
        )
        ocr = ocr_res.scalar_one_or_none()
        if ocr and ocr.raw_text:
            context_lines.append(f"【题目原文】\n{ocr.raw_text[:800]}")

        # 批改结果
        grading_res = await db.execute(
            select(GradingResult).where(GradingResult.assignment_id == aid_uuid)
        )
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

        # AI 分析
        analysis_res = await db.execute(
            select(AssignmentAnalysis).where(AssignmentAnalysis.assignment_id == aid_uuid)
        )
        analysis = analysis_res.scalar_one_or_none()
        if analysis and analysis.detected_subject:
            context_lines.append(f"【学科/题型】{analysis.detected_subject}")

    context_block = "\n\n".join(context_lines)
    user_content = (
        f"{context_block}\n\n学生追问：{body.message.strip()}"
        if context_block
        else body.message.strip()
    )

    # 调用豆包 Seed
    try:
        settings.validate_required_for_ai()
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    payload = {
        "model": settings.doubao_seed_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 400,
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
