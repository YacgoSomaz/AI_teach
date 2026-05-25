from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "grading_20260525_ai_grading_tables.py"


def test_grading_migration_uses_reserved_prefix_and_current_head():
    assert MIGRATION.exists()
    text = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "grading_20260525"' in text
    assert 'down_revision: Union[str, Sequence[str], None] = "776f9dd8f551"' in text


def test_grading_migration_creates_only_grading_taxonomy_references():
    text = MIGRATION.read_text(encoding="utf-8")

    for table in [
        "grading_taxonomy",
        "assignment_analyses",
        "grading_results",
        "question_knowledge_points",
        "student_knowledge_events",
        "student_knowledge_points",
    ]:
        assert f'"{table}"' in text

    assert 'ForeignKey("grading_taxonomy.id")' in text
    assert 'ForeignKey("knowledge_points.id")' not in text
