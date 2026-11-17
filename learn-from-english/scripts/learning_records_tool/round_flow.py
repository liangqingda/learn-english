"""One coordinated call that finishes a review round.

A scored review used to take four or five separate calls: ``complete-review``,
``note.py sections``, ``note.py append``, ``note.py check`` and ``menu``. Each
call is fast on its own, but every call is a round trip for the caller, so the
round felt slow. :func:`finish_round` runs the same writes in one process and
returns one JSON answer.

The note writer still lives in ``take-english-study-notes``; this module only
drives it through its public CLI, exactly like ``note.py`` drives
``record-tracking`` back. Nothing here parses or rewrites the Markdown.

Payload (``review-round --input -``)::

    {
      "review": {"id": "...", "score": 6, "errors": [...],
                 "claim_owner": "...", "claim_token": "..."},        # optional
      "note": {
        "file": "learning-record-notes/errors/errors-out-west.md",
        "date": "2026-11-16", "time": "21:30", "kind": "复习",
        "body": "## 本轮习题\\n\\n<table ...>...</table>",             # 不含 `# 标题` 行
        "explain": {"content": "...", "update": true},              # 文件缺 `## 讲解` 时必填
        "explain_sections": [{"title": "## 菜单项", "content": "..."}],
        "explain_parts": [{"title": "## 菜单项", "content": "补一段正文"}]
      },                                                            # optional
      "menu": {"context": "review-complete", "focus": "...",
               "has_answer_errors": true},                          # optional
      "check": true                                                 # default true
    }

``explain_sections`` entries are whole file-level sections (heading plus body); a
section whose title already exists is reported as ``duplicate`` and not rewritten,
because only scenario dialogues and stories are recorded again.
``explain_parts`` entries are body-only fragments appended to an existing section;
use them when the same menu item produces another story or dialogue block.

Each entry of ``review.errors`` may carry a ``category``: a reusable mistake goes
into the knowledge category it belongs to (``vocabulary`` / ``phrases`` /
``grammar`` / ``usage``), and only a mistake with no transferable knowledge point
goes into ``errors``; omitting ``category`` keeps the old ``errors`` default.

Returned payload always carries ``ok``. A round whose block already exists returns
``already_saved: true`` and writes nothing further, so retrying the same payload
never duplicates the explanation sections. A failed step keeps the earlier results
and adds ``failed_step`` plus ``error``, so a caller can tell "the record was
written but the note was rejected" from "nothing happened" and follow the
failure-recovery matrix instead of retrying blind.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .models import RecordError

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")
ROUND_KINDS = ("复习", "练习", "套题")


def note_cli_path(repo_root: Path) -> Path:
    """Locate the note writer without importing the other skill's module."""
    override = os.environ.get("LEARN_ENGLISH_NOTE_CLI")
    candidates = [Path(override).expanduser()] if override else []
    candidates.append(repo_root / "take-english-study-notes" / "scripts" / "note.py")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    raise RecordError(
        "note writer not found: take-english-study-notes/scripts/note.py"
    )


def run_note(cli: Path, argv: list[str], content: str | None = None) -> dict[str, Any]:
    """Run one note.py command and parse its JSON answer."""
    try:
        completed = subprocess.run(
            [sys.executable, str(cli), *argv],
            input=content,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RecordError(f"cannot run the note writer: {exc}") from exc
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        detail = (completed.stderr or completed.stdout).strip()
        raise RecordError(f"note writer returned unreadable output: {detail}") from None
    if completed.returncode not in (0, 1) or payload.get("ok") is False:
        detail = payload.get("error") or (completed.stderr or "").strip() or "note write failed"
        raise RecordError(str(detail))
    return payload


def note_check(cli: Path, note_file: str, repo_root: Path) -> dict[str, Any]:
    """Validate one note; an invalid note is reported, not raised."""
    target = Path(note_file).expanduser()
    if not target.is_absolute():
        target = repo_root / target

    def run(*extra: str) -> dict[str, Any] | None:
        try:
            completed = subprocess.run(
                [sys.executable, str(cli), "check", str(target), *extra],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": None, "skipped": f"cannot run the note validator: {exc}", "issues": []}
        try:
            return json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return {
                "ok": None,
                "skipped": "note validator returned unreadable output",
                "issues": [],
            }

    report = run()
    if report is None or report.get("ok") is not False:
        return report or {"ok": None, "issues": []}
    # 与 note.py 的写入路径一致：能安全修的先修，再重新校验一次
    repaired = run("--fix")
    if repaired and repaired.get("fixed"):
        report = run() or report
        report["auto_fixed"] = repaired.get("fixed")
    return report


def section_body(content: str, title: str) -> str:
    """Strip the section heading so a repeated menu item can be appended as a fragment."""
    lines = content.split("\n")
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if line.strip() == title:
            return "\n".join(lines[index + 1 :]).strip()
        if line.startswith("## "):
            raise RecordError(
                f"section content starts with {line.strip()!r} but the entry title is {title!r}"
            )
        break
    return content.strip()


def write_explanation(cli: Path, note_file: str, explain: dict[str, Any], *, exists: bool) -> None:
    content = explain.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RecordError(
            "the note has no file-level '## 讲解'; supply note.explain.content so the "
            "explanation is written before the round block"
        )
    argv = ["explain", "--file", note_file, "--content-file", "-"]
    if exists or explain.get("update"):
        argv.append("--update")
    run_note(cli, argv, content)


def validate_note(note: dict[str, Any]) -> None:
    """Reject a malformed note payload before anything is written."""
    if not isinstance(note.get("file"), str) or not note.get("file", "").strip():
        raise RecordError("note.file is required")
    if not DATE_PATTERN.match(str(note.get("date") or "")):
        raise RecordError("note.date must look like YYYY-MM-DD")
    if not TIME_PATTERN.match(str(note.get("time") or "")):
        raise RecordError("note.time must look like HH:MM")
    kind = str(note.get("kind") or "复习")
    if kind not in ROUND_KINDS:
        raise RecordError(f"note.kind must be one of {ROUND_KINDS}")
    body = note.get("body")
    if not isinstance(body, str) or not body.strip():
        raise RecordError(
            "note.body is required: the round block body without the '# heading' line"
        )


def explain_entry(item: Any, field: str) -> tuple[str, str]:
    """Read one ``explain_sections`` / ``explain_parts`` entry; both share one rule."""
    if not isinstance(item, dict):
        raise RecordError(f"each {field} entry must be an object with 'title' and 'content'")
    title = str(item.get("title") or "").strip()
    content = str(item.get("content") or "").strip()
    if not title.startswith("## ") or not content:
        raise RecordError(f"each {field} entry needs a '## ' title and content")
    return title, content


def write_note(note: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    """Ensure the explanation exists, then append the round block and its sections."""
    validate_note(note)
    # validate_note 已经校验并挡住了缺字段：这里只做取值，不再重复一套规则
    note_file = str(note["file"])
    date = str(note["date"])
    time = str(note["time"])
    kind = str(note.get("kind") or "复习")
    body = str(note["body"])

    cli = note_cli_path(repo_root)
    result: dict[str, Any] = {"file": note_file}

    exists = True
    try:
        sections = run_note(cli, ["sections", "--file", note_file])
    except RecordError:
        exists = False
        sections = {}
    result["note_existed"] = exists

    if not exists or not sections.get("has_explanation"):
        explain = note.get("explain")
        if not isinstance(explain, dict):
            raise RecordError(
                "the note has no file-level '## 讲解'; supply note.explain.content so the "
                "explanation is written before the round block"
            )
        write_explanation(cli, note_file, explain, exists=exists)
        result["explain_written"] = True

    block = f"# {date} {time} · {kind}\n\n{body.strip()}\n"
    appended = run_note(cli, ["append", "--file", note_file, "--content-file", "-"], block)
    result["block"] = {
        "heading": appended.get("heading"),
        "appended": appended.get("appended"),
        "duplicate": appended.get("duplicate", False),
        "section_renamed": appended.get("section_renamed") or [],
        "heading_adjusted": appended.get("heading_adjusted", False),
    }

    if appended.get("duplicate"):
        # 这一轮已经落过盘：讲解区小节也必须保持原样，再追加一次会多存一份故事 / 对话原文
        result["already_saved"] = True
        if note.get("explain_sections") or note.get("explain_parts"):
            result["skipped_explain"] = True
        return result

    for item in note.get("explain_sections") or []:
        title, content = explain_entry(item, "explain_sections")
        argv = ["append-explain-section", "--file", note_file, "--content-file", "-"]
        if item.get("rewrite"):
            argv.append("--rewrite")
        written = run_note(cli, argv, content)
        # 同名小节已存在就是这个菜单项已经记录过：除场景对话与小故事外不再重复记录，
        # 另一段故事 / 对话要用 explain_parts 显式说明，不能靠这里自动补段。
        result.setdefault("explain_sections", []).append(
            {
                "title": written.get("section") or title,
                "duplicate": bool(written.get("duplicate")),
            }
        )

    for item in note.get("explain_parts") or []:
        title, content = explain_entry(item, "explain_parts")
        run_note(
            cli,
            [
                "append-explain-part",
                "--file",
                note_file,
                "--section",
                title,
                "--content-file",
                "-",
            ],
            section_body(content, title),
        )
        result.setdefault("explain_parts", []).append({"title": title})

    return result


def finish_round(
    payload: dict[str, Any], service: Any, repo_root: Path
) -> dict[str, Any]:
    """Run the whole round in one call and keep partial results when a step fails."""
    if not isinstance(payload, dict):
        raise RecordError("review-round input must be an object")
    result: dict[str, Any] = {"ok": True, "steps": []}

    review = payload.get("review")
    if review is not None:
        if not isinstance(review, dict):
            raise RecordError("review must be an object")
        try:
            score = float(review.get("score", -1))
        except (TypeError, ValueError) as exc:
            raise RecordError("review.score must be a number") from exc
        errors = review.get("errors", [])
        if not isinstance(errors, list):
            raise RecordError("review.errors must be an array")
        owner = review.get("claim_owner")
        token = review.get("claim_token")
        if owner is not None and not isinstance(owner, str):
            raise RecordError("review.claim_owner must be a string")
        if token is not None and not isinstance(token, str):
            raise RecordError("review.claim_token must be a string")
        result["review"] = service.complete_review(
            str(review.get("id", "")),
            score,
            errors,
            claim_owner=owner,
            claim_token=token,
        )
        result["steps"].append("review")

    note = payload.get("note")
    # 本轮记录被自动删除（已掌握记录连续三次 10 分）时，记录已经不在库里，笔记 md 保留：
    # 本轮不按记录口径补区块（追踪行无从取），笔记原样留在原处，之后仍可按路径练习。
    record_deleted = bool(
        isinstance(result.get("review"), dict) and result["review"].get("deleted")
    )
    if note is not None and record_deleted:
        result["note_skipped"] = {
            "reason": "record-auto-deleted",
            "record": result["review"].get("deleted_record"),
        }
    elif note is not None:
        if not isinstance(note, dict):
            raise RecordError("note must be an object")
        validate_note(note)
        try:
            result["note"] = write_note(note, repo_root)
        except RecordError as exc:
            result.update(
                ok=False,
                failed_step="note",
                error=str(exc),
                hint=(
                    "the record write above already happened; follow the failure-recovery "
                    "matrix instead of retrying the whole round"
                )
                if "review" in result["steps"]
                else None,
            )
            if payload.get("menu"):
                result["menu"] = _menu(payload["menu"], service)
            return result
        result["steps"].append("note")

    if payload.get("check", True) and "note" in result:
        check = note_check(
            note_cli_path(repo_root), result["note"]["file"], repo_root
        )
        result["check"] = check
        result["check_ok"] = check.get("ok")
        result["note_status"] = (
            "valid"
            if check.get("ok") is True
            else "invalid"
            if check.get("ok") is False
            else "unverified"
        )

    if payload.get("menu"):
        result["menu"] = _menu(payload["menu"], service)
        result["steps"].append("menu")
    return result


def _menu(menu: dict[str, Any], service: Any) -> dict[str, Any]:
    if not isinstance(menu, dict):
        raise RecordError("menu must be an object")
    return service.menu(
        menu.get("context", "review-complete"),
        focus=menu.get("focus"),
        current_exercise_explained=bool(menu.get("current_exercise_explained", False)),
        has_answer_errors=bool(menu.get("has_answer_errors", False)),
        grammar_explained=bool(menu.get("grammar_explained", False)),
    )
