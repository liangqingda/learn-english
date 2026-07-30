#!/usr/bin/env python3
"""Maintain categorized English-learning records."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any


CATEGORIES = (
    "vocabulary",
    "phrases",
    "grammar",
    "usage",
    "errors",
)
RECORDS_DIR = Path(__file__).resolve().parents[2] / "learning-records"
FAMILIAR_RECORDS_DIR = (
    Path(__file__).resolve().parents[2] / "familiar-learning-records"
)
MASTERED_RECORDS_DIR = (
    Path(__file__).resolve().parents[2] / "mastered-learning-records"
)
MASTERY_THRESHOLD = 8.0
PERFECT_SCORE = 10.0
MASTERED_SUMMARY_LIMIT = 240
ITEM_FIELD_DEFAULTS = {
    "example": "",
    "tags": [],
    "mastery_score": 0,
    "review_count": 0,
    "high_score_streak": 0,
    "last_reviewed_at": None,
}
REQUIRED_ITEM_FIELDS = (
    "id",
    "title",
    "explanation",
    "source",
    "example",
    "tags",
    "first_learned_at",
    "last_learned_at",
    "learned_count",
    "mastery_score",
    "review_count",
    "high_score_streak",
    "last_reviewed_at",
)
REQUIRED_MASTERED_ITEM_FIELDS = (
    "id",
    "title",
    "summary",
    "mastered_at",
)
REVIEW_PATHS = (
    {
        "id": "errors-grammar",
        "icon": "🧩",
        "label": "复习掌握不稳的知识点、语法和句型",
        "categories": ("errors", "grammar"),
    },
    {
        "id": "vocabulary-phrases",
        "icon": "📚",
        "label": "复习词汇、搭配和固定表达",
        "categories": ("vocabulary", "phrases"),
    },
    {
        "id": "usage",
        "icon": "🌍",
        "label": "复习语气、自然度和场景选择",
        "categories": ("usage",),
    },
)


class RecordError(Exception):
    """Raised when record data is invalid or cannot be safely updated."""


def category_path(category: str) -> Path:
    if category not in CATEGORIES:
        raise RecordError(
            f"invalid category {category!r}; expected one of: {', '.join(CATEGORIES)}"
        )
    return RECORDS_DIR / f"{category}.json"


def familiar_category_path(category: str) -> Path:
    if category not in CATEGORIES:
        raise RecordError(
            f"invalid category {category!r}; expected one of: {', '.join(CATEGORIES)}"
        )
    return FAMILIAR_RECORDS_DIR / f"{category}.json"


def mastered_category_path(category: str) -> Path:
    if category not in CATEGORIES:
        raise RecordError(
            f"invalid category {category!r}; expected one of: {', '.join(CATEGORIES)}"
        )
    return MASTERED_RECORDS_DIR / f"{category}.json"


def empty_document(category: str) -> dict[str, Any]:
    return {"category": category, "items": []}


def load_document(category: str, *, create_missing: bool = False) -> dict[str, Any]:
    path = category_path(category)
    if not path.exists():
        if create_missing:
            return empty_document(category)
        raise RecordError(f"record file does not exist: {path}")

    try:
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordError(f"cannot read valid JSON from {path}: {exc}") from exc

    if not isinstance(document, dict):
        raise RecordError(f"invalid record document in {path}: root must be an object")
    if document.get("category") != category:
        raise RecordError(f"invalid record document in {path}: category does not match")
    if not isinstance(document.get("items"), list):
        raise RecordError(f"invalid record document in {path}: items must be an array")
    return document


def normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE)
    return normalized.strip("-_")


def record_id(category: str, canonical_key: str) -> str:
    key = normalize_key(canonical_key)
    if not key:
        raise RecordError("canonical key must contain at least one letter or number")
    return f"{category}:{key}"


def write_document_to_path(path: Path, category: str, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{category}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_document(category: str, document: dict[str, Any]) -> None:
    write_document_to_path(category_path(category), category, document)


def document_path(location: str, category: str) -> Path:
    if location == "learning-records":
        return category_path(category)
    if location == "familiar-learning-records":
        return familiar_category_path(category)
    if location == "mastered-learning-records":
        return mastered_category_path(category)
    raise RecordError(f"invalid location {location!r}")


def load_document_from_location(location: str, category: str) -> dict[str, Any]:
    if location == "learning-records":
        return load_document(category, create_missing=True)
    if location == "familiar-learning-records":
        return load_familiar_document(category)
    if location == "mastered-learning-records":
        return load_mastered_document(category)
    raise RecordError(f"invalid location {location!r}")


def write_document_to_location(
    location: str, category: str, document: dict[str, Any]
) -> None:
    write_document_to_path(document_path(location, category), category, document)


def load_familiar_document(category: str) -> dict[str, Any]:
    path = familiar_category_path(category)
    if not path.exists():
        return empty_document(category)

    try:
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordError(f"cannot read valid JSON from {path}: {exc}") from exc

    if not isinstance(document, dict):
        raise RecordError(f"invalid record document in {path}: root must be an object")
    if document.get("category") != category:
        raise RecordError(f"invalid record document in {path}: category does not match")
    if not isinstance(document.get("items"), list):
        raise RecordError(f"invalid record document in {path}: items must be an array")
    return document


def load_mastered_document(category: str) -> dict[str, Any]:
    path = mastered_category_path(category)
    if not path.exists():
        return empty_document(category)

    try:
        with path.open(encoding="utf-8") as handle:
            document = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordError(f"cannot read valid JSON from {path}: {exc}") from exc

    if not isinstance(document, dict):
        raise RecordError(f"invalid record document in {path}: root must be an object")
    if document.get("category") != category:
        raise RecordError(f"invalid record document in {path}: category does not match")
    if not isinstance(document.get("items"), list):
        raise RecordError(f"invalid record document in {path}: items must be an array")
    return document


def archive_record(category: str, item: dict[str, Any]) -> None:
    document = load_familiar_document(category)
    archived = next(
        (candidate for candidate in document["items"] if candidate.get("id") == item["id"]),
        None,
    )
    if archived is None:
        document["items"].append(item)
    else:
        document["items"][document["items"].index(archived)] = item
    document["items"].sort(key=lambda value: str(value.get("id", "")))
    write_document_to_path(familiar_category_path(category), category, document)


def compact_text(value: Any, limit: int = MASTERED_SUMMARY_LIMIT) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def mastered_item(item: dict[str, Any], mastered_at: str) -> dict[str, Any]:
    summary_source = item.get("explanation") or item.get("example") or item.get("source")
    return {
        "id": item["id"],
        "title": compact_text(item.get("title")),
        "summary": compact_text(summary_source),
        "mastered_at": mastered_at,
    }


def master_record(category: str, item: dict[str, Any], mastered_at: str) -> None:
    document = load_mastered_document(category)
    concise = mastered_item(item, mastered_at)
    existing = next(
        (candidate for candidate in document["items"] if candidate.get("id") == item["id"]),
        None,
    )
    if existing is None:
        document["items"].append(concise)
    else:
        document["items"][document["items"].index(existing)] = concise
    document["items"].sort(key=lambda value: str(value.get("id", "")))
    write_document_to_path(mastered_category_path(category), category, document)


def restore_record(category: str, item: dict[str, Any]) -> None:
    document = load_document(category, create_missing=True)
    existing = next(
        (candidate for candidate in document["items"] if candidate.get("id") == item["id"]),
        None,
    )
    if existing is None:
        document["items"].append(item)
    else:
        document["items"][document["items"].index(existing)] = item
    document["items"].sort(key=lambda value: str(value.get("id", "")))
    write_document(category, document)


def complete_item_defaults(item: dict[str, Any]) -> bool:
    changed = False
    for field, default in ITEM_FIELD_DEFAULTS.items():
        if field not in item:
            item[field] = list(default) if isinstance(default, list) else default
            changed = True
    if "last_learned_at" not in item and "first_learned_at" in item:
        item["last_learned_at"] = item["first_learned_at"]
        changed = True
    if "learned_count" not in item:
        item["learned_count"] = 1
        changed = True
    return changed


def validate_item(
    location: str, category: str, item: Any, index: int
) -> list[dict[str, Any]]:
    prefix = f"{location}/{category}.json"
    item_id = item.get("id", f"<item {index}>") if isinstance(item, dict) else f"<item {index}>"
    if not isinstance(item, dict):
        return [
            {
                "location": location,
                "category": category,
                "id": item_id,
                "field": None,
                "message": f"{prefix}: item must be an object",
            }
        ]

    issues: list[dict[str, Any]] = []
    required_fields = (
        REQUIRED_MASTERED_ITEM_FIELDS
        if location == "mastered-learning-records"
        else REQUIRED_ITEM_FIELDS
    )
    for field in required_fields:
        if field not in item:
            issues.append(
                {
                    "location": location,
                    "category": category,
                    "id": item_id,
                    "field": field,
                    "message": f"{prefix}: missing required field {field!r}",
                }
            )

    if location == "mastered-learning-records":
        string_fields = ("id", "title", "summary", "mastered_at")
    else:
        string_fields = (
            "id",
            "title",
            "explanation",
            "source",
            "example",
            "first_learned_at",
            "last_learned_at",
        )
    for field in string_fields:
        if field in item and not isinstance(item[field], str):
            issues.append(
                {
                    "location": location,
                    "category": category,
                    "id": item_id,
                    "field": field,
                    "message": f"{prefix}: field {field!r} must be a string",
                }
            )

    if isinstance(item.get("id"), str) and not item["id"].startswith(f"{category}:"):
        issues.append(
            {
                "location": location,
                "category": category,
                "id": item_id,
                "field": "id",
                "message": f"{prefix}: id must start with {category!r}",
            }
        )

    if "tags" in item and not (
        isinstance(item["tags"], list)
        and all(isinstance(tag, str) for tag in item["tags"])
    ):
        issues.append(
            {
                "location": location,
                "category": category,
                "id": item_id,
                "field": "tags",
                "message": f"{prefix}: field 'tags' must be an array of strings",
            }
        )

    for field in ("learned_count", "review_count", "high_score_streak"):
        if field in item and (
            not isinstance(item[field], int) or isinstance(item[field], bool) or item[field] < 0
        ):
            issues.append(
                {
                    "location": location,
                    "category": category,
                    "id": item_id,
                    "field": field,
                    "message": f"{prefix}: field {field!r} must be a non-negative integer",
                }
            )

    if "mastery_score" in item:
        score = item["mastery_score"]
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not 0 <= float(score) <= 10
        ):
            issues.append(
                {
                    "location": location,
                    "category": category,
                    "id": item_id,
                    "field": "mastery_score",
                    "message": f"{prefix}: field 'mastery_score' must be between 0 and 10",
                }
            )

    if "last_reviewed_at" in item and item["last_reviewed_at"] is not None and not isinstance(
        item["last_reviewed_at"], str
    ):
        issues.append(
            {
                "location": location,
                "category": category,
                "id": item_id,
                "field": "last_reviewed_at",
                "message": f"{prefix}: field 'last_reviewed_at' must be a string or null",
            }
        )

    return issues


def validate_document_items(
    location: str, category: str, document: dict[str, Any]
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(document["items"]):
        issues.extend(validate_item(location, category, item, index))
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            if item["id"] in seen:
                issues.append(
                    {
                        "location": location,
                        "category": category,
                        "id": item["id"],
                        "field": "id",
                        "message": f"{location}/{category}.json: duplicate id {item['id']!r}",
                    }
                )
            seen.add(item["id"])
    return issues


def upsert(args: argparse.Namespace) -> dict[str, Any]:
    for field in ("title", "explanation", "source"):
        if not getattr(args, field).strip():
            raise RecordError(f"{field} must not be empty")

    document = load_document(args.category, create_missing=True)
    identifier = record_id(args.category, args.key or args.title)
    existing = next(
        (item for item in document["items"] if item.get("id") == identifier),
        None,
    )
    if existing is not None:
        return {
            **existing,
            "created": False,
            "location": "learning-records",
        }

    familiar_document = load_familiar_document(args.category)
    familiar = next(
        (item for item in familiar_document["items"] if item.get("id") == identifier),
        None,
    )
    if familiar is not None:
        return {
            **familiar,
            "created": False,
            "location": "familiar-learning-records",
        }

    mastered_document = load_mastered_document(args.category)
    mastered = next(
        (item for item in mastered_document["items"] if item.get("id") == identifier),
        None,
    )
    if mastered is not None:
        return {
            **mastered,
            "created": False,
            "location": "mastered-learning-records",
        }

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    tags = sorted(
        {tag.strip() for tag in args.tag if tag.strip()},
        key=lambda value: (value.casefold(), value),
    )
    item = {
        "id": identifier,
        "title": args.title.strip(),
        "explanation": args.explanation.strip(),
        "source": args.source.strip(),
        "example": args.example.strip(),
        "tags": tags,
        "first_learned_at": now,
        "last_learned_at": now,
        "learned_count": 1,
        "mastery_score": 0,
        "review_count": 0,
        "high_score_streak": 0,
        "last_reviewed_at": None,
    }
    document["items"].append(item)

    document["items"].sort(key=lambda value: str(value.get("id", "")))
    write_document(args.category, document)
    return {
        **item,
        "created": True,
        "location": "learning-records",
    }


def review_record(args: argparse.Namespace) -> dict[str, Any]:
    if not 0 <= args.score <= 10:
        raise RecordError("score must be between 0 and 10")

    document = load_document(args.category)
    identifier = record_id(args.category, args.key)
    existing = next((item for item in document["items"] if item.get("id") == identifier), None)
    if existing is None:
        raise RecordError(f"record does not exist: {identifier}")

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    streak = (
        int(existing.get("high_score_streak", 0)) + 1
        if args.score >= MASTERY_THRESHOLD
        else 0
    )
    review_count = int(existing.get("review_count", 0)) + 1

    existing["mastery_score"] = args.score
    existing["review_count"] = review_count
    existing["high_score_streak"] = streak
    existing["last_reviewed_at"] = now

    if args.score == PERFECT_SCORE:
        master_record(args.category, existing, now)
        document["items"].remove(existing)
        write_document(args.category, document)
        return {
            **existing,
            "archived": False,
            "deleted": False,
            "mastered": True,
        }

    if args.score >= MASTERY_THRESHOLD:
        archive_record(args.category, existing)
        document["items"].remove(existing)
        write_document(args.category, document)
        return {
            **existing,
            "archived": True,
            "deleted": False,
            "mastered": False,
        }

    write_document(args.category, document)
    return {**existing, "archived": False, "deleted": False, "mastered": False}


def mastery_sort_key(item: dict[str, Any]) -> tuple[float, str, str]:
    return (
        float(item.get("mastery_score", 0)),
        str(item.get("last_reviewed_at") or ""),
        str(item.get("id", "")),
    )


def list_records(args: argparse.Namespace) -> list[dict[str, Any]]:
    return sorted(load_document(args.category)["items"], key=mastery_sort_key)


def familiar_review_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return (
        str(item.get("last_reviewed_at") or ""),
        str(item.get("id", "")),
    )


def list_familiar_records(_args: argparse.Namespace) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for category in CATEGORIES:
        items.extend(
            {"category": category, **item}
            for item in load_familiar_document(category)["items"]
        )
    return sorted(items, key=familiar_review_sort_key)


def mastered_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    return (
        str(item.get("mastered_at") or ""),
        str(item.get("id", "")),
    )


def list_mastered_records(_args: argparse.Namespace) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for category in CATEGORIES:
        items.extend(
            {"category": category, "location": "mastered-learning-records", **item}
            for item in load_mastered_document(category)["items"]
        )
    return sorted(items, key=mastered_sort_key)


def review_familiar_record(args: argparse.Namespace) -> dict[str, Any]:
    if not 0 <= args.score <= 10:
        raise RecordError("score must be between 0 and 10")

    document = load_familiar_document(args.category)
    identifier = record_id(args.category, args.key)
    existing = next((item for item in document["items"] if item.get("id") == identifier), None)
    if existing is None:
        raise RecordError(f"familiar record does not exist: {identifier}")

    existing["mastery_score"] = args.score
    existing["review_count"] = int(existing.get("review_count", 0)) + 1
    existing["last_reviewed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    if args.score == PERFECT_SCORE:
        master_record(args.category, existing, existing["last_reviewed_at"])
        document["items"].remove(existing)
        write_document_to_path(familiar_category_path(args.category), args.category, document)
        return {
            **existing,
            "moved_to_learning_records": False,
            "deleted": False,
            "mastered": True,
        }

    if args.score < MASTERY_THRESHOLD:
        existing["high_score_streak"] = 0
        restore_record(args.category, existing)
        document["items"].remove(existing)
        write_document_to_path(familiar_category_path(args.category), args.category, document)
        return {
            **existing,
            "moved_to_learning_records": True,
            "deleted": False,
            "mastered": False,
        }

    write_document_to_path(familiar_category_path(args.category), args.category, document)
    return {
        **existing,
        "moved_to_learning_records": False,
        "deleted": False,
        "mastered": False,
    }


def search_record_document(
    location: str, category: str, document: dict[str, Any], needle: str
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for item in document["items"]:
        searchable = json.dumps(item, ensure_ascii=False).casefold()
        if needle in searchable:
            result = {"category": category, **item}
            if location != "learning-records":
                result["location"] = location
            matches.append(result)
    return matches


def search_records(args: argparse.Namespace) -> list[dict[str, Any]]:
    needle = unicodedata.normalize("NFKC", args.query).casefold().strip()
    if not needle:
        raise RecordError("query must not be empty")

    matches: list[dict[str, Any]] = []
    for category in CATEGORIES:
        matches.extend(
            search_record_document(
                "learning-records",
                category,
                load_document(category, create_missing=True),
                needle,
            )
        )
        if getattr(args, "include_familiar", False):
            matches.extend(
                search_record_document(
                    "familiar-learning-records",
                    category,
                    load_familiar_document(category),
                    needle,
                )
            )
        if getattr(args, "include_mastered", False):
            matches.extend(
                search_record_document(
                    "mastered-learning-records",
                    category,
                    load_mastered_document(category),
                    needle,
                )
            )
    return matches


def summarize_records(args: argparse.Namespace) -> list[dict[str, Any]]:
    include_familiar = getattr(args, "include_familiar", False)
    include_mastered = getattr(args, "include_mastered", False)
    summary: list[dict[str, Any]] = []
    for category in CATEGORIES:
        count = len(load_document(category, create_missing=True)["items"])
        item = {"category": category, "count": count}
        if include_familiar:
            familiar_count = len(load_familiar_document(category)["items"])
            item["familiar_count"] = familiar_count
        if include_mastered:
            mastered_count = len(load_mastered_document(category)["items"])
            item["mastered_count"] = mastered_count
        if include_familiar or include_mastered:
            item["total_count"] = (
                count
                + int(item.get("familiar_count", 0))
                + int(item.get("mastered_count", 0))
            )
        summary.append(item)
    return summary


def category_counts() -> dict[str, int]:
    return {
        category: len(load_document(category, create_missing=True)["items"])
        for category in CATEGORIES
    }


def review_path_count(path: dict[str, Any], counts: dict[str, int]) -> int:
    return sum(counts[category] for category in path["categories"])


def build_review_menu(args: argparse.Namespace) -> dict[str, Any]:
    counts = category_counts()
    regular_total = sum(counts.values())
    familiar_count = len(list_familiar_records(argparse.Namespace()))
    mastered_total = len(list_mastered_records(argparse.Namespace()))
    active_paths = [
        {
            **path,
            "categories": list(path["categories"]),
            "count": review_path_count(path, counts),
        }
        for path in REVIEW_PATHS
        if review_path_count(path, counts) > 0
    ]

    if not active_paths and familiar_count == 0 and mastered_total == 0:
        return {
            "state": "empty",
            "counts": counts,
            "regular_total": regular_total,
            "familiar_count": familiar_count,
            "mastered_total": mastered_total,
            "options": [
                {
                    "id": "status",
                    "icon": "📊",
                    "label": "查看当前学习记录状态",
                    "kind": "status",
                },
                {
                    "id": "cet-practice",
                    "icon": "🧪",
                    "label": "做一道 CET-4 仔细阅读单选题",
                    "kind": "cet-practice",
                },
                {
                    "id": "scenario-dialogue",
                    "icon": "🎭",
                    "label": "开始一段咖啡店点单的场景对话",
                    "kind": "scenario-dialogue",
                },
            ],
        }

    visible_paths = active_paths
    if len(visible_paths) > 1:
        merged_paths = sorted(visible_paths, key=lambda path: (path["count"], path["id"]))
        merged = merged_paths[0]
        merged_categories: list[str] = []
        for path in merged_paths:
            merged_categories.extend(path["categories"])
        visible_paths = [
            {
                "id": f"mixed-{merged_paths[0]['id']}-{merged_paths[1]['id']}",
                "icon": merged["icon"],
                "label": "综合复习低分知识点",
                "categories": merged_categories,
                "count": sum(path["count"] for path in merged_paths),
                "merged_from": [path["id"] for path in merged_paths],
            }
        ]

    options: list[dict[str, Any]] = [
        {**path, "kind": "review-path"} for path in visible_paths
    ]
    options.extend(
        [
            {
                "id": "cet-practice",
                "icon": "🧪",
                "label": "做一道基于学习记录的四六级规格纯文本习题",
                "kind": "cet-practice",
            },
            {
                "id": "mastered-cet-paper",
                "icon": "📝",
                "label": "生成一套基于已掌握知识点的完整四六级套题（不含听力）",
                "kind": "mastered-cet-paper",
                "count": mastered_total,
            },
            {
                "id": "scenario-dialogue",
                "icon": "🎭",
                "label": "用学过的英语开展一个真实场景对话",
                "kind": "scenario-dialogue",
            },
            {
                "id": "familiar-review",
                "icon": "🔁",
                "label": "复习已标熟的知识点",
                "kind": "familiar-review",
                "count": familiar_count,
            },
        ]
    )
    return {
        "state": "ready",
        "counts": counts,
        "regular_total": regular_total,
        "familiar_count": familiar_count,
        "mastered_total": mastered_total,
        "options": options,
    }


def next_review_record(args: argparse.Namespace) -> dict[str, Any]:
    if args.familiar:
        familiar = list_familiar_records(argparse.Namespace())
        return {"location": "familiar-learning-records", "record": familiar[0] if familiar else None}

    categories = args.category or []
    if args.path:
        selected = next((path for path in REVIEW_PATHS if path["id"] == args.path), None)
        selected_paths = [selected] if selected is not None else [
            path for path in REVIEW_PATHS if path["id"] in args.path
        ]
        if not selected_paths:
            raise RecordError(f"review path does not exist: {args.path}")
        for path in selected_paths:
            categories.extend(path["categories"])
    if not categories:
        raise RecordError("at least one --category, --path, or --familiar is required")

    candidates: list[dict[str, Any]] = []
    for category in dict.fromkeys(categories):
        candidates.extend(
            {"category": category, **item}
            for item in load_document(category, create_missing=True)["items"]
        )
    if getattr(args, "random", False):
        return {
            "location": "learning-records",
            "record": random.choice(candidates) if candidates else None,
        }
    return {
        "location": "learning-records",
        "record": sorted(candidates, key=mastery_sort_key)[0] if candidates else None,
    }


def validate_records(_args: argparse.Namespace) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for location in (
        "learning-records",
        "familiar-learning-records",
        "mastered-learning-records",
    ):
        for category in CATEGORIES:
            document = load_document_from_location(location, category)
            issues.extend(validate_document_items(location, category, document))
    return {"valid": not issues, "issue_count": len(issues), "issues": issues}


def migrate_records(args: argparse.Namespace) -> dict[str, Any]:
    migrated: list[dict[str, Any]] = []
    for location in ("learning-records", "familiar-learning-records"):
        for category in CATEGORIES:
            document = load_document_from_location(location, category)
            changed_ids: list[str] = []
            for item in document["items"]:
                if isinstance(item, dict) and complete_item_defaults(item):
                    changed_ids.append(str(item.get("id", "")))
            if changed_ids:
                document["items"].sort(key=lambda value: str(value.get("id", "")))
                if not args.dry_run:
                    write_document_to_location(location, category, document)
                migrated.append(
                    {
                        "location": location,
                        "category": category,
                        "count": len(changed_ids),
                        "ids": changed_ids,
                    }
                )
    return {"dry_run": args.dry_run, "changed": migrated}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    upsert_parser = subparsers.add_parser(
        "upsert", help="add one record, skipping an existing canonical key"
    )
    upsert_parser.add_argument("--category", required=True, choices=CATEGORIES)
    upsert_parser.add_argument("--key", help="canonical semantic key used to deduplicate")
    upsert_parser.add_argument("--title", required=True)
    upsert_parser.add_argument("--explanation", required=True)
    upsert_parser.add_argument("--source", required=True)
    upsert_parser.add_argument("--example", default="")
    upsert_parser.add_argument("--tag", action="append", default=[])
    upsert_parser.set_defaults(handler=upsert)

    list_parser = subparsers.add_parser("list", help="list one category")
    list_parser.add_argument("--category", required=True, choices=CATEGORIES)
    list_parser.set_defaults(handler=list_records)

    familiar_list_parser = subparsers.add_parser(
        "familiar-list", help="list familiar records from oldest review time first"
    )
    familiar_list_parser.set_defaults(handler=list_familiar_records)

    mastered_list_parser = subparsers.add_parser(
        "mastered-list", help="list mastered records from oldest mastered time first"
    )
    mastered_list_parser.set_defaults(handler=list_mastered_records)

    review_parser = subparsers.add_parser(
        "review", help="record a 0-10 review score and archive perfect scores"
    )
    review_parser.add_argument("--category", required=True, choices=CATEGORIES)
    review_parser.add_argument("--key", required=True, help="canonical key after the id colon")
    review_parser.add_argument("--score", required=True, type=float)
    review_parser.set_defaults(handler=review_record)

    familiar_review_parser = subparsers.add_parser(
        "familiar-review", help="score a familiar record and archive perfect scores"
    )
    familiar_review_parser.add_argument("--category", required=True, choices=CATEGORIES)
    familiar_review_parser.add_argument(
        "--key", required=True, help="canonical key after the id colon"
    )
    familiar_review_parser.add_argument("--score", required=True, type=float)
    familiar_review_parser.set_defaults(handler=review_familiar_record)

    search_parser = subparsers.add_parser("search", help="search all categories")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument(
        "--include-familiar",
        action="store_true",
        help="also search familiar records",
    )
    search_parser.add_argument(
        "--include-mastered",
        action="store_true",
        help="also search mastered records",
    )
    search_parser.set_defaults(handler=search_records)

    summary_parser = subparsers.add_parser(
        "summary", help="show the number of records in every category"
    )
    summary_parser.add_argument(
        "--include-familiar",
        action="store_true",
        help="also include familiar record counts",
    )
    summary_parser.add_argument(
        "--include-mastered",
        action="store_true",
        help="also include mastered record counts",
    )
    summary_parser.set_defaults(handler=summarize_records)

    menu_parser = subparsers.add_parser(
        "menu", help="build a bounded review menu from current record counts"
    )
    menu_parser.set_defaults(handler=build_review_menu)

    next_parser = subparsers.add_parser(
        "next-review", help="select the next review record from categories or a path"
    )
    next_parser.add_argument("--category", action="append", choices=CATEGORIES, default=[])
    next_parser.add_argument(
        "--path",
        help="review path id from the menu command, including merged path ids",
    )
    next_parser.add_argument(
        "--familiar",
        action="store_true",
        help="select from familiar records by oldest review time",
    )
    next_parser.add_argument(
        "--random",
        action="store_true",
        help="select a random record from the requested learning-records scope",
    )
    next_parser.set_defaults(handler=next_review_record)

    validate_parser = subparsers.add_parser(
        "validate", help="check all record files for item-level schema issues"
    )
    validate_parser.set_defaults(handler=validate_records)

    migrate_parser = subparsers.add_parser(
        "migrate", help="fill missing optional tracking fields in old records"
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show records that would change without writing files",
    )
    migrate_parser.set_defaults(handler=migrate_records)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except RecordError as exc:
        parser.error(str(exc))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
