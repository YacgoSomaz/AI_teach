"""Knowledge graph service.

Responsibilities:
- Build student graph: nodes from GradingTaxonomy + mastery from StudentKnowledgePoint,
  edges from CurriculumKPRelation
- Generate and cache student profile reports (StudentReport)
- Provide RAG micro-context for the chat endpoint
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
import requests
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.grading import GradingTaxonomy, StudentKnowledgePoint
from src.models.knowledge_graph import CurriculumKPRelation, StudentReport
from src.services.embedding_service import batch_embed_documents, embed_query

logger = logging.getLogger(__name__)

REPORT_TTL_DAYS = 7
REPORT_INVALIDATE_THRESHOLD = 5  # regenerate if student did ≥ N new attempts since last report

MASTERY_STRONG = 0.70
MASTERY_WEAK = 0.40


# ── DTOs ──────────────────────────────────────────────────────────────────────


@dataclass
class GraphNode:
    id: str
    name: str
    chapter: str
    subject: str
    grade: str
    level: int
    mastery: float | None
    attempts: int
    correct_count: int
    last_seen: datetime | None
    status: str  # "strong" | "medium" | "weak" | "unseen"


@dataclass
class GraphEdge:
    source: str
    target: str
    relation_type: str  # "direct" | "cross_chapter"


@dataclass
class StudentGraph:
    student_id: str
    subject: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)


@dataclass
class ReportData:
    student_id: str
    subject: str
    content: str
    generated_at: datetime
    expires_at: datetime
    meta: dict


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mastery_status(mastery: float | None) -> str:
    if mastery is None:
        return "unseen"
    if mastery >= MASTERY_STRONG:
        return "strong"
    if mastery >= MASTERY_WEAK:
        return "medium"
    return "weak"


def _call_ai(prompt: str, system: str, max_tokens: int = 600) -> str:
    """Synchronous AI call for report generation."""
    payload = {
        "model": settings.doubao_seed_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.6,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {settings.doubao_seed_api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"{settings.doubao_seed_base_url}/chat/completions",
        json=payload,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ── Graph builder ─────────────────────────────────────────────────────────────


async def get_student_graph(
    student_id: str,
    subject: str,
    db: AsyncSession,
) -> StudentGraph:
    """Return knowledge graph nodes + edges for one student + subject."""

    # All active taxonomy nodes for this subject
    tax_rows = (
        await db.execute(
            select(GradingTaxonomy).where(
                GradingTaxonomy.subject == subject,
                GradingTaxonomy.is_active.is_(True),
            )
        )
    ).scalars().all()

    if not tax_rows:
        return StudentGraph(student_id=student_id, subject=subject)

    tax_ids = [t.id for t in tax_rows]

    # Student mastery for these nodes
    skp_rows = (
        await db.execute(
            select(StudentKnowledgePoint).where(
                StudentKnowledgePoint.student_id == student_id,
                StudentKnowledgePoint.knowledge_point_id.in_(tax_ids),
            )
        )
    ).scalars().all()
    mastery_map: dict[str, StudentKnowledgePoint] = {r.knowledge_point_id: r for r in skp_rows}

    # Edges
    edge_rows = (
        await db.execute(
            select(CurriculumKPRelation).where(
                CurriculumKPRelation.source_id.in_(tax_ids),
                CurriculumKPRelation.is_active.is_(True),
            )
        )
    ).scalars().all()

    nodes: list[GraphNode] = []
    for t in tax_rows:
        skp = mastery_map.get(t.id)
        mastery_val = float(skp.mastery) if skp and skp.mastery is not None else None
        nodes.append(
            GraphNode(
                id=t.id,
                name=t.name,
                chapter=t.chapter,
                subject=t.subject,
                grade=t.grade,
                level=t.level,
                mastery=mastery_val,
                attempts=skp.attempts if skp else 0,
                correct_count=skp.correct_count if skp else 0,
                last_seen=skp.last_seen if skp else None,
                status=_mastery_status(mastery_val),
            )
        )

    edges = [
        GraphEdge(source=e.source_id, target=e.target_id, relation_type=e.relation_type)
        for e in edge_rows
    ]

    return StudentGraph(student_id=student_id, subject=subject, nodes=nodes, edges=edges)


# ── Relation management ───────────────────────────────────────────────────────


async def upsert_relations(
    relations: list[dict],
    db: AsyncSession,
) -> int:
    """Bulk upsert curriculum relations. Each dict: {source_id, target_id, relation_type}."""
    count = 0
    for rel in relations:
        existing = (
            await db.execute(
                select(CurriculumKPRelation).where(
                    CurriculumKPRelation.source_id == rel["source_id"],
                    CurriculumKPRelation.target_id == rel["target_id"],
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.relation_type = rel.get("relation_type", "direct")
            existing.is_active = True
        else:
            db.add(
                CurriculumKPRelation(
                    source_id=rel["source_id"],
                    target_id=rel["target_id"],
                    relation_type=rel.get("relation_type", "direct"),
                )
            )
        count += 1

    await db.flush()
    return count


# ── Report ────────────────────────────────────────────────────────────────────


async def get_or_generate_report(
    student_id: str,
    subject: str,
    db: AsyncSession,
    force: bool = False,
) -> ReportData:
    """Return cached report or generate a fresh one."""
    now = datetime.now(timezone.utc)

    if not force:
        cached = (
            await db.execute(
                select(StudentReport)
                .where(
                    StudentReport.student_id == student_id,
                    StudentReport.subject == subject,
                    StudentReport.expires_at > now,
                )
                .order_by(StudentReport.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if cached:
            return ReportData(
                student_id=student_id,
                subject=subject,
                content=cached.content,
                generated_at=cached.created_at,
                expires_at=cached.expires_at,
                meta=cached.meta or {},
            )

    graph = await get_student_graph(student_id, subject, db)
    content, meta = await _generate_report_content(graph)

    expires_at = now + timedelta(days=REPORT_TTL_DAYS)
    report = StudentReport(
        student_id=student_id,
        subject=subject,
        content=content,
        expires_at=expires_at,
        meta=meta,
    )
    db.add(report)
    await db.flush()

    return ReportData(
        student_id=student_id,
        subject=subject,
        content=content,
        generated_at=now,
        expires_at=expires_at,
        meta=meta,
    )


async def _generate_report_content(graph: StudentGraph) -> tuple[str, dict]:
    """Call AI to write the report. Returns (content, meta_stats)."""
    strong = [n for n in graph.nodes if n.status == "strong"]
    medium = [n for n in graph.nodes if n.status == "medium"]
    weak = [n for n in graph.nodes if n.status == "weak"]
    unseen = [n for n in graph.nodes if n.status == "unseen"]

    total = len(graph.nodes)
    overall_mastery = (
        sum(n.mastery for n in graph.nodes if n.mastery is not None) / max(total, 1)
        if total
        else 0.0
    )

    meta = {
        "total": total,
        "strong_count": len(strong),
        "medium_count": len(medium),
        "weak_count": len(weak),
        "unseen_count": len(unseen),
        "overall_mastery": round(overall_mastery, 3),
    }

    weak_names = "、".join(n.name for n in weak[:5]) or "暂无"
    strong_names = "、".join(n.name for n in strong[:5]) or "暂无"

    prompt = f"""请根据以下学生{graph.subject}学习数据，用亲切的口吻写一份简短的学习报告（200字以内）。

数据：
- 总知识点：{total} 个
- 已掌握（强）：{len(strong)} 个，包括：{strong_names}
- 进步中（中）：{len(medium)} 个
- 需加强（弱）：{len(weak)} 个，包括：{weak_names}
- 未接触：{len(unseen)} 个
- 综合掌握度：{round(overall_mastery * 100)}%

要求：
1. 第一段：总体评价，说明整体水平
2. 第二段：具体指出最需要加强的知识点，给出一句实用建议
3. 语气像老师写给家长的评语，客观温和
4. 禁止使用 markdown 格式，纯文字输出"""

    system = "你是一位初中物理教学专家，擅长用简洁清晰的语言评价学生学习状况。"

    try:
        settings.validate_required_for_ai()
        content = _call_ai(prompt, system, max_tokens=400)
    except Exception as e:
        logger.warning(f"Report AI call failed: {e}")
        content = (
            f"该学生共接触 {graph.subject} 知识点 {total} 个，"
            f"综合掌握度 {round(overall_mastery * 100)}%。"
            f"需要重点加强：{weak_names}。"
            f"已掌握：{strong_names}。"
        )

    return content, meta


# ── RAG context for chat ──────────────────────────────────────────────────────


async def get_rag_context(
    student_id: str,
    knowledge_point_ids: list[str],
    db: AsyncSession,
) -> str:
    """Return a short text block describing student mastery for given KP ids.

    Designed to be injected into the chat system prompt (≤ 80 words).
    """
    if not knowledge_point_ids:
        return ""

    skp_rows = (
        await db.execute(
            select(StudentKnowledgePoint, GradingTaxonomy)
            .join(GradingTaxonomy, StudentKnowledgePoint.knowledge_point_id == GradingTaxonomy.id)
            .where(
                StudentKnowledgePoint.student_id == student_id,
                StudentKnowledgePoint.knowledge_point_id.in_(knowledge_point_ids),
            )
        )
    ).all()

    if not skp_rows:
        return ""

    lines: list[str] = []
    for skp, tax in skp_rows:
        mastery_pct = round(float(skp.mastery) * 100) if skp.mastery else 0
        status = _mastery_status(float(skp.mastery) if skp.mastery else None)
        status_label = {"strong": "已掌握", "medium": "进步中", "weak": "需加强", "unseen": "未接触"}[status]
        lines.append(f"- {tax.name}：{status_label}（{mastery_pct}%，共做 {skp.attempts} 题）")

    return "【该学生对本题相关知识点的掌握情况】\n" + "\n".join(lines)


# ── Vectorisation ─────────────────────────────────────────────────────────────


async def vectorize_curriculum(
    subject: str,
    db: AsyncSession,
    force: bool = False,
) -> dict:
    """Embed all active taxonomy nodes for a subject and store vectors.

    Skips nodes that already have an embedding unless force=True.
    Returns {"total": N, "embedded": M, "skipped": K}.
    """
    stmt = select(GradingTaxonomy).where(
        GradingTaxonomy.subject == subject,
        GradingTaxonomy.is_active.is_(True),
    )
    if not force:
        stmt = stmt.where(GradingTaxonomy.embedding.is_(None))

    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return {"total": 0, "embedded": 0, "skipped": 0}

    # Build text representation for each node
    texts = [
        f"{r.name}。{r.description or ''}章节：{r.chapter}。学科：{r.subject}。"
        for r in rows
    ]

    vectors = batch_embed_documents(texts)

    for row, vec in zip(rows, vectors):
        await db.execute(
            sa.text(
                "UPDATE grading_taxonomy SET embedding = :vec WHERE id = :id"
            ),
            {"vec": f"[{','.join(str(x) for x in vec)}]", "id": row.id},
        )

    await db.flush()

    total_count_res = await db.execute(
        select(sa.func.count()).select_from(GradingTaxonomy).where(
            GradingTaxonomy.subject == subject,
            GradingTaxonomy.is_active.is_(True),
        )
    )
    total = total_count_res.scalar_one()

    return {"total": total, "embedded": len(rows), "skipped": total - len(rows)}


# ── Semantic search ───────────────────────────────────────────────────────────


async def semantic_search_kp(
    query: str,
    subject: str,
    student_id: str,
    db: AsyncSession,
    top_k: int = 4,
) -> str:
    """Vector-search curriculum KB for query, then fetch student mastery.

    Used for general chat (no assignment_id) to build RAG context.
    Returns a short context string for injection into the AI prompt.
    """
    try:
        vec = embed_query(query)
    except Exception as e:
        logger.warning(f"embed_query failed: {e}")
        return ""

    vec_literal = f"[{','.join(str(x) for x in vec)}]"

    # Cosine distance search (pgvector operator <=>)
    rows = (
        await db.execute(
            sa.text(
                """
                SELECT id, name, chapter
                FROM grading_taxonomy
                WHERE subject = :subject
                  AND is_active = true
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :k
                """
            ),
            {"subject": subject, "vec": vec_literal, "k": top_k},
        )
    ).all()

    if not rows:
        return ""

    kp_ids = [r.id for r in rows]
    return await get_rag_context(student_id, kp_ids, db)
