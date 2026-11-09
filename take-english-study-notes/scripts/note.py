#!/usr/bin/env python3
"""笔记（`learning-record-notes/*.md`）的统一入口：规则、模板、校验、写入都在本 skill 内。

用法：
    python3 take-english-study-notes/scripts/note.py explain --file <note.md> --content-file - [--update] [--check]
    python3 take-english-study-notes/scripts/note.py append --file <note.md> --content-file - [--check]
    python3 take-english-study-notes/scripts/note.py append-section --file <note.md> --heading "<# ...>" --content-file - [--check]
    python3 take-english-study-notes/scripts/note.py replace --file <note.md> --heading "<# ...>" --content-file - [--rewrite-section "## ..."] [--check]
    python3 take-english-study-notes/scripts/note.py sections --file <note.md> [--heading "<# ...>"] [--section "## <小节标题>"]
    python3 take-english-study-notes/scripts/note.py list [--record <id>]
    python3 take-english-study-notes/scripts/note.py check --all [--fix]
    python3 take-english-study-notes/scripts/note.py check learning-record-notes/<category>-<slug>.md

写入全程在 `learning-record-notes/.notes.lock` 排他锁内完成，调用方不自己改写文件。
追踪字段（记录 ID、目标知识点、累计复习次数、下次复习、分类 · 状态变化、本轮得分）在写入后自动与
规范记录比对；记录事实由 learn-from-english 的 `learning_records.py record-tracking` 提供，
找不到该脚本时跳过比对并在结果里说明，不阻断写入。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from note_store import NoteStore, NoteError, _split_blocks  # noqa: E402


REPO_ROOT = Path(
    os.environ.get("LEARN_ENGLISH_REPO_ROOT", Path(__file__).resolve().parents[2])
).expanduser().resolve()

TRACKING_ROW_RE = re.compile(
    r"<tr><td>(记录 ID / 试卷 ID|目标知识点|累计复习次数|下次复习|分类 · 状态变化|本轮得分|复习时间|主观题得分|笔记生成时间|笔记更新时间)</td><td>(.*?)</td></tr>"
)
TRACKING_SKIP = ("题量与错题数", "主观题得分", "笔记生成时间", "笔记更新时间")


def repo_root() -> Path:
    return REPO_ROOT


def store() -> NoteStore:
    return NoteStore(repo_root())


def cli_candidates() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get("LEARN_ENGLISH_CLI")
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(repo_root() / "learn-from-english" / "scripts" / "learning_records.py")
    for root in (
        Path.home() / ".agents" / "skills",
        Path.home() / ".claude" / "skills",
        Path.home() / "Doubao" / "skills",
    ):
        candidates.append(root / "learn-from-english" / "scripts" / "learning_records.py")
    return candidates


def locate_records_cli() -> Path | None:
    for candidate in cli_candidates():
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def record_tracking(identifier: str) -> dict[str, Any] | None:
    """Ask the record store for the authoritative tracking values (read-only)."""
    if not identifier:
        return None
    cli = locate_records_cli()
    if cli is None:
        return None
    try:
        completed = subprocess.run(
            [sys.executable, str(cli), "record-tracking", "--id", identifier],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        payload = json.loads(completed.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    tracking = payload.get("tracking")
    return tracking if isinstance(tracking, dict) else None


def verify_tracking(note: NoteStore, file: str, heading: str) -> dict[str, Any]:
    """Compare the written tracking rows with the canonical record, so nobody copies them by hand."""
    target = note.resolve(file)
    text = target.read_text(encoding="utf-8")
    block = next((body for title, body in _split_blocks(text) if title == heading), None)
    if block is None:
        block = ""
    # 记录级字段在文件顶部的「基础信息」里，本轮字段在目标区块里：先读全文件，再用目标区块覆盖
    full_rows = {
        field: value.strip() for field, value in TRACKING_ROW_RE.findall(text)
    }
    rows = {
        **full_rows,
        **{field: value.strip() for field, value in TRACKING_ROW_RE.findall(block)},
    }
    expected = record_tracking(rows.get("记录 ID / 试卷 ID", ""))
    if expected is None:
        return {"tracking_skipped": "record store unavailable; tracking rows not verified"}
    mismatches = [
        {"field": field, "expected": value, "actual": rows.get(field)}
        for field, value in expected.items()
        if field not in TRACKING_SKIP and rows.get(field) != value
    ]
    if not mismatches:
        return {}
    return {"tracking_mismatch": mismatches, "tracking_expected": expected}


def validate_after_write(note: NoteStore, result: dict[str, Any]) -> dict[str, Any]:
    """Check, auto-repair the safe issues, re-check, then verify tracking rows."""
    heading = result.get("heading", "")
    check = note.check(result["file"])
    if check.get("ok") is False:
        repaired = note.check(result["file"], fix=True)
        if repaired.get("fixed"):
            result["auto_fixed"] = repaired["fixed"]
            check = note.check(result["file"])
    result["check"] = check
    result["check_ok"] = check.get("ok")
    result["note_status"] = "valid" if check.get("ok") else ("unverified" if check.get("ok") is None else "invalid")
    if heading:
        result.update(verify_tracking(note, result["file"], heading))
    return result


def read_content(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).expanduser().read_text(encoding="utf-8")


def handle_explain(args: argparse.Namespace) -> dict[str, Any]:
    note = store()
    result = note.write_explanation(args.file, read_content(args.content_file), update=args.update)
    if args.check and (
        result.get("appended") or result.get("updated") or result.get("inserted")
    ):
        result["check"] = note.check(result["file"])
        result["check_ok"] = result["check"].get("ok")
        result["note_status"] = (
            "valid" if result["check"].get("ok") else ("unverified" if result["check"].get("ok") is None else "invalid")
        )
    return result


def handle_append(args: argparse.Namespace) -> dict[str, Any]:
    note = store()
    result = note.append(args.file, read_content(args.content_file))
    if args.check:
        validate_after_write(note, result)
    return result


def handle_append_section(args: argparse.Namespace) -> dict[str, Any]:
    note = store()
    result = note.append_section(args.file, args.heading, read_content(args.content_file))
    if args.check and result.get("appended_section"):
        validate_after_write(note, result)
    return result


def handle_replace(args: argparse.Namespace) -> dict[str, Any]:
    note = store()
    result = note.replace_block(
        args.file,
        args.heading,
        read_content(args.content_file),
        tuple(args.drop_section or ()),
        tuple(args.rewrite_section or ()),
    )
    if args.check:
        validate_after_write(note, result)
    return result


def handle_sections(args: argparse.Namespace) -> dict[str, Any]:
    note = store()
    whole = note.sections(args.file)
    result: dict[str, Any] = {"file": whole["file"]}
    result["record_id"] = whole["record_id"]
    result["blocks"] = [
        {"heading": block["heading"], "sections": block["sections"]}
        for block in whole["blocks"]
        if args.heading is None or block["heading"] == args.heading
    ]
    result["block_count"] = whole["block_count"]
    if args.section:
        queried = args.section.strip()
        result["queried_section"] = queried
        result["has_section"] = any(
            queried in block["sections"] for block in whole["blocks"]
        )
    return result


def handle_list(args: argparse.Namespace) -> dict[str, Any]:
    return {"notes": store().list_notes(args.record)}


CHECK_COMMANDS = ("check", "validate")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    explain = subparsers.add_parser(
        "explain", help="create a note with the file-level '## 讲解' section (one per knowledge point)"
    )
    explain.add_argument("--file", required=True, help="learning-record-notes/<category>-<slug>.md")
    explain.add_argument("--content-file", required=True, help="raw Markdown (基础信息 + 讲解) path or - for stdin")
    explain.add_argument(
        "--update",
        action="store_true",
        help="rewrite the existing '## 讲解' section; if the note has none yet, insert it after the 基础信息 table",
    )
    explain.add_argument("--check", action="store_true", help="run the validator afterwards")
    explain.set_defaults(handler=handle_explain)

    append = subparsers.add_parser("append", help="append one round block under an exclusive lock")
    append.add_argument("--file", required=True, help="learning-record-notes/<category>-<slug>.md")
    append.add_argument("--content-file", required=True, help="raw Markdown block path or - for stdin")
    append.add_argument("--check", action="store_true", help="run the validator and tracking compare afterwards")
    append.set_defaults(handler=handle_append)

    append_section = subparsers.add_parser(
        "append-section", help="append one '## section' inside an existing round block"
    )
    append_section.add_argument("--file", required=True, help="learning-record-notes/<category>-<slug>.md")
    append_section.add_argument("--heading", required=True, help="exact level-1 heading line of the target round")
    append_section.add_argument("--content-file", required=True, help="raw '## ...' Markdown section path or - for stdin")
    append_section.add_argument("--check", action="store_true", help="run the validator afterwards")
    append_section.set_defaults(handler=handle_append_section)

    replace = subparsers.add_parser("replace", help="replace one existing round block in place")
    replace.add_argument("--file", required=True, help="learning-record-notes/<category>-<slug>.md")
    replace.add_argument("--heading", required=True, help="exact level-1 heading line of the round to replace")
    replace.add_argument("--content-file", required=True, help="raw Markdown block path or - for stdin")
    replace.add_argument(
        "--drop-section",
        action="append",
        metavar="HEADING",
        help="allow dropping an existing '## section'; sections the new content omits are preserved",
    )
    replace.add_argument(
        "--rewrite-section",
        action="append",
        metavar="HEADING",
        help="declare a '## section' this replacement may rewrite (only one per replace otherwise)",
    )
    replace.add_argument("--check", action="store_true", help="run the validator and tracking compare afterwards")
    replace.set_defaults(handler=handle_replace)

    sections = subparsers.add_parser(
        "sections", help="index one note's round blocks and '##' sections (read-only)"
    )
    sections.add_argument("--file", required=True, help="learning-record-notes/<category>-<slug>.md")
    sections.add_argument("--heading", help="only this exact level-1 heading line")
    sections.add_argument("--section", help="report has_section for this '## ...' title")
    sections.set_defaults(handler=handle_sections)

    listing = subparsers.add_parser("list", help="list notes, optionally filtered by record id")
    listing.add_argument("--record", help="only notes tracking this record id")
    listing.set_defaults(handler=handle_list)

    return parser


def fail(message: str) -> int:
    print(
        json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2),
        file=sys.stderr,
    )
    return 2


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args[0] in CHECK_COMMANDS:
        # 校验器就在本目录，独立运行不需要另装任何 skill
        import check_note  # noqa: PLC0415

        return check_note.main(["note.py", *args[1:]])

    parser = build_parser()
    namespace = parser.parse_args(args)
    handler = getattr(namespace, "handler", None)
    if handler is None:  # pragma: no cover - argparse 已经要求子命令
        return fail(f"unknown command: {namespace.command}")
    try:
        result = handler(namespace)
    except NoteError as exc:
        return fail(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    check = result.get("check") if isinstance(result, dict) else None
    if isinstance(check, dict) and check.get("ok") is False:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
