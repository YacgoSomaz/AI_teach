import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SET_PATH = ROOT / "data" / "golden_set" / "golden_set.json"
TAXONOMY_PATH = ROOT / "data" / "taxonomy" / "physics_grade8.json"

VALID_TYPES = {"multiple_choice", "fill_blank", "calculation", "experiment", "open_ended"}
REQUIRED_FIELDS = {
    "id",
    "image_path",
    "question_type",
    "standard_answer",
    "expected_taxonomy_ids",
    "acceptable_solution_points",
}


def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def test_golden_set_exists_and_has_mvp_size():
    assert GOLDEN_SET_PATH.exists()
    cases = load_json(GOLDEN_SET_PATH)
    assert 20 <= len(cases) <= 30


def test_golden_set_schema_and_images_are_valid():
    cases = load_json(GOLDEN_SET_PATH)
    taxonomy_ids = {item["id"] for item in load_json(TAXONOMY_PATH)}
    seen_ids = set()

    for case in cases:
        assert REQUIRED_FIELDS <= set(case)
        assert case["id"] not in seen_ids
        seen_ids.add(case["id"])
        assert case["question_type"] in VALID_TYPES
        assert case["standard_answer"].strip()
        assert case["expected_taxonomy_ids"]
        assert case["acceptable_solution_points"]

        image_path = ROOT / case["image_path"]
        assert image_path.exists(), case["image_path"]
        assert image_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}

        compressed = case.get("compressed_image_path")
        if compressed:
            assert (ROOT / compressed).exists(), compressed

        for taxonomy_id in case["expected_taxonomy_ids"]:
            assert taxonomy_id in taxonomy_ids


def test_golden_set_covers_required_question_types():
    counts = Counter(case["question_type"] for case in load_json(GOLDEN_SET_PATH))

    assert counts["multiple_choice"] >= 8
    assert counts["fill_blank"] >= 4
    assert counts["calculation"] >= 4
    assert counts["experiment"] >= 4
