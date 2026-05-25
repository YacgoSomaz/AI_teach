import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = ROOT / "data" / "taxonomy" / "physics_grade8.json"

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


def load_taxonomy() -> list[dict]:
    with TAXONOMY_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    return data


def test_physics_grade8_taxonomy_file_exists():
    assert TAXONOMY_PATH.exists()


def test_taxonomy_has_mvp_scale_and_required_fields():
    items = load_taxonomy()

    assert 60 <= len(items) <= 100
    for item in items:
        assert REQUIRED_FIELDS <= set(item)
        assert item["id"].startswith("physics_g8_")
        assert item["subject"] == "physics"
        assert item["grade"] == "八年级"
        assert item["level"] in (1, 2, 3)
        assert isinstance(item["aliases"], list)
        assert item["name"] in item["aliases"]
        assert item["description"].strip()
        assert isinstance(item["is_active"], bool)


def test_taxonomy_ids_aliases_and_parent_links_are_consistent():
    items = load_taxonomy()
    ids = [item["id"] for item in items]

    assert len(ids) == len(set(ids))

    id_set = set(ids)
    aliases_by_id = {}
    for item in items:
        aliases = [alias.strip() for alias in item["aliases"]]
        assert len(aliases) == len(set(aliases))
        aliases_by_id[item["id"]] = aliases

        parent_id = item["parent_id"]
        if item["level"] == 1:
            assert parent_id is None
        else:
            assert parent_id in id_set
            parent = next(candidate for candidate in items if candidate["id"] == parent_id)
            assert parent["level"] == item["level"] - 1

    all_aliases = [
        (item_id, alias)
        for item_id, aliases in aliases_by_id.items()
        for alias in aliases
    ]
    alias_values = [alias for _, alias in all_aliases]
    assert len(alias_values) == len(set(alias_values))


def test_taxonomy_covers_core_grade8_physics_units():
    chapters = {item["chapter"] for item in load_taxonomy()}

    expected = {
        "机械运动",
        "声现象",
        "物态变化",
        "光现象",
        "透镜及其应用",
        "质量与密度",
        "力",
        "运动和力",
        "压强",
        "浮力",
        "功和机械能",
        "简单机械",
        "电学",
    }

    assert expected <= chapters
