import json
from pathlib import Path

from scripts.import_taxonomy import load_taxonomy_items, upsert_taxonomy_items


class FakeSession:
    def __init__(self):
        self.rows = {}
        self.added = []

    def get(self, model, key):
        return self.rows.get(key)

    def add(self, row):
        self.rows[row.id] = row
        self.added.append(row)


def test_load_taxonomy_items_validates_required_fields(tmp_path: Path):
    path = tmp_path / "taxonomy.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "physics_g8_test",
                    "name": "测试知识点",
                    "subject": "physics",
                    "grade": "八年级",
                    "chapter": "测试章",
                    "parent_id": None,
                    "level": 1,
                    "aliases": ["测试知识点"],
                    "description": "用于测试。",
                    "is_active": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    items = load_taxonomy_items(path)

    assert items[0]["id"] == "physics_g8_test"


def test_upsert_taxonomy_items_inserts_and_updates():
    session = FakeSession()
    items = [
        {
            "id": "physics_g8_test",
            "name": "测试知识点",
            "subject": "physics",
            "grade": "八年级",
            "chapter": "测试章",
            "parent_id": None,
            "level": 1,
            "aliases": ["测试知识点"],
            "description": "第一次导入。",
            "is_active": True,
        }
    ]

    inserted, updated = upsert_taxonomy_items(session, items)

    row = session.get(None, "physics_g8_test")
    assert inserted == 1
    assert updated == 0
    assert row.description == "第一次导入。"

    items[0]["description"] = "第二次更新。"
    inserted, updated = upsert_taxonomy_items(session, items)

    row = session.get(None, "physics_g8_test")
    assert inserted == 0
    assert updated == 1
    assert row.description == "第二次更新。"
