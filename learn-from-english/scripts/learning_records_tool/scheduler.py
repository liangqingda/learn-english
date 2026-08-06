"""Deterministic spaced-review scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


REQUIRED_MASTERY_TEN_COUNT = 3


def ten_score_count(record: dict[str, Any]) -> int:
    return sum(
        1
        for event in record.get("review_history", [])
        if float(event.get("score", -1)) == 10
    )


def status_for_score(score: float, record: dict[str, Any] | None = None) -> str:
    if score == 10 and record is not None:
        if record.get("status") == "mastered":
            return "mastered"
        if ten_score_count(record) + 1 >= REQUIRED_MASTERY_TEN_COUNT:
            return "mastered"
        return "familiar"
    if score == 10:
        return "mastered"
    if score >= 8:
        return "familiar"
    return "learning"


def interval_days(record: dict[str, Any], score: float) -> int:
    if score < 5:
        return 1
    if score < 8:
        return 3
    streak = max(0, int(record.get("high_score_streak", 0)) - 1)
    if score == 10:
        return min(180, 30 * (2 ** min(streak, 2)))
    if score >= 9:
        return min(90, 14 * (2 ** min(streak, 2)))
    return min(60, 7 * (2 ** min(streak, 2)))


def schedule_review(record: dict[str, Any], score: float, reviewed_at: datetime) -> None:
    previous_status = str(record["status"])
    if score >= 8:
        record["high_score_streak"] = int(record.get("high_score_streak", 0)) + 1
    else:
        record["high_score_streak"] = 0
    if score < 8 and previous_status in {"familiar", "mastered"}:
        record["lapse_count"] = int(record.get("lapse_count", 0)) + 1
    record["status"] = status_for_score(score, record)
    if record["status"] == "mastered" and record.get("mastered_at") is None:
        record["mastered_at"] = reviewed_at.isoformat(timespec="seconds")
    elif record["status"] != "mastered":
        record["mastered_at"] = None
    record["next_review_at"] = (
        reviewed_at + timedelta(days=interval_days(record, score))
    ).isoformat(timespec="seconds")


def review_priority(record: dict[str, Any], now: datetime) -> tuple[int, float, int, float, str]:
    due_at = record.get("next_review_at")
    parsed_due = datetime.fromisoformat(due_at) if due_at is not None else None
    if parsed_due is not None and parsed_due <= now:
        queue = 0
    elif parsed_due is None:
        queue = 1
    else:
        queue = 2
    return (
        queue,
        float(record.get("mastery_score", 0)),
        -int(record.get("lapse_count", 0)),
        parsed_due.astimezone(timezone.utc).timestamp() if parsed_due is not None else 0.0,
        str(record["id"]),
    )
