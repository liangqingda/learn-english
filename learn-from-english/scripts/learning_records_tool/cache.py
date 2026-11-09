"""Cached, read-only view of the notes directory for cheap session lookups.

Every review round used to start by shelling out ``ls``, ``grep`` and
``git log`` to find out where the repository stands: which note file tracks a
record, which round blocks and ``##`` sections that file already has, and what
commit the working tree sits on. Those answers only change when something
writes, so they are cached here instead of being re-derived on every turn.

The snapshot is strictly an acceleration layer:

* it never feeds a write decision that could corrupt a note, because every
  read revalidates the referenced file's ``mtime`` and ``size`` before the
  cached entry is trusted;
* note writes now live in the ``take-english-study-notes`` skill and no longer refresh this
  snapshot (``refresh_note`` stays available for callers that still hold an
  entry, but nothing in this package calls it);
* a stale snapshot is simply rebuilt, so deleting the cache file is always
  safe.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


NOTES_DIR_NAME = "learning-record-notes"
CACHE_DIR_NAME = ".cache"
CACHE_FILE_NAME = "snapshot.json"
SNAPSHOT_SCHEMA = 1
# 会话默认有效期：30 分钟。超过后重新读取仓库，避免与其它会话的写入漂移。
DEFAULT_MAX_AGE_SECONDS = 30 * 60

RECORD_ID_ROW_RE = re.compile(r"<tr><td>记录 ID / 试卷 ID</td><td>(.*?)</td></tr>")
HEADING_RE = re.compile(
    r"^# (?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}) · (?P<kind>复习|练习|套题)$"
)


def cache_path(repo_root: Path | str) -> Path:
    return Path(repo_root).resolve() / CACHE_DIR_NAME / CACHE_FILE_NAME


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def git_head(repo_root: Path) -> str | None:
    """Short HEAD hash, or ``None`` when this is not a git work tree."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def note_entry(path: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Describe one note file by reading it from disk."""
    return note_entry_from_text(
        path, path.read_text(encoding="utf-8"), repo_root=repo_root
    )


def note_entry_from_text(
    path: Path, text: str, *, repo_root: Path | None = None
) -> dict[str, Any]:
    """Build the index entry from text the caller already holds.

    The writer passes the exact text it just published, so a refresh never
    re-reads the file (and never risks describing a half-written state).
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    stat = path.stat()
    record = RECORD_ID_ROW_RE.search(normalized)
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    chunk: list[str] = []
    for line in normalized.split("\n"):
        if line.startswith("# "):
            if current is not None:
                block_match = RECORD_ID_ROW_RE.search("\n".join(chunk))
                current["record_id"] = (
                    block_match.group(1).strip() if block_match else None
                )
            heading = line.strip()
            match = HEADING_RE.match(heading)
            current = {
                "heading": heading,
                "kind": match.group("kind") if match else None,
                "sections": [],
                "record_id": None,
            }
            blocks.append(current)
            chunk = [line]
        elif current is not None:
            chunk.append(line)
            if line.startswith("## "):
                current["sections"].append(line.strip())
    if current is not None:
        block_match = RECORD_ID_ROW_RE.search("\n".join(chunk))
        current["record_id"] = block_match.group(1).strip() if block_match else None
    relative = (
        str(path.resolve().relative_to(repo_root))
        if repo_root is not None
        else str(path)
    )
    return {
        "file": relative,
        "record_id": record.group(1).strip() if record else None,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "blocks": blocks,
    }


def build_snapshot(repo_root: Path | str) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    notes_dir = root / NOTES_DIR_NAME
    notes: dict[str, Any] = {}
    record_files: dict[str, str] = {}
    if notes_dir.is_dir():
        for path in sorted(notes_dir.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            try:
                entry = note_entry(path, repo_root=root)
            except OSError:
                continue
            notes[entry["file"]] = entry
            if entry["record_id"]:
                record_files.setdefault(entry["record_id"], entry["file"])
    return {
        "schema": SNAPSHOT_SCHEMA,
        "generated_at": _now_iso(),
        "git_head": git_head(root),
        "notes": notes,
        "record_files": record_files,
        "counts": {
            "files": len(notes),
            "blocks": sum(len(entry["blocks"]) for entry in notes.values()),
        },
    }


def _write_snapshot(repo_root: Path, snapshot: dict[str, Any]) -> None:
    target = cache_path(repo_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".snapshot.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def load_snapshot(repo_root: Path | str) -> dict[str, Any] | None:
    target = cache_path(repo_root)
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def invalidate(repo_root: Path | str) -> None:
    """Drop the cached snapshot; the next read rebuilds it."""
    try:
        cache_path(repo_root).unlink()
    except FileNotFoundError:
        pass


def _age_seconds(snapshot: dict[str, Any]) -> float:
    stamp = snapshot.get("generated_at")
    if not isinstance(stamp, str):
        return float("inf")
    try:
        parsed = datetime.fromisoformat(stamp)
        now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
        return max(0.0, (now - parsed).total_seconds())
    except (TypeError, ValueError):
        return float("inf")


def get_snapshot(
    repo_root: Path | str,
    *,
    refresh: bool = False,
    max_age: float = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Return a usable snapshot, rebuilding it when missing or too old."""
    root = Path(repo_root).resolve()
    cached = None if refresh else load_snapshot(root)
    age = _age_seconds(cached) if cached is not None else float("inf")
    if cached is not None and cached.get("schema") == SNAPSHOT_SCHEMA and age <= max_age:
        cached["age_seconds"] = round(age, 1)
        cached["source"] = "cache"
        return cached
    snapshot = build_snapshot(root)
    try:
        _write_snapshot(root, snapshot)
    except OSError:
        pass
    snapshot["age_seconds"] = 0.0
    snapshot["source"] = "rebuild"
    return snapshot


def note_entry_current(
    repo_root: Path | str, snapshot: dict[str, Any], file: str
) -> dict[str, Any] | None:
    """Return the cached entry only if the file still matches its stat."""
    entry = snapshot.get("notes", {}).get(file)
    if not entry:
        return None
    target = Path(repo_root).resolve() / file
    try:
        stat = target.stat()
    except OSError:
        return None
    if stat.st_size != entry.get("size") or stat.st_mtime != entry.get("mtime"):
        return None
    return entry


def refresh_note(repo_root: Path | str, path: Path, text: str) -> None:
    """Update the cached entry for one just-written note file.

    Called from the writer, so the snapshot never describes a file that has
    already moved on. A missing snapshot stays missing: a write is not a
    reason to build one.
    """
    root = Path(repo_root).resolve()
    target = cache_path(root)
    if not target.exists():
        return
    snapshot = load_snapshot(root)
    if snapshot is None or snapshot.get("schema") != SNAPSHOT_SCHEMA:
        return
    try:
        entry = note_entry_from_text(path, text, repo_root=root)
    except OSError:
        invalidate(root)
        return
    notes = snapshot.setdefault("notes", {})
    notes[entry["file"]] = entry
    record_files = snapshot.setdefault("record_files", {})
    if entry["record_id"]:
        record_files[entry["record_id"]] = entry["file"]
    snapshot.setdefault("counts", {})
    snapshot["counts"]["files"] = len(notes)
    snapshot["counts"]["blocks"] = sum(len(item["blocks"]) for item in notes.values())
    # 写入不改变 HEAD，也不续期 generated_at：快照照常 30 分钟后重建，
    # 期间 HEAD 的变化由 snapshot 命令的实时比对暴露。
    try:
        _write_snapshot(root, snapshot)
    except OSError:
        invalidate(root)
