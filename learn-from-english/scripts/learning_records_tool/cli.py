"""Command-line interface for the versioned learning-record service."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .cache import DEFAULT_MAX_AGE_SECONDS, get_snapshot, git_head
from .menu import annotate_writes
from .models import CATEGORIES, STATUSES, RecordError, record_id
from .notes import NoteStore, _split_blocks
from .papers import PAPER_STATUSES, PaperService
from .service import RecordService
from .store import RecordStore


REPO_ROOT = Path(
    os.environ.get("LEARN_ENGLISH_REPO_ROOT", Path(__file__).resolve().parents[3])
).resolve()


def service() -> RecordService:
    return RecordService(RecordStore(REPO_ROOT))


def paper_service() -> PaperService:
    return PaperService(RecordStore(REPO_ROOT))


def note_store() -> NoteStore:
    return NoteStore(REPO_ROOT)


def read_text_input(path: str) -> str:
    try:
        if path == "-":
            return sys.stdin.read()
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise RecordError(f"cannot read note content: {exc}") from exc


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


def handle_merge(args: argparse.Namespace) -> dict[str, Any]:
    return service().merge_records(
        args.target,
        args.source,
        title=args.title,
        explanation=args.explanation,
        source=args.record_source,
        example=args.example,
    )


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
    claim_owner = payload.get("claim_owner")
    claim_token = payload.get("claim_token")
    if claim_owner is not None and not isinstance(claim_owner, str):
        raise RecordError("complete-review claim_owner must be a string")
    if claim_token is not None and not isinstance(claim_token, str):
        raise RecordError("complete-review claim_token must be a string")
    return service().complete_review(
        str(payload.get("id", "")),
        score,
        errors,
        claim_owner=claim_owner,
        claim_token=claim_token,
    )


def handle_rescore(args: argparse.Namespace) -> dict[str, Any]:
    return service().rescore(args.id, args.score)


def handle_review(args: argparse.Namespace, expected_status: str | None = None) -> dict[str, Any]:
    identifier = record_id(args.category, args.key)
    return service().complete_review(
        identifier, args.score, expected_status=expected_status
    )


def handle_list(args: argparse.Namespace) -> list[dict[str, Any]]:
    return _maybe_brief(
        service().list_records(category=args.category, status=args.status), args.brief
    )


def handle_legacy_list(args: argparse.Namespace, status: str) -> list[dict[str, Any]]:
    return _maybe_brief(service().list_records(status=status), getattr(args, "brief", False))


def _maybe_brief(
    records: list[dict[str, Any]], brief: bool
) -> list[dict[str, Any]]:
    """Drop review history and scheduling noise when a list is only a chooser."""
    if not brief:
        return records
    return [
        {
            key: record.get(key)
            for key in (
                "id",
                "category",
                "status",
                "title",
                "explanation",
                "source",
                "example",
                "mastery_score",
                "review_count",
                "lapse_count",
            )
        }
        for record in records
    ]


def handle_search(args: argparse.Namespace) -> list[dict[str, Any]]:
    statuses = set(args.status) if args.status else None
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
    return service().menu(
        args.context,
        focus=args.focus,
        current_exercise_explained=args.current_exercise_explained,
        has_answer_errors=args.has_answer_errors,
        grammar_explained=args.grammar_explained,
    )


def handle_next_review(args: argparse.Namespace) -> dict[str, Any]:
    return service().next_review(
        categories=args.category,
        path=args.path,
        status=args.status,
        randomize=args.random,
        due_only=args.due_only,
        claim_owner=args.claim_owner,
    )


def handle_release_claim(args: argparse.Namespace) -> dict[str, Any]:
    return service().release_claim(
        args.id,
        claim_owner=args.claim_owner,
        claim_token=args.claim_token,
    )


def handle_error_clusters(args: argparse.Namespace) -> dict[str, Any]:
    return service().error_pattern_clusters(
        minimum_size=args.minimum_size
    )


def handle_error_cluster_get(args: argparse.Namespace) -> dict[str, Any]:
    return service().error_cluster_records(
        args.id,
        unclustered=args.unclustered,
        limit=args.limit,
        minimum_size=args.minimum_size,
    )


def handle_paper_create(args: argparse.Namespace) -> dict[str, Any]:
    return paper_service().create(read_input(args.input))


def handle_paper_get(args: argparse.Namespace) -> dict[str, Any]:
    return paper_service().get(args.paper_id, args.attempt_id)


def handle_paper_list(args: argparse.Namespace) -> Any:
    return paper_service().list(args.status, randomize=args.random)


def handle_paper_submit(args: argparse.Namespace) -> dict[str, Any]:
    return paper_service().submit(read_input(args.input))


def handle_paper_complete(args: argparse.Namespace) -> dict[str, Any]:
    return paper_service().complete(read_input(args.input))


def handle_paper_menu(args: argparse.Namespace) -> list[dict[str, Any]]:
    return annotate_writes(paper_service().menu_options())


def handle_note_sections(args: argparse.Namespace) -> dict[str, Any]:
    """Index one note's round blocks and `##` sections without a grep."""
    whole = note_store().sections(args.file)
    blocks = [
        block
        for block in whole["blocks"]
        if args.heading is None or block["heading"] == args.heading
    ]
    result: dict[str, Any] = {**whole, "blocks": blocks}
    if args.section:
        queried = args.section.strip()
        result["queried_section"] = queried
        result["has_section"] = any(
            queried in block["sections"] for block in whole["blocks"]
        )
    return result


def handle_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    """One cheap answer to "where does the repository stand right now?".

    Replaces a round of ``ls``/``grep``/``git log`` calls: commit hash, note
    file index, and the record→note mapping come from a cached snapshot that
    is rebuilt only when missing or older than ``--max-age``.
    """
    snapshot = get_snapshot(REPO_ROOT, refresh=args.refresh, max_age=args.max_age)
    age = float(snapshot.get("age_seconds") or 0.0)
    live_head = git_head(REPO_ROOT)
    payload: dict[str, Any] = {
        "git_head": snapshot.get("git_head"),
        "live_git_head": live_head,
        "head_drift": snapshot.get("git_head") != live_head,
        "generated_at": snapshot.get("generated_at"),
        "age_seconds": age,
        "max_age_seconds": args.max_age,
        "source": snapshot.get("source"),
        "stale": age > args.max_age,
        "counts": snapshot.get("counts", {}),
        "hint": (
            "read-only view for this session; a write through note.append/"
            "append_section/replace refreshes it automatically, so do not "
            "re-run git status/diff before a read-only display. When "
            "head_drift is true the working tree moved on: run --refresh "
            "before a write, not before a display"
        ),
    }
    if args.record:
        payload["record_file"] = snapshot.get("record_files", {}).get(args.record)
    if args.notes:
        payload["notes"] = snapshot.get("notes", {})
    return payload


TRACKING_ROW_RE = re.compile(
    r"<tr><td>(记录 ID / 试卷 ID|目标知识点|累计复习次数|下次复习|分类 · 状态变化|本轮得分|复习时间|主观题得分|笔记生成时间|笔记更新时间)</td><td>(.*?)</td></tr>"
)
TRACKING_SKIP = ("题量与错题数", "主观题得分", "笔记生成时间", "笔记更新时间")


def verify_tracking(store: NoteStore, file: str, heading: str) -> dict[str, Any]:
    """Compare the written tracking rows with the canonical record, so nobody copies them by hand."""
    target = store.resolve(file)
    block = next(
        (body for title, body in _split_blocks(target.read_text(encoding="utf-8")) if title == heading),
        None,
    )
    if block is None:
        return {}
    # 记录级字段在文件顶部的「基础信息」里，本轮字段在目标区块里：先读全文件，再用目标区块覆盖
    full_rows = {
        field: value.strip()
        for field, value in TRACKING_ROW_RE.findall(target.read_text(encoding="utf-8"))
    }
    rows = {**full_rows, **{field: value.strip() for field, value in TRACKING_ROW_RE.findall(block)}}
    identifier = rows.get("记录 ID / 试卷 ID", "")
    try:
        expected = service().note_context(identifier)["tracking"]
    except (RecordError, ValueError):
        return {}
    mismatches = [
        {"field": field, "expected": value, "actual": rows.get(field)}
        for field, value in expected.items()
        if field not in TRACKING_SKIP and rows.get(field) != value
    ]
    if not mismatches:
        return {}
    return {"tracking_mismatch": mismatches, "tracking_expected": expected}


def validate_after_write(store: NoteStore, result: dict[str, Any]) -> dict[str, Any]:
    """Check, auto-repair the safe issues, re-check, then verify tracking rows."""
    heading = result.get("heading", "")
    check = store.check(result["file"])
    if check.get("ok") is False:
        repaired = store.check(result["file"], fix=True)
        if repaired.get("fixed"):
            result["auto_fixed"] = repaired["fixed"]
            check = store.check(result["file"])
    result["check"] = check
    result.update(verify_tracking(store, result["file"], heading))
    return result


def handle_note_append(args: argparse.Namespace) -> dict[str, Any]:
    store = note_store()
    content = read_text_input(args.content_file)
    result = store.append(args.file, content)
    if args.check:
        validate_after_write(store, result)
    return result


def handle_note_append_section(args: argparse.Namespace) -> dict[str, Any]:
    store = note_store()
    content = read_text_input(args.content_file)
    result = store.append_section(args.file, args.heading, content)
    if args.check and result.get("appended_section"):
        validate_after_write(store, result)
    return result


def handle_note_replace_block(args: argparse.Namespace) -> dict[str, Any]:
    store = note_store()
    content = read_text_input(args.content_file)
    result = store.replace_block(
        args.file,
        args.heading,
        content,
        tuple(args.drop_section or ()),
        tuple(args.rewrite_section or ()),
    )
    if args.check:
        validate_after_write(store, result)
    return result


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

    batch = subparsers.add_parser("batch-upsert", help="add multiple records in one coordinated write")
    batch.add_argument("--input", required=True, help="JSON file path or - for stdin")
    batch.set_defaults(handler=handle_batch_upsert)

    merge = subparsers.add_parser("merge", help="merge duplicate records into one target")
    merge.add_argument("--target", required=True)
    merge.add_argument("--source", action="append", required=True)
    merge.add_argument("--title")
    merge.add_argument("--explanation")
    merge.add_argument("--record-source")
    merge.add_argument("--example")
    merge.set_defaults(handler=handle_merge)

    encounter = subparsers.add_parser("encounter", help="record another learning encounter")
    encounter.add_argument("--id", required=True)
    encounter.set_defaults(handler=handle_encounter)

    complete = subparsers.add_parser(
        "complete-review", help="score a record and add demonstrated errors in one coordinated write"
    )
    complete.add_argument("--input", required=True, help="JSON file path or - for stdin")
    complete.set_defaults(handler=handle_complete_review)

    rescore = subparsers.add_parser(
        "rescore", help="correct the most recent review score of one record"
    )
    rescore.add_argument("--id", required=True)
    rescore.add_argument("--score", required=True, type=float)
    rescore.set_defaults(handler=handle_rescore)

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
    listing.add_argument(
        "--brief", action="store_true", help="omit review history and scheduling timestamps"
    )
    listing.set_defaults(handler=handle_list)
    familiar = subparsers.add_parser("familiar-list", help="list familiar records")
    familiar.add_argument(
        "--brief", action="store_true", help="omit review history and scheduling timestamps"
    )
    familiar.set_defaults(handler=lambda args: handle_legacy_list(args, "familiar"))
    mastered = subparsers.add_parser("mastered-list", help="list mastered records")
    mastered.add_argument(
        "--brief", action="store_true", help="omit review history and scheduling timestamps"
    )
    mastered.set_defaults(handler=lambda args: handle_legacy_list(args, "mastered"))

    search = subparsers.add_parser("search", help="search record content")
    search.add_argument("--query", required=True)
    search.add_argument(
        "--status",
        action="append",
        choices=STATUSES,
        default=[],
        help="limit results to one or more statuses; defaults to all statuses",
    )
    search.set_defaults(handler=handle_search)

    summary = subparsers.add_parser("summary", help="summarize record counts")
    summary.add_argument("--include-familiar", action="store_true")
    summary.add_argument("--include-mastered", action="store_true")
    summary.set_defaults(handler=handle_summary)

    menu = subparsers.add_parser("menu", help="build a context-aware menu")
    menu.add_argument(
        "--context",
        choices=("initial", "review-complete", "learn"),
        default="initial",
    )
    menu.add_argument("--focus", help="current English target used in follow-up labels")
    menu.add_argument(
        "--current-exercise-explained",
        action="store_true",
        help="hide the error-explanation option after it has already been used",
    )
    menu.add_argument(
        "--has-answer-errors",
        action="store_true",
        help="show the error-explanation option after a reviewed answer has mistakes",
    )
    menu.add_argument(
        "--grammar-explained",
        action="store_true",
        help="learn context only: drop the generic grammar-entry option",
    )
    menu.set_defaults(handler=handle_menu)

    next_review = subparsers.add_parser("next-review", help="select a scheduled record")
    next_review.add_argument("--category", action="append", choices=CATEGORIES, default=[])
    next_review.add_argument("--path")
    review_status = next_review.add_mutually_exclusive_group()
    review_status.add_argument("--status", choices=STATUSES, default="learning")
    review_status.add_argument(
        "--familiar", action="store_const", const="familiar", dest="status"
    )
    review_status.add_argument(
        "--mastered", action="store_const", const="mastered", dest="status"
    )
    next_review.add_argument("--random", action="store_true")
    next_review.add_argument("--due-only", action="store_true")
    next_review.add_argument("--claim-owner")
    next_review.set_defaults(handler=handle_next_review)

    release_claim = subparsers.add_parser(
        "release-claim", help="release an active review claim"
    )
    release_claim.add_argument("--id", required=True)
    release_claim.add_argument("--claim-owner", required=True)
    release_claim.add_argument("--claim-token", required=True)
    release_claim.set_defaults(handler=handle_release_claim)

    error_clusters = subparsers.add_parser(
        "error-clusters", help="group similar error records for focused review"
    )
    error_clusters.add_argument("--minimum-size", type=int, default=2)
    error_clusters.set_defaults(handler=handle_error_clusters)

    cluster_get = subparsers.add_parser(
        "error-cluster-get", help="load the practice material for one error cluster"
    )
    group = cluster_get.add_mutually_exclusive_group(required=True)
    group.add_argument("--id", help="cluster id returned by error-clusters")
    group.add_argument(
        "--unclustered", action="store_true", help="load unclustered error records"
    )
    cluster_get.add_argument("--limit", type=int, default=None)
    cluster_get.add_argument(
        "--minimum-size",
        type=int,
        default=2,
        help="must match the value used when error-clusters built the ids",
    )
    cluster_get.set_defaults(handler=handle_error_cluster_get)

    duplicates = subparsers.add_parser(
        "duplicates", help="list near-duplicate records that are worth merging"
    )
    duplicates.add_argument("--threshold", type=float, default=0.85)
    duplicates.add_argument("--category", choices=CATEGORIES)
    duplicates.set_defaults(
        handler=lambda args: service().duplicate_candidates(
            threshold=args.threshold, category=args.category
        )
    )

    paper_create = subparsers.add_parser("paper-create", help="persist one generated exam paper")
    paper_create.add_argument("--input", required=True, help="JSON file path or - for stdin")
    paper_create.set_defaults(handler=handle_paper_create)

    paper_get = subparsers.add_parser("paper-get", help="read a paper and optional attempt")
    paper_get.add_argument("--paper-id", required=True)
    paper_get.add_argument("--attempt-id")
    paper_get.set_defaults(handler=handle_paper_get)

    paper_list = subparsers.add_parser("paper-list", help="list persisted exam papers")
    paper_list.add_argument("--status", choices=PAPER_STATUSES)
    paper_list.add_argument("--random", action="store_true")
    paper_list.set_defaults(handler=handle_paper_list)

    paper_submit = subparsers.add_parser("paper-submit", help="save incremental paper answers")
    paper_submit.add_argument("--input", required=True, help="JSON file path or - for stdin")
    paper_submit.set_defaults(handler=handle_paper_submit)

    paper_complete = subparsers.add_parser(
        "paper-complete", help="grade a paper attempt and record demonstrated errors"
    )
    paper_complete.add_argument("--input", required=True, help="JSON file path or - for stdin")
    paper_complete.set_defaults(handler=handle_paper_complete)

    paper_menu = subparsers.add_parser("paper-menu", help="build shared paper-history menu options")
    paper_menu.set_defaults(handler=handle_paper_menu)

    snapshot = subparsers.add_parser(
        "snapshot",
        help="one cheap read-only answer: HEAD, note index, record->note map",
    )
    snapshot.add_argument(
        "--refresh", action="store_true", help="rebuild even when the cache is fresh"
    )
    snapshot.add_argument(
        "--max-age",
        type=float,
        default=DEFAULT_MAX_AGE_SECONDS,
        help="seconds the cached view stays valid (default 1800 = 30 minutes)",
    )
    snapshot.add_argument(
        "--record", help="resolve one record id to the note file that tracks it"
    )
    snapshot.add_argument(
        "--notes", action="store_true", help="include the per-file block/section index"
    )
    snapshot.set_defaults(handler=handle_snapshot)

    note_sections = subparsers.add_parser(
        "note-sections",
        help="index one note's round blocks and '##' sections (read-only)",
    )
    note_sections.add_argument(
        "--file", required=True, help="learning-record-notes/<category>-<slug>.md"
    )
    note_sections.add_argument("--heading", help="only this exact level-1 heading line")
    note_sections.add_argument(
        "--section",
        help="report has_section for this '## ...' title before composing content",
    )
    note_sections.set_defaults(handler=handle_note_sections)

    note_append = subparsers.add_parser(
        "note-append",
        help="append one round block to a review note under an exclusive lock",
    )
    note_append.add_argument(
        "--file", required=True, help="learning-record-notes/<category>-<slug>.md"
    )
    note_append.add_argument(
        "--content-file", required=True, help="raw Markdown block path or - for stdin"
    )
    note_append.add_argument(
        "--check",
        action="store_true",
        help="run practice-learning-records check_note.py afterwards",
    )
    note_append.set_defaults(handler=handle_note_append)

    note_append_section = subparsers.add_parser(
        "note-append-section",
        help="append one '## section' inside an existing round block under the lock",
    )
    note_append_section.add_argument(
        "--file", required=True, help="learning-record-notes/<category>-<slug>.md"
    )
    note_append_section.add_argument(
        "--heading", required=True, help="exact level-1 heading line of the target round"
    )
    note_append_section.add_argument(
        "--content-file", required=True, help="raw '## ...' Markdown section path or - for stdin"
    )
    note_append_section.add_argument(
        "--check",
        action="store_true",
        help="run practice-learning-records check_note.py afterwards",
    )
    note_append_section.set_defaults(handler=handle_note_append_section)

    note_replace = subparsers.add_parser(
        "note-replace-block",
        help="replace one existing round block in place under the same exclusive lock",
    )
    note_replace.add_argument(
        "--file", required=True, help="learning-record-notes/<category>-<slug>.md"
    )
    note_replace.add_argument(
        "--heading", required=True, help="exact level-1 heading line of the round to replace"
    )
    note_replace.add_argument(
        "--content-file", required=True, help="raw Markdown block path or - for stdin"
    )
    note_replace.add_argument(
        "--drop-section",
        action="append",
        metavar="HEADING",
        help=(
            "allow dropping an existing '## section'; every other section that the new "
            "content omits is preserved automatically"
        ),
    )
    note_replace.add_argument(
        "--rewrite-section",
        action="append",
        metavar="HEADING",
        help=(
            "declare a '## section' this replacement is allowed to rewrite; "
            "without it a single replace may only modify one section"
        ),
    )
    note_replace.add_argument(
        "--check",
        action="store_true",
        help="run practice-learning-records check_note.py afterwards",
    )
    note_replace.set_defaults(handler=handle_note_replace_block)

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
    exit_code = 0
    if isinstance(result, dict):
        check = result.get("check")
        if isinstance(check, dict):
            # 写入是否成功看 appended / replaced，是否合规看 check.ok。
            # 用 note_status 把两者分开，避免 ok:true 配退出码 1 被读成写入失败。
            check_ok = check.get("ok")
            result["check_ok"] = check_ok
            result["note_status"] = (
                "valid"
                if check_ok is True
                else "invalid"
                if check_ok is False
                else "unverified"
            )
            if check_ok is False:
                exit_code = 1
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if args.command == "validate" and not result.get("valid", False):
        return 1
    return exit_code
