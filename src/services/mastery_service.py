"""Mastery aggregation rules for the AI grading taxonomy."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Protocol


GRADING_STATUS_WEIGHT = {
    "ai_final": 1.0,
    "disputed": 0.3,
    "corrected": 1.0,
    "excluded": 0.0,
}


class MasteryEvent(Protocol):
    score: Decimal
    max_score: Decimal
    grading_status: str
    excluded_from_mastery: bool
    created_at: object


def get_event_weight(event: MasteryEvent) -> float:
    """Return the status weight for an event.

    `excluded_from_mastery` has the highest priority and always forces zero
    weight, regardless of the grading status.
    """

    if event.excluded_from_mastery:
        return 0.0
    return GRADING_STATUS_WEIGHT.get(event.grading_status, 1.0)


def calc_mastery(events: Iterable[MasteryEvent]) -> float | None:
    """Calculate mastery from recent events using geometric decay.

    Returns None until there are at least three effective events, matching the
    MVP rule that the frontend should display "数据不足" before then.
    """

    sorted_events = sorted(events, key=lambda e: e.created_at, reverse=True)
    effective_events = [event for event in sorted_events if get_event_weight(event) > 0]
    if len(effective_events) < 3:
        return None

    total_weight = 0.0
    weighted_sum = 0.0
    decay = 1.0

    for event in sorted_events:
        status_weight = get_event_weight(event)
        weight = decay * status_weight
        if weight > 0:
            score = float(event.score)
            max_score = float(event.max_score)
            ratio = score / max_score if max_score > 0 else 0.0
            weighted_sum += weight * ratio
            total_weight += weight
        decay *= 0.8

    if total_weight <= 0:
        return None

    value = Decimal(str(weighted_sum / total_weight)).quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )
    return float(value)
