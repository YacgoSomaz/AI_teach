from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from src.services.mastery_service import calc_mastery, get_event_weight


@dataclass
class Event:
    score: Decimal
    max_score: Decimal
    grading_status: str = "ai_final"
    excluded_from_mastery: bool = False
    created_at: datetime = datetime(2026, 5, 25, tzinfo=timezone.utc)


def event(
    score: float,
    *,
    max_score: float = 1.0,
    status: str = "ai_final",
    excluded: bool = False,
    ts: int = 0,
) -> Event:
    return Event(
        score=Decimal(str(score)),
        max_score=Decimal(str(max_score)),
        grading_status=status,
        excluded_from_mastery=excluded,
        created_at=datetime(2026, 5, 25, 9, ts, tzinfo=timezone.utc),
    )


def test_get_event_weight_uses_dispute_policy_and_exclusion_priority():
    assert get_event_weight(event(1, status="ai_final")) == 1.0
    assert get_event_weight(event(1, status="disputed")) == 0.3
    assert get_event_weight(event(1, status="corrected")) == 1.0
    assert get_event_weight(event(1, status="excluded")) == 0.0
    assert get_event_weight(event(1, status="corrected", excluded=True)) == 0.0


def test_calc_mastery_returns_none_until_three_effective_events():
    assert calc_mastery([event(1), event(0)]) is None
    assert calc_mastery([event(1), event(0), event(1, excluded=True)]) is None


def test_calc_mastery_uses_recent_first_geometric_decay():
    events = [
        event(0, ts=1),
        event(1, ts=2),
        event(1, ts=3),
    ]

    # sorted desc: 1*1.0, 1*0.8, 0*0.64 => 1.8 / 2.44
    assert calc_mastery(events) == 0.7377


def test_calc_mastery_uses_score_ratio_not_binary_only():
    events = [
        event(8, max_score=10, ts=3),
        event(4, max_score=10, ts=2),
        event(10, max_score=10, ts=1),
    ]

    # 0.8*1.0 + 0.4*0.8 + 1.0*0.64 = 1.76 / 2.44
    assert calc_mastery(events) == 0.7213


def test_calc_mastery_downweights_disputed_events():
    events = [
        event(0, status="disputed", ts=3),
        event(1, ts=2),
        event(1, ts=1),
    ]

    # 0*0.3 + 1*0.8 + 1*0.64 = 1.44 / (0.3 + 0.8 + 0.64)
    assert calc_mastery(events) == 0.8276
