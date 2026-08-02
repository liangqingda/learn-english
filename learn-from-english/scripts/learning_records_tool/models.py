"""Data model helpers and validation for learning records."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any


SCHEMA_VERSION = 2
CATEGORIES = ("vocabulary", "phrases", "grammar", "usage", "errors")
STATUSES = ("learning", "familiar", "mastered")
REQUIRED_TEXT_FIELDS = ("title", "explanation", "source", "example")


class RecordError(Exception):
    """Raised when records cannot be safely read or updated."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE)
    normalized = normalized.replace("_", "-")
    return normalized.strip("-")


def record_id(category: str, canonical_key: str) -> str:
    if category not in CATEGORIES:
        raise RecordError(
            f"invalid category {category!r}; expected one of: {', '.join(CATEGORIES)}"
        )
    key = normalize_key(canonical_key)
    if not key:
        raise RecordError("canonical key must contain at least one letter or number")
    return f"{category}:{key}"


def normalize_tags(tags: list[str]) -> list[str]:
    unique: dict[str, str] = {}
    for tag in tags:
        stripped = tag.strip()
        if stripped:
            unique.setdefault(stripped.casefold(), stripped)
    return sorted(unique.values(), key=lambda value: (value.casefold(), value))


def empty_database() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "revision": 0, "records": {}}


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string or null")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def new_record(payload: dict[str, Any], *, timestamp: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RecordError("each record must be an object")
    category = str(payload.get("category", ""))
    for field in ("title", "explanation", "source"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise RecordError(f"{field} must not be empty")
    identifier = record_id(category, str(payload.get("key") or payload["title"]))
    learned_at = timestamp or now_iso()
    raw_tags = payload.get("tags", payload.get("tag", []))
    if not isinstance(raw_tags, list) or not all(isinstance(tag, str) for tag in raw_tags):
        raise RecordError("tags must be an array of strings")
    if not isinstance(payload.get("example", ""), str):
        raise RecordError("example must be a string")
    tags = normalize_tags(raw_tags)
    return {
        "id": identifier,
        "category": category,
        "status": "learning",
        "title": payload["title"].strip(),
        "explanation": payload["explanation"].strip(),
        "source": payload["source"].strip(),
        "example": payload.get("example", "").strip(),
        "tags": tags,
        "first_learned_at": learned_at,
        "last_learned_at": learned_at,
        "learned_count": 1,
        "mastery_score": 0.0,
        "review_count": 0,
        "high_score_streak": 0,
        "last_reviewed_at": None,
        "next_review_at": None,
        "lapse_count": 0,
        "mastered_at": None,
        "review_history": [],
    }


def _issue(record_id_value: str | None, field: str | None, message: str) -> dict[str, Any]:
    return {"id": record_id_value, "field": field, "message": message}


def validate_record(identifier: str, record: Any) -> list[dict[str, Any]]:
    if not isinstance(record, dict):
        return [_issue(identifier, None, "record must be an object")]

    issues: list[dict[str, Any]] = []
    category = record.get("category")
    if category not in CATEGORIES:
        issues.append(_issue(identifier, "category", "category is invalid"))
    if record.get("id") != identifier:
        issues.append(_issue(identifier, "id", "record id must match its object key"))
    if isinstance(category, str) and not identifier.startswith(f"{category}:"):
        issues.append(_issue(identifier, "id", "record id must start with its category"))
    if ":" in identifier and isinstance(category, str):
        suffix = identifier.partition(":")[2]
        try:
            if record_id(category, suffix) != identifier:
                issues.append(_issue(identifier, "id", "record id suffix is not normalized"))
        except RecordError:
            issues.append(_issue(identifier, "id", "record id is invalid"))

    if record.get("status") not in STATUSES:
        issues.append(_issue(identifier, "status", "status is invalid"))
    for field in REQUIRED_TEXT_FIELDS:
        if not isinstance(record.get(field), str):
            issues.append(_issue(identifier, field, f"{field} must be a string"))
    if not isinstance(record.get("title"), str) or not record.get("title", "").strip():
        issues.append(_issue(identifier, "title", "title must not be empty"))
    if not isinstance(record.get("explanation"), str) or not record.get(
        "explanation", ""
    ).strip():
        issues.append(_issue(identifier, "explanation", "explanation must not be empty"))

    tags = record.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        issues.append(_issue(identifier, "tags", "tags must be an array of strings"))
    elif len(tags) != len({tag.casefold() for tag in tags}):
        issues.append(_issue(identifier, "tags", "tags must not contain duplicates"))

    for field in ("learned_count", "review_count", "high_score_streak", "lapse_count"):
        value = record.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            issues.append(_issue(identifier, field, f"{field} must be a non-negative integer"))
    score = record.get("mastery_score")
    if (
        not isinstance(score, (int, float))
        or isinstance(score, bool)
        or not 0 <= float(score) <= 10
    ):
        issues.append(_issue(identifier, "mastery_score", "mastery_score must be 0 to 10"))

    timestamp_fields = (
        "first_learned_at",
        "last_learned_at",
        "last_reviewed_at",
        "next_review_at",
        "mastered_at",
    )
    parsed: dict[str, datetime | None] = {}
    for field in timestamp_fields:
        try:
            parsed[field] = parse_timestamp(record.get(field))
        except (TypeError, ValueError):
            issues.append(_issue(identifier, field, f"{field} must be an ISO timestamp with timezone"))
    if record.get("status") == "mastered" and record.get("mastered_at") is None:
        issues.append(_issue(identifier, "mastered_at", "mastered records require mastered_at"))
    if record.get("status") != "mastered" and record.get("mastered_at") is not None:
        issues.append(_issue(identifier, "mastered_at", "only mastered records may set mastered_at"))
    if parsed.get("last_reviewed_at") and parsed.get("next_review_at"):
        if parsed["next_review_at"] < parsed["last_reviewed_at"]:
            issues.append(_issue(identifier, "next_review_at", "next review cannot precede last review"))
    if parsed.get("first_learned_at") and parsed.get("last_learned_at"):
        if parsed["last_learned_at"] < parsed["first_learned_at"]:
            issues.append(_issue(identifier, "last_learned_at", "last learning cannot precede first learning"))
    if parsed.get("first_learned_at") and parsed.get("last_reviewed_at"):
        if parsed["last_reviewed_at"] < parsed["first_learned_at"]:
            issues.append(_issue(identifier, "last_reviewed_at", "last review cannot precede first learning"))
    if record.get("status") == "mastered" and score != 10:
        issues.append(_issue(identifier, "mastery_score", "mastered status requires score 10"))
    if record.get("status") == "familiar" and isinstance(score, (int, float)):
        if not 8 <= float(score) <= 10:
            issues.append(_issue(identifier, "mastery_score", "familiar status requires score 8 to 10"))
    if record.get("status") == "learning" and isinstance(score, (int, float)):
        if float(score) >= 8:
            issues.append(_issue(identifier, "mastery_score", "learning status requires score below 8"))

    history = record.get("review_history")
    if not isinstance(history, list):
        issues.append(_issue(identifier, "review_history", "review_history must be an array"))
    else:
        if isinstance(record.get("review_count"), int) and len(history) > record["review_count"]:
            issues.append(_issue(identifier, "review_count", "review_history cannot exceed review_count"))
        for index, event in enumerate(history):
            if not isinstance(event, dict):
                issues.append(_issue(identifier, "review_history", f"review event {index} must be an object"))
                continue
            if not isinstance(event.get("score"), (int, float)) or not 0 <= float(
                event.get("score", -1)
            ) <= 10:
                issues.append(_issue(identifier, "review_history", f"review event {index} has invalid score"))
            try:
                parse_timestamp(event.get("reviewed_at"))
            except (TypeError, ValueError):
                issues.append(_issue(identifier, "review_history", f"review event {index} has invalid time"))
    claim = record.get("review_claim")
    if claim is not None:
        if not isinstance(claim, dict):
            issues.append(_issue(identifier, "review_claim", "review_claim must be an object or null"))
        else:
            owner = claim.get("owner")
            if not isinstance(owner, str) or not owner.strip():
                issues.append(_issue(identifier, "review_claim", "review_claim.owner must not be empty"))
            for field in ("claimed_at", "expires_at"):
                try:
                    parse_timestamp(claim.get(field))
                except (TypeError, ValueError):
                    issues.append(
                        _issue(
                            identifier,
                            "review_claim",
                            f"review_claim.{field} must be an ISO timestamp with timezone",
                        )
                    )
    return issues


def validate_database(database: Any) -> list[dict[str, Any]]:
    if not isinstance(database, dict):
        return [_issue(None, None, "database root must be an object")]
    issues: list[dict[str, Any]] = []
    if database.get("schema_version") != SCHEMA_VERSION:
        issues.append(_issue(None, "schema_version", f"schema_version must be {SCHEMA_VERSION}"))
    revision = database.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        issues.append(_issue(None, "revision", "revision must be a non-negative integer"))
    records = database.get("records")
    if not isinstance(records, dict):
        issues.append(_issue(None, "records", "records must be an object"))
        return issues
    for identifier, record in records.items():
        if not isinstance(identifier, str):
            issues.append(_issue(None, "records", "record keys must be strings"))
            continue
        issues.extend(validate_record(identifier, record))
    return issues
