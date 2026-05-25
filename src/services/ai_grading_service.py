"""Core service for the AI grading MVP pipeline."""

from __future__ import annotations

import json
import struct
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.grading import (
    AssignmentAnalysis,
    GradingResult as GradingResultModel,
    GradingTaxonomy,
    QuestionKnowledgePoint,
    StudentKnowledgeEvent,
    StudentKnowledgePoint,
)
from src.prompts.grading import build_call1_messages, build_call2_messages
from src.schemas.ai_grading import (
    AIGradingResult,
    KnowledgeCandidate,
    KnowledgeMappingResult,
)
from src.services.mastery_service import calc_mastery


MIN_IMAGE_BYTES = 80 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MIN_LONG_EDGE = 200
CALL1_TIMEOUT_SECONDS = 120
CALL2_TIMEOUT_SECONDS = 60


class GradingAIClient(Protocol):
    """Minimal async interface used by the grading service."""

    async def complete_json(
        self,
        *,
        messages: list[dict],
        model: str,
        timeout: int,
    ) -> dict[str, Any]:
        """Return a parsed JSON object from an AI provider."""


class OpenAICompatibleGradingClient:
    """Tiny async client for OpenAI-compatible chat completion providers."""

    def __init__(self, *, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def complete_json(
        self,
        *,
        messages: list[dict],
        model: str,
        timeout: int,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"] or "{}"
        return parse_json_response(content)


def create_default_grading_ai_client() -> GradingAIClient:
    api_key = (
        getattr(settings, "ai_grading_api_key", None)
        or getattr(settings, "doubao_seed_api_key", None)
    )
    if not api_key:
        raise ValueError("AI_GRADING_API_KEY 或 DOUBAO_SEED_API_KEY 未配置")
    base_url = (
        getattr(settings, "ai_grading_base_url", None)
        or getattr(settings, "doubao_seed_base_url", None)
    )
    return OpenAICompatibleGradingClient(api_key=api_key, base_url=base_url)


class ImagePreflightError(ValueError):
    """Raised when an image should be rejected before any AI call."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ImagePreflightResult:
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None


@dataclass(frozen=True)
class AIGradingPipelineResult:
    call1_result: AIGradingResult
    mapping_result: KnowledgeMappingResult | None
    preflight: ImagePreflightResult


class AIGradingService:
    """Run preflight, AI calls, quality checks, and optional persistence."""

    def __init__(self, ai_client: GradingAIClient):
        self.ai_client = ai_client

    def preflight_image(self, image_bytes: bytes, mime_type: str) -> ImagePreflightResult:
        """Reject clearly bad inputs before paying for model inference."""

        normalized_mime = (mime_type or "").split(";")[0].strip().lower()
        if not normalized_mime.startswith("image/"):
            raise ImagePreflightError("unsupported_file_type", "仅支持图片文件")

        size_bytes = len(image_bytes)
        if size_bytes > MAX_IMAGE_BYTES:
            raise ImagePreflightError("image_too_large", "图片超过 20MB")
        if size_bytes < MIN_IMAGE_BYTES:
            raise ImagePreflightError("image_too_small", "图片压缩后小于 80KB")

        width, height = get_image_size(image_bytes)
        if width is not None and height is not None and max(width, height) < MIN_LONG_EDGE:
            raise ImagePreflightError("image_dimension_too_small", "图片长边小于 200px")

        return ImagePreflightResult(
            mime_type=normalized_mime,
            size_bytes=size_bytes,
            width=width,
            height=height,
        )

    async def analyze_image_bytes(
        self,
        *,
        image_bytes: bytes,
        mime_type: str,
        taxonomy_entries: list[dict],
        subject_hint: str = "physics",
        grade_hint: str = "八年级",
        include_few_shot: bool = True,
    ) -> AIGradingPipelineResult:
        """Run the two-call AI pipeline without touching the database."""

        preflight = self.preflight_image(image_bytes, mime_type)
        call1_messages = build_call1_messages(
            image_bytes=image_bytes,
            subject_hint=subject_hint,
            grade_hint=grade_hint,
            include_few_shot=include_few_shot,
            media_type=preflight.mime_type,
        )
        call1_payload = await self.ai_client.complete_json(
            messages=call1_messages,
            model=getattr(settings, "ai_grading_call1_model", settings.doubao_seed_model),
            timeout=CALL1_TIMEOUT_SECONDS,
        )
        call1_result = self.apply_post_ai_checks(
            AIGradingResult.model_validate(call1_payload)
        )

        mapping_result = None
        if should_run_taxonomy_mapping(call1_result):
            call2_messages = build_call2_messages(
                candidates=call1_result.knowledge_candidates,
                taxonomy_entries=taxonomy_entries,
            )
            call2_payload = await self.ai_client.complete_json(
                messages=call2_messages,
                model=getattr(settings, "ai_grading_call2_model", settings.doubao_seed_model),
                timeout=CALL2_TIMEOUT_SECONDS,
            )
            mapping_result = KnowledgeMappingResult.model_validate(call2_payload)

        return AIGradingPipelineResult(
            call1_result=call1_result,
            mapping_result=mapping_result,
            preflight=preflight,
        )

    def apply_post_ai_checks(self, result: AIGradingResult) -> AIGradingResult:
        """Apply deterministic quality gates after Call 1."""

        checked = result.model_copy(deep=True)
        reasons = list(dict.fromkeys(checked.review_reasons))

        def flag(reason: str) -> None:
            if reason not in reasons:
                reasons.append(reason)

        if checked.solution.answer.strip() != checked.grading.correct_answer.strip():
            checked.quality_flags.answer_solution_mismatch = True
            flag("answer_solution_mismatch")

        if checked.grading.student_answer is None and checked.grading.is_correct is not None:
            checked.quality_flags.missing_student_answer = True
            flag("missing_student_answer_inconsistent")

        if checked.support_status == "uncertain":
            flag("support_status_uncertain")

        if len(checked.question_struct.stem.strip()) < 5:
            checked.quality_flags.incomplete_schema = True
            flag("stem_too_short")

        checked.review_reasons = reasons
        checked.review_required = checked.review_required or bool(reasons)
        return checked

    async def analyze_and_persist(
        self,
        *,
        db: AsyncSession,
        assignment_id: str,
        student_id: str,
        image_bytes: bytes,
        mime_type: str,
        subject_hint: str = "physics",
        grade_hint: str = "八年级",
    ) -> AIGradingPipelineResult:
        """Run the AI pipeline and persist grading data in one transaction."""

        taxonomy_entries = await load_active_taxonomy_entries(
            db,
            subject=subject_hint,
            grade=grade_hint,
        )
        pipeline_result = await self.analyze_image_bytes(
            image_bytes=image_bytes,
            mime_type=mime_type,
            taxonomy_entries=taxonomy_entries,
            subject_hint=subject_hint,
            grade_hint=grade_hint,
        )
        await persist_pipeline_result(
            db=db,
            assignment_id=assignment_id,
            student_id=student_id,
            pipeline_result=pipeline_result,
        )
        return pipeline_result


def should_run_taxonomy_mapping(result: AIGradingResult) -> bool:
    return result.support_status == "supported" and bool(result.knowledge_candidates)


def should_write_mastery_event(result: AIGradingResult) -> bool:
    grading = result.grading
    return (
        result.support_status == "supported"
        and grading.student_answer is not None
        and grading.is_correct is not None
    )


def derive_event_result(*, is_correct: bool, score: float | None) -> str:
    if is_correct:
        return "correct"
    if score is not None and 0 < score < 1:
        return "partial"
    return "wrong"


def score_for_event(result: AIGradingResult) -> Decimal:
    grading = result.grading
    if grading.score is not None:
        return Decimal(str(grading.score))
    return Decimal("1.0") if grading.is_correct else Decimal("0.0")


async def load_active_taxonomy_entries(
    db: AsyncSession,
    *,
    subject: str = "physics",
    grade: str = "八年级",
) -> list[dict]:
    result = await db.execute(
        select(GradingTaxonomy)
        .where(GradingTaxonomy.subject == subject)
        .where(GradingTaxonomy.grade == grade)
        .where(GradingTaxonomy.is_active.is_(True))
        .order_by(GradingTaxonomy.chapter, GradingTaxonomy.level, GradingTaxonomy.name)
    )
    rows = result.scalars().all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "chapter": row.chapter,
            "aliases": row.aliases or [],
            "is_active": row.is_active,
        }
        for row in rows
    ]


async def persist_pipeline_result(
    *,
    db: AsyncSession,
    assignment_id: str,
    student_id: str,
    pipeline_result: AIGradingPipelineResult,
) -> None:
    """Persist Call 1/Call 2 outputs and rebuild derived mastery aggregates."""

    assignment_uuid = uuid.UUID(str(assignment_id))
    call1 = pipeline_result.call1_result
    mapping = pipeline_result.mapping_result

    await db.execute(
        delete(QuestionKnowledgePoint).where(
            QuestionKnowledgePoint.assignment_id == assignment_uuid
        )
    )
    await db.execute(
        delete(StudentKnowledgeEvent).where(
            StudentKnowledgeEvent.assignment_id == assignment_uuid
        )
    )
    await db.execute(
        delete(GradingResultModel).where(
            GradingResultModel.assignment_id == assignment_uuid
        )
    )
    await db.execute(
        delete(AssignmentAnalysis).where(
            AssignmentAnalysis.assignment_id == assignment_uuid
        )
    )

    db.add(
        AssignmentAnalysis(
            assignment_id=assignment_uuid,
            student_id=student_id,
            detected_subject=call1.detected_subject,
            detected_grade=call1.detected_grade,
            support_status=call1.support_status,
            question_struct=call1.question_struct.model_dump(mode="json"),
            review_required=call1.review_required,
            review_reasons=call1.review_reasons,
            quality_flags=call1.quality_flags.model_dump(mode="json"),
            call1_raw=call1.model_dump(mode="json"),
        )
    )
    db.add(
        GradingResultModel(
            assignment_id=assignment_uuid,
            student_id=student_id,
            correct_answer=call1.grading.correct_answer,
            student_answer=call1.grading.student_answer,
            is_correct=call1.grading.is_correct,
            score=(
                Decimal(str(call1.grading.score))
                if call1.grading.score is not None
                else None
            ),
            max_score=Decimal("1.0"),
            mistake_type=call1.grading.mistake_type,
            mistake_reason=call1.grading.mistake_reason,
            feedback=call1.grading.feedback,
            status="ai_final",
        )
    )

    changed_knowledge_point_ids: set[str] = set()
    if mapping is not None:
        for mapped in mapping.primary_knowledge_points:
            db.add(
                QuestionKnowledgePoint(
                    assignment_id=assignment_uuid,
                    knowledge_point_id=mapped.taxonomy_id,
                    role=mapped.role,
                    confidence=Decimal(str(mapped.confidence)),
                    match_method=mapped.match_method,
                )
            )
            if should_write_mastery_event(call1):
                db.add(
                    StudentKnowledgeEvent(
                        student_id=student_id,
                        assignment_id=assignment_uuid,
                        knowledge_point_id=mapped.taxonomy_id,
                        result=derive_event_result(
                            is_correct=bool(call1.grading.is_correct),
                            score=call1.grading.score,
                        ),
                        score=score_for_event(call1),
                        max_score=Decimal("1.0"),
                        mistake_type=call1.grading.mistake_type,
                        grading_status="ai_final",
                        excluded_from_mastery=False,
                    )
                )
                changed_knowledge_point_ids.add(mapped.taxonomy_id)

    await db.flush()
    for knowledge_point_id in changed_knowledge_point_ids:
        await rebuild_student_knowledge_point(
            db,
            student_id=student_id,
            knowledge_point_id=knowledge_point_id,
        )
    await db.commit()


async def rebuild_student_knowledge_point(
    db: AsyncSession,
    *,
    student_id: str,
    knowledge_point_id: str,
) -> None:
    result = await db.execute(
        select(StudentKnowledgeEvent)
        .where(StudentKnowledgeEvent.student_id == student_id)
        .where(StudentKnowledgeEvent.knowledge_point_id == knowledge_point_id)
        .order_by(StudentKnowledgeEvent.created_at.desc())
    )
    events = result.scalars().all()
    mastery = calc_mastery(events)
    effective_events = [event for event in events if not event.excluded_from_mastery]
    correct_count = sum(1 for event in effective_events if event.result == "correct")
    last_seen = max((event.created_at for event in effective_events), default=None)

    existing_result = await db.execute(
        select(StudentKnowledgePoint)
        .where(StudentKnowledgePoint.student_id == student_id)
        .where(StudentKnowledgePoint.knowledge_point_id == knowledge_point_id)
    )
    aggregate = existing_result.scalar_one_or_none()
    if aggregate is None:
        aggregate = StudentKnowledgePoint(
            student_id=student_id,
            knowledge_point_id=knowledge_point_id,
        )
        db.add(aggregate)

    aggregate.mastery = Decimal(str(mastery)) if mastery is not None else None
    aggregate.attempts = len(effective_events)
    aggregate.correct_count = correct_count
    aggregate.last_seen = last_seen


def get_image_size(image_bytes: bytes) -> tuple[int | None, int | None]:
    """Read PNG/JPEG dimensions without pulling in heavyweight image libraries."""

    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(image_bytes) >= 24:
        width, height = struct.unpack(">II", image_bytes[16:24])
        return int(width), int(height)

    if image_bytes.startswith(b"\xff\xd8"):
        return _get_jpeg_size(image_bytes)

    return None, None


def _get_jpeg_size(image_bytes: bytes) -> tuple[int | None, int | None]:
    index = 2
    size = len(image_bytes)
    while index + 9 < size:
        if image_bytes[index] != 0xFF:
            index += 1
            continue

        marker = image_bytes[index + 1]
        index += 2
        while marker == 0xFF and index < size:
            marker = image_bytes[index]
            index += 1

        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > size:
            return None, None

        segment_length = int.from_bytes(image_bytes[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > size:
            return None, None

        if 0xC0 <= marker <= 0xC3 or 0xC5 <= marker <= 0xC7 or 0xC9 <= marker <= 0xCB or 0xCD <= marker <= 0xCF:
            if segment_length >= 7:
                height = int.from_bytes(image_bytes[index + 3 : index + 5], "big")
                width = int.from_bytes(image_bytes[index + 5 : index + 7], "big")
                return width, height

        index += segment_length

    return None, None


def parse_json_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return json.loads(stripped)


def dumps_json(data: dict[str, Any] | list[Any]) -> str:
    """Small debug helper kept local for future provider logging."""

    return json.dumps(data, ensure_ascii=False, sort_keys=True)
