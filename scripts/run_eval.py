#!/usr/bin/env python3
"""
Phase A eval script for the AI grading pipeline.

Runs the two-call AI grading pipeline against the golden test set and
reports metrics against the acceptance thresholds in docs/AI_GRADING_MVP.md §十一.

Usage:
    python scripts/run_eval.py
    python scripts/run_eval.py --golden-set data/golden_set/golden_set.json
    python scripts/run_eval.py --taxonomy data/taxonomy/physics_grade8.json
    python scripts/run_eval.py --output-json results/eval_20260525.json
    python scripts/run_eval.py --dry-run          # validate golden set, no AI calls
    python scripts/run_eval.py --max-cases 5      # smoke test with 5 cases
    python scripts/run_eval.py --no-few-shot      # ablation: disable few-shot examples

Environment variables (required for real AI calls):
    DOUBAO_SEED_API_KEY    API key for the AI provider
    DOUBAO_SEED_BASE_URL   Base URL (default: Volces endpoint)
    AI_GRADING_CALL1_MODEL Model for Call 1 (default: same as doubao_seed_model)
    AI_GRADING_CALL2_MODEL Model for Call 2 (default: same as Call 1)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ─── Resolve project root so script is runnable from any cwd ─────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.prompts.grading import (
    PROMPT_VERSION,
    build_call1_messages,
    build_call2_messages,
)
from src.schemas.ai_grading import AIGradingResult, KnowledgeMappingResult

# ─── Acceptance thresholds (from AI_GRADING_MVP.md §十一) ─────────────────────

GATE_SCHEMA_PARSE_MIN = 0.95
GATE_ANSWER_ACCURACY_MIN = 0.80
GATE_GRADING_ACCURACY_MIN = 0.80
GATE_TAXONOMY_TOP1_HIT_MIN = 0.75

# ─── Golden set schema ────────────────────────────────────────────────────────


@dataclass
class GoldenCase:
    """One annotated test case in the golden set."""

    id: str
    image_path: str
    question_type: str
    standard_answer: str
    # Optional fields
    compressed_image_path: Optional[str] = None
    student_answer: Optional[str] = None
    expected_is_correct: Optional[bool] = None
    expected_mistake_type: Optional[str] = None
    expected_taxonomy_ids: list[str] = field(default_factory=list)
    acceptable_solution_points: list[str] = field(default_factory=list)
    notes: str = ""


# ─── Per-case result ──────────────────────────────────────────────────────────


@dataclass
class CaseResult:
    case_id: str
    question_type: str
    # Schema parse
    call1_parse_ok: bool = False
    call2_parse_ok: Optional[bool] = None  # None = not attempted
    # Accuracy
    answer_match: Optional[bool] = None    # None = cannot evaluate
    grading_match: Optional[bool] = None   # None = student_answer was null
    taxonomy_hit: Optional[bool] = None    # None = not attempted / no expected IDs
    # Performance
    call1_latency_s: float = 0.0
    call2_latency_s: Optional[float] = None
    call1_input_tokens: int = 0
    call1_output_tokens: int = 0
    call2_input_tokens: Optional[int] = None
    call2_output_tokens: Optional[int] = None
    image_size_kb: float = 0.0
    # Outputs
    got_answer: Optional[str] = None
    got_is_correct: Optional[bool] = None
    got_support_status: Optional[str] = None
    got_taxonomy_ids: list[str] = field(default_factory=list)
    review_required: Optional[bool] = None
    review_reasons: list[str] = field(default_factory=list)
    error: Optional[str] = None


# ─── Metrics ─────────────────────────────────────────────────────────────────


@dataclass
class EvalMetrics:
    n_total: int = 0
    n_schema_ok: int = 0
    n_answer_evaluated: int = 0
    n_answer_correct: int = 0
    n_grading_evaluated: int = 0
    n_grading_correct: int = 0
    n_taxonomy_evaluated: int = 0
    n_taxonomy_hit: int = 0
    latencies_call1: list[float] = field(default_factory=list)
    latencies_call2: list[float] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @property
    def schema_parse_rate(self) -> float:
        return self.n_schema_ok / self.n_total if self.n_total else 0.0

    @property
    def answer_accuracy(self) -> float:
        return (
            self.n_answer_correct / self.n_answer_evaluated
            if self.n_answer_evaluated else 0.0
        )

    @property
    def grading_accuracy(self) -> float:
        return (
            self.n_grading_correct / self.n_grading_evaluated
            if self.n_grading_evaluated else 0.0
        )

    @property
    def taxonomy_top1_hit_rate(self) -> float:
        return (
            self.n_taxonomy_hit / self.n_taxonomy_evaluated
            if self.n_taxonomy_evaluated else 0.0
        )

    @property
    def p50_latency_s(self) -> float:
        return _percentile(self.latencies_call1, 50)

    @property
    def p90_latency_s(self) -> float:
        return _percentile(self.latencies_call1, 90)

    @property
    def schema_gate_pass(self) -> bool:
        return self.schema_parse_rate >= GATE_SCHEMA_PARSE_MIN

    @property
    def answer_gate_pass(self) -> bool:
        return self.n_answer_evaluated == 0 or self.answer_accuracy >= GATE_ANSWER_ACCURACY_MIN

    @property
    def grading_gate_pass(self) -> bool:
        return self.n_grading_evaluated == 0 or self.grading_accuracy >= GATE_GRADING_ACCURACY_MIN

    @property
    def taxonomy_gate_pass(self) -> bool:
        return (
            self.n_taxonomy_evaluated == 0
            or self.taxonomy_top1_hit_rate >= GATE_TAXONOMY_TOP1_HIT_MIN
        )

    @property
    def all_gates_pass(self) -> bool:
        return (
            self.schema_gate_pass
            and self.answer_gate_pass
            and self.grading_gate_pass
            and self.taxonomy_gate_pass
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _percentile(values: list[float], pct: int) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = max(0, int(len(sorted_vals) * pct / 100) - 1)
    return sorted_vals[idx]


def _normalize_answer(answer: str, question_type: str) -> str:
    """Normalize an answer string for comparison."""
    s = answer.strip()
    if question_type == "multiple_choice":
        # Extract the first uppercase letter A-D
        m = re.search(r"[A-Da-d]", s)
        return m.group(0).upper() if m else s.upper()
    # For other types: strip whitespace, collapse multiple spaces
    return re.sub(r"\s+", " ", s)


def _answers_match(got: Optional[str], expected: str, question_type: str) -> bool:
    if got is None:
        return False
    return _normalize_answer(got, question_type) == _normalize_answer(expected, question_type)


def _load_golden_set(path: Path) -> list[GoldenCase]:
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    cases = []
    for item in raw:
        cases.append(GoldenCase(**{k: item[k] for k in GoldenCase.__dataclass_fields__ if k in item}))
    return cases


def _load_taxonomy(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _load_image(case: GoldenCase, root: Path) -> bytes:
    """Load image bytes, preferring the compressed version."""
    preferred = case.compressed_image_path or case.image_path
    img_path = root / preferred
    if not img_path.exists():
        img_path = root / case.image_path
    if not img_path.exists():
        raise FileNotFoundError(f"Image not found: {case.image_path}")
    return img_path.read_bytes()


def _parse_json_response(text: str) -> dict:
    """
    Extract and parse JSON from a model response.
    Handles accidental markdown code fences.
    """
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        inner = lines[1:] if len(lines) > 2 else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        s = "\n".join(inner).strip()
    return json.loads(s)


def _make_ai_client():
    """Create an OpenAI-compatible client from environment variables."""
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: 'openai' package not installed. Run: pip install openai", file=sys.stderr)
        sys.exit(1)

    api_key = (
        os.environ.get("DOUBAO_SEED_API_KEY")
        or os.environ.get("AI_GRADING_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    if not api_key:
        print(
            "ERROR: No API key found. Set DOUBAO_SEED_API_KEY or AI_GRADING_API_KEY.",
            file=sys.stderr,
        )
        sys.exit(1)

    base_url = os.environ.get(
        "AI_GRADING_BASE_URL",
        os.environ.get(
            "DOUBAO_SEED_BASE_URL",
            "https://ark.cn-beijing.volces.com/api/v3",
        ),
    )
    return OpenAI(api_key=api_key, base_url=base_url)


def _get_model(env_key: str, fallback_key: str, default: str) -> str:
    return (
        os.environ.get(env_key)
        or os.environ.get(fallback_key)
        or default
    )


# ─── Single-case runner ───────────────────────────────────────────────────────


def run_single_case(
    case: GoldenCase,
    taxonomy: list[dict],
    client,
    call1_model: str,
    call2_model: str,
    include_few_shot: bool,
    root: Path,
    verbose: bool = False,
) -> CaseResult:
    result = CaseResult(case_id=case.id, question_type=case.question_type)

    # ── Load image ────────────────────────────────────────────────────────────
    try:
        image_bytes = _load_image(case, root)
        result.image_size_kb = len(image_bytes) / 1024
    except FileNotFoundError as e:
        result.error = str(e)
        return result

    suffix = (case.compressed_image_path or case.image_path).rsplit(".", 1)[-1].lower()
    media_type = "image/webp" if suffix == "webp" else "image/jpeg"

    # ── Call 1 ────────────────────────────────────────────────────────────────
    messages = build_call1_messages(
        image_bytes=image_bytes,
        subject_hint="物理",
        grade_hint="八年级",
        include_few_shot=include_few_shot,
        media_type=media_type,
    )

    t0 = time.monotonic()
    try:
        resp1 = client.chat.completions.create(
            model=call1_model,
            messages=messages,
            max_tokens=4096,
            temperature=0.2,
        )
        result.call1_latency_s = time.monotonic() - t0
        result.call1_input_tokens = resp1.usage.prompt_tokens if resp1.usage else 0
        result.call1_output_tokens = resp1.usage.completion_tokens if resp1.usage else 0
        raw1 = resp1.choices[0].message.content or ""
    except Exception as e:
        result.call1_latency_s = time.monotonic() - t0
        result.error = f"Call 1 API error: {e}"
        return result

    # Parse Call 1 response
    try:
        data1 = _parse_json_response(raw1)
        grading_result = AIGradingResult(**data1)
        result.call1_parse_ok = True
    except Exception as e:
        result.error = f"Call 1 parse error: {e}\nRaw (first 300 chars): {raw1[:300]}"
        return result

    result.got_answer = grading_result.solution.answer
    result.got_is_correct = grading_result.grading.is_correct
    result.got_support_status = grading_result.support_status
    result.review_required = grading_result.review_required
    result.review_reasons = grading_result.review_reasons

    # ── Evaluate Call 1 outputs ───────────────────────────────────────────────
    result.answer_match = _answers_match(
        grading_result.solution.answer, case.standard_answer, case.question_type
    )

    if case.expected_is_correct is not None and grading_result.grading.student_answer is not None:
        result.grading_match = grading_result.grading.is_correct == case.expected_is_correct

    if verbose:
        _print_case_call1(case, result, grading_result)

    # ── Call 2 (only when supported and there are candidates) ─────────────────
    if (
        grading_result.support_status == "supported"
        and grading_result.knowledge_candidates
    ):
        messages2 = build_call2_messages(
            candidates=grading_result.knowledge_candidates,
            taxonomy_entries=taxonomy,
        )
        t2 = time.monotonic()
        try:
            resp2 = client.chat.completions.create(
                model=call2_model,
                messages=messages2,
                max_tokens=1024,
                temperature=0.0,
            )
            result.call2_latency_s = time.monotonic() - t2
            result.call2_input_tokens = resp2.usage.prompt_tokens if resp2.usage else 0
            result.call2_output_tokens = resp2.usage.completion_tokens if resp2.usage else 0
            raw2 = resp2.choices[0].message.content or ""
        except Exception as e:
            result.call2_latency_s = time.monotonic() - t2
            result.error = f"Call 2 API error: {e}"
            result.call2_parse_ok = False
            return result

        try:
            data2 = _parse_json_response(raw2)
            mapping_result = KnowledgeMappingResult(**data2)
            result.call2_parse_ok = True
        except Exception as e:
            result.error = f"Call 2 parse error: {e}\nRaw (first 300 chars): {raw2[:300]}"
            result.call2_parse_ok = False
            return result

        result.got_taxonomy_ids = [
            mp.taxonomy_id for mp in mapping_result.primary_knowledge_points
        ]

        # Taxonomy top-1 hit: is expected_taxonomy_ids[0] anywhere in the mapped list?
        if case.expected_taxonomy_ids:
            result.taxonomy_hit = case.expected_taxonomy_ids[0] in result.got_taxonomy_ids

    return result


def _print_case_call1(case: GoldenCase, result: CaseResult, gr: AIGradingResult) -> None:
    status = "✅" if result.answer_match else "❌"
    print(
        f"  [{status}] {case.id} | type={case.question_type} "
        f"| expected={case.standard_answer!r} got={result.got_answer!r} "
        f"| latency={result.call1_latency_s:.1f}s "
        f"| support={result.got_support_status} "
        f"| review={result.review_required}"
    )


# ─── Validation (dry run) ────────────────────────────────────────────────────


def validate_golden_set(cases: list[GoldenCase], root: Path) -> None:
    """Check structure without making API calls. Exits on failure."""
    errors: list[str] = []

    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        errors.append("Duplicate IDs in golden set")

    valid_types = {"multiple_choice", "fill_blank", "calculation", "experiment", "open_ended"}
    for c in cases:
        if c.question_type not in valid_types:
            errors.append(f"{c.id}: invalid question_type={c.question_type!r}")
        if not c.standard_answer.strip():
            errors.append(f"{c.id}: standard_answer is empty")
        img = root / (c.compressed_image_path or c.image_path)
        if not img.exists():
            errors.append(f"{c.id}: image not found at {img}")

    if errors:
        print("Golden set validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"Golden set validation passed: {len(cases)} cases, no errors.")


# ─── Aggregate + report ───────────────────────────────────────────────────────


def aggregate(results: list[CaseResult]) -> EvalMetrics:
    m = EvalMetrics()
    m.n_total = len(results)
    for r in results:
        if r.call1_parse_ok:
            m.n_schema_ok += 1
        if r.answer_match is not None:
            m.n_answer_evaluated += 1
            if r.answer_match:
                m.n_answer_correct += 1
        if r.grading_match is not None:
            m.n_grading_evaluated += 1
            if r.grading_match:
                m.n_grading_correct += 1
        if r.taxonomy_hit is not None:
            m.n_taxonomy_evaluated += 1
            if r.taxonomy_hit:
                m.n_taxonomy_hit += 1
        if r.call1_latency_s > 0:
            m.latencies_call1.append(r.call1_latency_s)
        if r.call2_latency_s is not None:
            m.latencies_call2.append(r.call2_latency_s)
        m.total_input_tokens += r.call1_input_tokens + (r.call2_input_tokens or 0)
        m.total_output_tokens += r.call1_output_tokens + (r.call2_output_tokens or 0)
    return m


def print_report(metrics: EvalMetrics, results: list[CaseResult]) -> None:
    passed = lambda ok: "✅ PASS" if ok else "❌ FAIL"

    print("\n" + "=" * 70)
    print("EVAL REPORT — AI Grading Pipeline")
    print(f"Prompt version: {PROMPT_VERSION}  |  Cases: {metrics.n_total}")
    print("=" * 70)

    print("\n── Functional Gates (must all pass to ship) ──")
    print(
        f"  schema_parse_success  : "
        f"{metrics.schema_parse_rate:.1%}  "
        f"(min {GATE_SCHEMA_PARSE_MIN:.0%})  "
        f"{passed(metrics.schema_gate_pass)}"
    )
    print(
        f"  answer_accuracy       : "
        f"{metrics.answer_accuracy:.1%}  "
        f"({metrics.n_answer_correct}/{metrics.n_answer_evaluated})  "
        f"(min {GATE_ANSWER_ACCURACY_MIN:.0%})  "
        f"{passed(metrics.answer_gate_pass)}"
    )
    print(
        f"  grading_accuracy      : "
        f"{metrics.grading_accuracy:.1%}  "
        f"({metrics.n_grading_correct}/{metrics.n_grading_evaluated})  "
        f"(min {GATE_GRADING_ACCURACY_MIN:.0%})  "
        f"{passed(metrics.grading_gate_pass)}"
    )
    print(
        f"  taxonomy_top1_hit     : "
        f"{metrics.taxonomy_top1_hit_rate:.1%}  "
        f"({metrics.n_taxonomy_hit}/{metrics.n_taxonomy_evaluated})  "
        f"(min {GATE_TAXONOMY_TOP1_HIT_MIN:.0%})  "
        f"{passed(metrics.taxonomy_gate_pass)}"
    )

    print("\n── Performance (observation only, not a gate) ──")
    print(f"  Call 1 P50 latency    : {metrics.p50_latency_s:.1f}s  (target ≤ 30s)")
    print(f"  Call 1 P90 latency    : {metrics.p90_latency_s:.1f}s")
    if metrics.latencies_call2:
        print(f"  Call 2 P50 latency    : {_percentile(metrics.latencies_call2, 50):.1f}s")
    print(f"  Total input tokens    : {metrics.total_input_tokens:,}")
    print(f"  Total output tokens   : {metrics.total_output_tokens:,}")

    # Per-case failures
    failures = [r for r in results if r.error or not r.call1_parse_ok or r.answer_match is False]
    if failures:
        print(f"\n── Failed / Flagged Cases ({len(failures)}) ──")
        for r in failures:
            tag = "ERR" if r.error else ("PARSE_FAIL" if not r.call1_parse_ok else "WRONG_ANS")
            detail = r.error or f"got={r.got_answer!r}"
            print(f"  [{tag}] {r.case_id} — {detail}")

    verdict = "✅ ALL GATES PASS — ready for Phase B" if metrics.all_gates_pass else \
              "❌ GATES FAILED — iterate prompt (see AI_GRADING_MVP.md §十一)"
    print(f"\n{verdict}")
    print("=" * 70 + "\n")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Eval the AI grading pipeline against the golden test set."
    )
    parser.add_argument(
        "--golden-set",
        default=str(ROOT / "data" / "golden_set" / "golden_set.json"),
        help="Path to golden_set.json",
    )
    parser.add_argument(
        "--taxonomy",
        default=str(ROOT / "data" / "taxonomy" / "physics_grade8.json"),
        help="Path to taxonomy JSON",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Write full JSON report to this path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate golden set structure only, no AI calls",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Limit to first N cases (for smoke tests)",
    )
    parser.add_argument(
        "--no-few-shot",
        action="store_true",
        help="Disable few-shot examples (ablation study)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-case details",
    )
    args = parser.parse_args()

    golden_set_path = Path(args.golden_set)
    taxonomy_path = Path(args.taxonomy)

    # ── Load and validate inputs ──────────────────────────────────────────────
    if not golden_set_path.exists():
        print(f"ERROR: golden set not found at {golden_set_path}", file=sys.stderr)
        print("Build the golden set (Phase A5) before running eval.", file=sys.stderr)
        sys.exit(1)

    if not taxonomy_path.exists():
        print(f"ERROR: taxonomy not found at {taxonomy_path}", file=sys.stderr)
        sys.exit(1)

    cases = _load_golden_set(golden_set_path)
    taxonomy = _load_taxonomy(taxonomy_path)

    if args.max_cases:
        cases = cases[: args.max_cases]

    print(f"Loaded {len(cases)} golden cases, {len(taxonomy)} taxonomy entries.")

    validate_golden_set(cases, ROOT)

    if args.dry_run:
        print("Dry run complete — no AI calls made.")
        return

    # ── Set up AI client ──────────────────────────────────────────────────────
    client = _make_ai_client()

    default_model = os.environ.get("DOUBAO_SEED_MODEL", "ep-20260518173637-nhzdp")
    call1_model = _get_model("AI_GRADING_CALL1_MODEL", "DOUBAO_SEED_MODEL", default_model)
    call2_model = _get_model("AI_GRADING_CALL2_MODEL", "DOUBAO_SEED_MODEL", default_model)
    include_few_shot = not args.no_few_shot

    print(f"Call 1 model : {call1_model}")
    print(f"Call 2 model : {call2_model}")
    print(f"Few-shot     : {'on' if include_few_shot else 'off (ablation)'}")
    print(f"Prompt ver.  : {PROMPT_VERSION}")
    print()

    # ── Run eval ──────────────────────────────────────────────────────────────
    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        print(f"[{i:02d}/{len(cases):02d}] {case.id} ...", end="" if not args.verbose else "\n")
        r = run_single_case(
            case=case,
            taxonomy=taxonomy,
            client=client,
            call1_model=call1_model,
            call2_model=call2_model,
            include_few_shot=include_few_shot,
            root=ROOT,
            verbose=args.verbose,
        )
        results.append(r)
        if not args.verbose:
            tag = "✅" if r.call1_parse_ok and r.answer_match else "❌"
            print(f" {tag}  ({r.call1_latency_s:.1f}s)")

    # ── Report ────────────────────────────────────────────────────────────────
    metrics = aggregate(results)
    print_report(metrics, results)

    # ── JSON output ───────────────────────────────────────────────────────────
    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "prompt_version": PROMPT_VERSION,
            "call1_model": call1_model,
            "call2_model": call2_model,
            "few_shot": include_few_shot,
            "n_cases": metrics.n_total,
            "metrics": {
                "schema_parse_rate": metrics.schema_parse_rate,
                "answer_accuracy": metrics.answer_accuracy,
                "grading_accuracy": metrics.grading_accuracy,
                "taxonomy_top1_hit_rate": metrics.taxonomy_top1_hit_rate,
                "p50_call1_latency_s": metrics.p50_latency_s,
                "p90_call1_latency_s": metrics.p90_latency_s,
                "total_input_tokens": metrics.total_input_tokens,
                "total_output_tokens": metrics.total_output_tokens,
            },
            "gates": {
                "schema": metrics.schema_gate_pass,
                "answer": metrics.answer_gate_pass,
                "grading": metrics.grading_gate_pass,
                "taxonomy": metrics.taxonomy_gate_pass,
                "all_pass": metrics.all_gates_pass,
            },
            "cases": [asdict(r) for r in results],
        }
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"JSON report written to {out_path}")

    sys.exit(0 if metrics.all_gates_pass else 1)


if __name__ == "__main__":
    main()
