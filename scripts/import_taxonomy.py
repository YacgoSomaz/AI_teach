#!/usr/bin/env python3
"""Import taxonomy JSON into the AI grading taxonomy table."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.config import settings
from src.models.grading import GradingTaxonomy


REQUIRED_FIELDS = {
    "id",
    "name",
    "subject",
    "grade",
    "chapter",
    "parent_id",
    "level",
    "aliases",
    "description",
    "is_active",
}


def load_taxonomy_items(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        items = json.load(f)

    if not isinstance(items, list):
        raise ValueError("taxonomy JSON must be a list")

    seen_ids: set[str] = set()
    for item in items:
        missing = REQUIRED_FIELDS - set(item)
        if missing:
            raise ValueError(f"taxonomy item missing fields: {sorted(missing)}")
        if item["id"] in seen_ids:
            raise ValueError(f"duplicate taxonomy id: {item['id']}")
        seen_ids.add(item["id"])
        if item["name"] not in item["aliases"]:
            raise ValueError(f"name must be included in aliases: {item['id']}")
    return items


def _apply_item(row: GradingTaxonomy, item: dict) -> None:
    row.name = item["name"]
    row.subject = item["subject"]
    row.grade = item["grade"]
    row.chapter = item["chapter"]
    row.parent_id = item["parent_id"]
    row.level = item["level"]
    row.aliases = item["aliases"]
    row.description = item["description"]
    row.is_active = item["is_active"]


def upsert_taxonomy_items(session, items: Iterable[dict]) -> tuple[int, int]:
    inserted = 0
    updated = 0

    for item in items:
        row = session.get(GradingTaxonomy, item["id"])
        if row is None:
            row = GradingTaxonomy(id=item["id"])
            _apply_item(row, item)
            session.add(row)
            inserted += 1
        else:
            _apply_item(row, item)
            updated += 1

    return inserted, updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Import grading taxonomy JSON.")
    parser.add_argument(
        "--taxonomy",
        default=str(ROOT / "data" / "taxonomy" / "physics_grade8.json"),
        help="Path to taxonomy JSON file",
    )
    parser.add_argument(
        "--database-url",
        default=settings.database_url,
        help="SQLAlchemy database URL. Defaults to configured DATABASE_URL.",
    )
    args = parser.parse_args()

    items = load_taxonomy_items(Path(args.taxonomy))
    database_url = args.database_url
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    engine = create_engine(database_url)
    with Session(engine) as session:
        inserted, updated = upsert_taxonomy_items(session, items)
        session.commit()

    print(f"Imported grading taxonomy: inserted={inserted}, updated={updated}")


if __name__ == "__main__":
    main()
