"""Command-line interface for the versioned learning-record service."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .models import CATEGORIES, STATUSES, RecordError, record_id
from .service import RecordService
from .store import RecordStore


REPO_ROOT = Path(
    os.environ.get("LEARN_ENGLISH_REPO_ROOT", Path(__file__).resolve().parents[3])
).resolve()


def service() -> RecordService:
    return RecordService(
        RecordStore(REPO_ROOT),
        auto_commit=os.environ.get("LEARN_ENGLISH_AUTO_COMMIT", "1") != "0",
    )


def read_input(path: str) -> Any:
    try:
        if path == "-":
            return json.load(sys.stdin)
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordError(f"cannot read valid JSON input: {exc}") from exc


def payload_from_upsert(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "category": args.category,
        "key": args.key,
        "title": args.title,
        "explanation": args.explanation,
        "source": args.source,
        "example": args.example,
        "tags": args.tag,
    }


def handle_upsert(args: argparse.Namespace) -> dict[str, Any]:
    return service().upsert(payload_from_upsert(args))


def handle_batch_upsert(args: argparse.Namespace) -> dict[str, Any]:
    payload = read_input(args.input)
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise RecordError("batch input must be an array or an object containing records")
    return service().batch_upsert(records)


def handle_encounter(args: argparse.Namespace) -> dict[str, Any]:
    return service().encounter(args.id)


def handle_complete_review(args: argparse.Namespace) -> dict[str, Any]:
    payload = read_input(args.input)
    if not isinstance(payload, dict):
        raise RecordError("complete-review input must be an object")
    errors = payload.get("errors", [])
    if not isinstance(errors, list):
        raise RecordError("complete-review errors must be an array")
    try:
        score = float(payload.get("score", -1))
    except (TypeError, ValueError) as exc:
        raise RecordError("complete-review score must be a number") from exc
    return service().complete_review(str(payload.get("id", "")), score, errors)


def handle_review(args: argparse.Namespace, expected_status: str | None = None) -> dict[str, Any]:
    identifier = record_id(args.category, args.key)
    return service().complete_review(
        identifier, args.score, expected_status=expected_status
    )


def handle_list(args: argparse.Namespace) -> list[dict[str, Any]]:
    return service().list_records(category=args.category, status=args.status)


def handle_legacy_list(args: argparse.Namespace, status: str) -> list[dict[str, Any]]:
    return service().list_records(status=status)


def handle_search(args: argparse.Namespace) -> list[dict[str, Any]]:
    statuses = {"learning"}
    if args.include_familiar:
        statuses.add("familiar")
    if args.include_mastered:
        statuses.add("mastered")
    return service().search(args.query, statuses)


def handle_summary(args: argparse.Namespace) -> list[dict[str, Any]]:
    counts = service().summary()["by_status"]
    result = []
    for category in CATEGORIES:
        item = {"category": category, "count": counts["learning"][category]}
        if args.include_familiar:
            item["familiar_count"] = counts["familiar"][category]
        if args.include_mastered:
            item["mastered_count"] = counts["mastered"][category]
        if args.include_familiar or args.include_mastered:
            item["total_count"] = sum(
                int(item.get(field, 0))
                for field in ("count", "familiar_count", "mastered_count")
            )
        result.append(item)
    return result


def handle_menu(args: argparse.Namespace) -> dict[str, Any]:
    return service().menu(args.context, focus=args.focus)


def handle_next_review(args: argparse.Namespace) -> dict[str, Any]:
    status = args.status
    if args.familiar:
        status = "familiar"
    if args.mastered:
        status = "mastered"
    return service().next_review(
        categories=args.category,
        path=args.path,
        status=status,
        randomize=args.random,
        due_only=args.due_only,
    )


def parse_period(value: str) -> int:
    normalized = value.strip().casefold()
    if normalized.endswith("d"):
        normalized = normalized[:-1]
    try:
        days = int(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("period must look like 30d") from exc
    if days <= 0:
        raise argparse.ArgumentTypeError("period must be positive")
    return days


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    upsert = subparsers.add_parser("upsert", help="add or encounter one record")
    upsert.add_argument("--category", required=True, choices=CATEGORIES)
    upsert.add_argument("--key")
    upsert.add_argument("--title", required=True)
    upsert.add_argument("--explanation", required=True)
    upsert.add_argument("--source", required=True)
    upsert.add_argument("--example", default="")
    upsert.add_argument("--tag", action="append", default=[])
    upsert.set_defaults(handler=handle_upsert)

    batch = subparsers.add_parser("batch-upsert", help="atomically add multiple records")
    batch.add_argument("--input", required=True, help="JSON file path or - for stdin")
    batch.set_defaults(handler=handle_batch_upsert)

    encounter = subparsers.add_parser("encounter", help="record another learning encounter")
    encounter.add_argument("--id", required=True)
    encounter.set_defaults(handler=handle_encounter)

    complete = subparsers.add_parser(
        "complete-review", help="atomically score a record and add demonstrated errors"
    )
    complete.add_argument("--input", required=True, help="JSON file path or - for stdin")
    complete.set_defaults(handler=handle_complete_review)

    for command, expected_status in (("review", "learning"), ("familiar-review", "familiar")):
        review = subparsers.add_parser(command, help=f"score one {expected_status} record")
        review.add_argument("--category", required=True, choices=CATEGORIES)
        review.add_argument("--key", required=True)
        review.add_argument("--score", required=True, type=float)
        review.set_defaults(
            handler=lambda args, status=expected_status: handle_review(args, status)
        )

    listing = subparsers.add_parser("list", help="list records")
    listing.add_argument("--category", choices=CATEGORIES)
    listing.add_argument("--status", choices=STATUSES, default="learning")
    listing.set_defaults(handler=handle_list)
    familiar = subparsers.add_parser("familiar-list", help="list familiar records")
    familiar.set_defaults(handler=lambda args: handle_legacy_list(args, "familiar"))
    mastered = subparsers.add_parser("mastered-list", help="list mastered records")
    mastered.set_defaults(handler=lambda args: handle_legacy_list(args, "mastered"))

    search = subparsers.add_parser("search", help="search record content")
    search.add_argument("--query", required=True)
    search.add_argument("--include-familiar", action="store_true")
    search.add_argument("--include-mastered", action="store_true")
    search.set_defaults(handler=handle_search)

    summary = subparsers.add_parser("summary", help="summarize record counts")
    summary.add_argument("--include-familiar", action="store_true")
    summary.add_argument("--include-mastered", action="store_true")
    summary.set_defaults(handler=handle_summary)

    menu = subparsers.add_parser("menu", help="build a context-aware review menu")
    menu.add_argument(
        "--context",
        choices=("initial", "review-complete", "exercise-active"),
        default="initial",
    )
    menu.add_argument("--focus", help="current English target used in follow-up labels")
    menu.set_defaults(handler=handle_menu)

    next_review = subparsers.add_parser("next-review", help="select a scheduled record")
    next_review.add_argument("--category", action="append", choices=CATEGORIES, default=[])
    next_review.add_argument("--path")
    next_review.add_argument("--status", choices=STATUSES, default="learning")
    next_review.add_argument("--familiar", action="store_true")
    next_review.add_argument("--mastered", action="store_true")
    next_review.add_argument("--random", action="store_true")
    next_review.add_argument("--due-only", action="store_true")
    next_review.set_defaults(handler=handle_next_review)

    history = subparsers.add_parser("history", help="show one record's review history")
    history.add_argument("--id", required=True)
    history.set_defaults(handler=lambda args: service().history(args.id))
    stats = subparsers.add_parser("stats", help="show review statistics")
    stats.add_argument("--period", default=30, type=parse_period)
    stats.set_defaults(handler=lambda args: service().stats(args.period))

    validate = subparsers.add_parser("validate", help="validate the canonical database")
    validate.set_defaults(handler=lambda args: service().validate())
    repair = subparsers.add_parser("repair", help="repair unambiguous record issues")
    repair.add_argument("--dry-run", action="store_true")
    repair.set_defaults(handler=lambda args: service().repair(dry_run=args.dry_run))
    migrate = subparsers.add_parser("migrate-v2", help="migrate legacy record directories")
    migrate.add_argument("--dry-run", action="store_true")
    migrate.set_defaults(handler=lambda args: service().migrate_legacy(dry_run=args.dry_run))
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except (RecordError, ValueError) as exc:
        parser.error(str(exc))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if args.command == "validate" and not result.get("valid", False):
        return 1
    return 0
