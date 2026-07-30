"""Deterministic spaced-review scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def status_for_score(score: float) -> str:
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
    record["status"] = status_for_score(score)
    if score == 10 and record.get("mastered_at") is None:
        record["mastered_at"] = reviewed_at.isoformat(timespec="seconds")
    elif score < 10:
        record["mastered_at"] = None
    record["next_review_at"] = (
        reviewed_at + timedelta(days=interval_days(record, score))
    ).isoformat(timespec="seconds")


def review_priority(record: dict[str, Any], now: datetime) -> tuple[int, str, float, int, str]:
    due_at = record.get("next_review_at")
    due = due_at is None or datetime.fromisoformat(due_at) <= now
    return (
        0 if due else 1,
        str(due_at or ""),
        float(record.get("mastery_score", 0)),
        -int(record.get("lapse_count", 0)),
        str(record["id"]),
    )
