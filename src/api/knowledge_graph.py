"""Knowledge graph API.

GET  /api/knowledge-graph/graph          – student graph (nodes + edges)
GET  /api/knowledge-graph/curriculum     – all active taxonomy nodes for a subject
POST /api/knowledge-graph/relations      – bulk upsert curriculum edges (admin)
GET  /api/knowledge-graph/report         – get or generate student report
POST /api/knowledge-graph/report/refresh – force-regenerate report
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_student_id
from src.db.session import get_db
from src.models.grading import GradingTaxonomy
from src.services.knowledge_graph_service import (
    get_or_generate_report,
    get_student_graph,
    upsert_relations,
    vectorize_curriculum,
)

router = APIRouter(prefix="/api/knowledge-graph", tags=["knowledge-graph"])


# ── Response models ───────────────────────────────────────────────────────────


class GraphNodeOut(BaseModel):
    id: str
    name: str
    chapter: str
    subject: str
    grade: str
    level: int
    mastery: Optional[float]
    attempts: int
    correct_count: int
    last_seen: Optional[datetime]
    status: str


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    relation_type: str


class StudentGraphResponse(BaseModel):
    student_id: str
    subject: str
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    stats: dict


class TaxonomyNodeOut(BaseModel):
    id: str
    name: str
    subject: str
    grade: str
    chapter: str
    level: int
    parent_id: Optional[str]
    description: Optional[str]


class RelationIn(BaseModel):
    source_id: str
    target_id: str
    relation_type: str = "direct"


class UpsertRelationsRequest(BaseModel):
    relations: list[RelationIn]


class ReportResponse(BaseModel):
    student_id: str
    subject: str
    content: str
    generated_at: datetime
    expires_at: datetime
    meta: dict


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/graph", response_model=StudentGraphResponse)
async def get_graph(
    subject: str = "物理",
    student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> StudentGraphResponse:
    """Return the student's knowledge graph for the requested subject."""
    graph = await get_student_graph(student_id, subject, db)

    strong = sum(1 for n in graph.nodes if n.status == "strong")
    weak = sum(1 for n in graph.nodes if n.status == "weak")
    total = len(graph.nodes)
    seen = [n for n in graph.nodes if n.mastery is not None]
    overall = round(sum(n.mastery for n in seen) / len(seen), 3) if seen else 0.0

    return StudentGraphResponse(
        student_id=student_id,
        subject=subject,
        nodes=[GraphNodeOut(**n.__dict__) for n in graph.nodes],
        edges=[GraphEdgeOut(**e.__dict__) for e in graph.edges],
        stats={
            "total": total,
            "strong_count": strong,
            "weak_count": weak,
            "overall_mastery": overall,
        },
    )


@router.get("/curriculum", response_model=list[TaxonomyNodeOut])
async def get_curriculum(
    subject: str = "物理",
    grade: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> list[TaxonomyNodeOut]:
    """Return all active taxonomy nodes for a subject (no student data)."""
    stmt = select(GradingTaxonomy).where(
        GradingTaxonomy.subject == subject,
        GradingTaxonomy.is_active.is_(True),
    )
    if grade:
        stmt = stmt.where(GradingTaxonomy.grade == grade)
    rows = (await db.execute(stmt)).scalars().all()

    return [
        TaxonomyNodeOut(
            id=r.id,
            name=r.name,
            subject=r.subject,
            grade=r.grade,
            chapter=r.chapter,
            level=r.level,
            parent_id=r.parent_id,
            description=r.description,
        )
        for r in rows
    ]


@router.post("/relations", status_code=status.HTTP_201_CREATED)
async def add_relations(
    body: UpsertRelationsRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bulk upsert curriculum knowledge-point relations."""
    relations = [r.model_dump() for r in body.relations]

    # Validate that all IDs exist in taxonomy
    all_ids = {r["source_id"] for r in relations} | {r["target_id"] for r in relations}
    existing = (
        await db.execute(
            select(GradingTaxonomy.id).where(GradingTaxonomy.id.in_(list(all_ids)))
        )
    ).scalars().all()
    missing = all_ids - set(existing)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown taxonomy IDs: {', '.join(sorted(missing))}",
        )

    count = await upsert_relations(relations, db)
    return {"upserted": count}


@router.get("/report", response_model=ReportResponse)
async def get_report(
    subject: str = "物理",
    student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    """Return the cached report, or generate one if cache is stale."""
    data = await get_or_generate_report(student_id, subject, db)
    return ReportResponse(
        student_id=data.student_id,
        subject=data.subject,
        content=data.content,
        generated_at=data.generated_at,
        expires_at=data.expires_at,
        meta=data.meta,
    )


@router.post("/curriculum/vectorize")
async def vectorize(
    subject: str = "物理",
    force: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Embed all active taxonomy nodes for a subject and store vectors in DB.

    Call this once after loading curriculum data, or with force=True to refresh.
    """
    result = await vectorize_curriculum(subject, db, force=force)
    return result


@router.post("/report/refresh", response_model=ReportResponse)
async def refresh_report(
    subject: str = "物理",
    student_id: str = Depends(get_current_student_id),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    """Force-regenerate the student report ignoring cache."""
    data = await get_or_generate_report(student_id, subject, db, force=True)
    return ReportResponse(
        student_id=data.student_id,
        subject=data.subject,
        content=data.content,
        generated_at=data.generated_at,
        expires_at=data.expires_at,
        meta=data.meta,
    )
