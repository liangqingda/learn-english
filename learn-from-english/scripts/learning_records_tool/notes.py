"""Lock-protected append and replace for human-readable review notes.

Notes under ``learning-record-notes/`` are a readable copy, not a canonical
data source, so they are never validated by the record store. They are still
written by several conversations at once, which makes a plain
read-modify-write cycle destructive: two sessions that both read the same
file and then write it back silently drop one round.

This module owns every note mutation and makes the whole cycle exclusive:
a single advisory ``flock`` on ``learning-record-notes/.notes.lock`` covers
read, compose, and the atomic ``os.replace`` that publishes the new file.
Callers never rewrite the file themselves.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import RecordError


NOTES_DIR_NAME = "learning-record-notes"
LOCK_FILE_NAME = ".notes.lock"
SLUG_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.md$")
HEADING_RE = re.compile(
    r"^# (?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}) · (?P<kind>复习|练习|套题)$"
)
DIVIDER = "---"


def _normalize_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _normalize_block(text: str) -> str:
    """Return the block as a heading first, trailing-newline terminated chunk."""
    block = _normalize_text(text).strip("\n")
    lines = block.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        raise RecordError("note block is empty")
    if not HEADING_RE.match(lines[0].strip()):
        raise RecordError(
            "note block must start with '# <YYYY-MM-DD> <HH:MM> · <复习|练习|套题>'"
        )
    for line in lines[1:]:
        if line.startswith("# "):
            raise RecordError(
                "one append must contain exactly one round block; "
                "a second level-1 heading was found"
            )
    return "\n".join(lines).rstrip("\n") + "\n"


def _block_heading(block: str) -> str:
    return block.split("\n", 1)[0].strip()


def _ends_with_divider(text: str) -> bool:
    stripped = text.rstrip("\n")
    return stripped.split("\n")[-1].strip() == DIVIDER


def _count_blocks(text: str) -> int:
    return sum(1 for line in _normalize_text(text).split("\n") if line.startswith("# "))


class NoteStore:
    """Exclusive, atomic access to the notes directory."""

    def __init__(self, repo_root: Path, checker_path: Path | None = None):
        self.repo_root = Path(repo_root).resolve()
        self.notes_dir = self.repo_root / NOTES_DIR_NAME
        self.lock_path = self.notes_dir / LOCK_FILE_NAME
        if checker_path is not None:
            self.checker_path = Path(checker_path).resolve()
        else:
            self.checker_path = self._default_checker()

    def _default_checker(self) -> Path:
        """Prefer the validator next to the given repo, then the installed one."""
        repo_candidate = (
            self.repo_root / "practice-learning-records" / "scripts" / "check_note.py"
        )
        if repo_candidate.is_file():
            return repo_candidate
        installed = (
            Path(__file__).resolve().parents[3]
            / "practice-learning-records"
            / "scripts"
            / "check_note.py"
        )
        return repo_candidate if not installed.is_file() else installed

    # -- path handling ---------------------------------------------------
    def resolve(self, path: str) -> Path:
        raw = Path(path).expanduser()
        if raw.is_absolute():
            candidate = raw
        elif raw.parent == Path("."):
            candidate = self.notes_dir / raw.name
        else:
            candidate = self.repo_root / raw
        if candidate.is_symlink():
            raise RecordError("refusing to write through a symbolic link")
        target = candidate.resolve()
        notes_dir = self.notes_dir.resolve()
        if target.parent != notes_dir:
            raise RecordError(
                f"note path must live directly under {NOTES_DIR_NAME}/: {path}"
            )
        if not SLUG_FILE_RE.match(target.name):
            raise RecordError(
                "note file name must look like <category>-<slug>.md "
                "(lowercase letters, digits, and hyphens only)"
            )
        if target.exists() and not target.is_file():
            raise RecordError(f"note path is not a regular file: {path}")
        return target

    def relative(self, target: Path) -> str:
        return f"{NOTES_DIR_NAME}/{target.name}"

    # -- locking and atomic publication ---------------------------------
    @contextmanager
    def _exclusive_lock(self):
        """Cross-process exclusive lock, POSIX ``flock`` with a Windows fallback.

        Imported lazily so the rest of the CLI still works where ``fcntl`` is
        missing; without any lock available, refuse to write rather than risk
        silently dropping another session's round.
        """
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            release = self._lock_handle(handle)
            try:
                yield
            finally:
                release()

    @staticmethod
    def _lock_handle(handle) -> Any:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - Windows only
            try:
                import msvcrt
            except ImportError as exc:
                raise RecordError(
                    "this platform provides no file locking; refusing to write notes"
                ) from exc
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

            def unlock() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

            return unlock
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

        def unlock() -> None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        return unlock

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except OSError as exc:
            raise RecordError(f"cannot read note {path}: {exc}") from exc

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_name, mode)
            os.replace(temporary_name, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    # -- public operations ----------------------------------------------
    def append(self, path: str, content: str) -> dict[str, Any]:
        target = self.resolve(path)
        block = _normalize_block(content)
        heading = _block_heading(block)
        with self._exclusive_lock():
            existing = self._read(target)
            if heading in existing.split("\n"):
                return {
                    "ok": True,
                    "appended": False,
                    "duplicate": True,
                    "file": self.relative(target),
                    "heading": heading,
                    "blocks": _count_blocks(existing),
                }
            body = _normalize_text(existing).rstrip("\n")
            if not body.strip():
                composed = block
            elif _ends_with_divider(body):
                composed = f"{body}\n\n{block}"
            else:
                composed = f"{body}\n\n{DIVIDER}\n\n{block}"
            self._write(target, composed)
            blocks = _count_blocks(composed)
        return {
            "ok": True,
            "appended": True,
            "duplicate": False,
            "file": self.relative(target),
            "heading": heading,
            "blocks": blocks,
            "bytes": len(composed.encode("utf-8")),
        }

    def replace_block(self, path: str, heading: str, content: str) -> dict[str, Any]:
        target = self.resolve(path)
        block = _normalize_block(content)
        wanted = _normalize_text(heading).strip()
        if _block_heading(block) != wanted:
            raise RecordError(
                "replacement block must keep the original heading line unchanged"
            )
        with self._exclusive_lock():
            existing = _normalize_text(self._read(target))
            if not existing:
                raise RecordError(f"note does not exist: {self.relative(target)}")
            lines = existing.split("\n")
            matches = [index for index, line in enumerate(lines) if line.strip() == wanted]
            if not matches:
                raise RecordError(f"heading not found in note: {wanted}")
            if len(matches) > 1:
                raise RecordError(
                    f"heading appears {len(matches)} times; refusing an ambiguous replace: {wanted}"
                )
            start = matches[0]
            end = next(
                (
                    index
                    for index in range(start + 1, len(lines))
                    if lines[index].startswith("# ")
                ),
                len(lines),
            )
            tail = lines[end:]
            before = lines[:start]
            # Keep the divider that separated the replaced block from the next one.
            while tail and not tail[0].strip():
                tail.pop(0)
            replacement = block.split("\n")[:-1]
            if tail:
                replacement = replacement + ["", DIVIDER, ""] + tail
            composed = "\n".join(before + replacement).rstrip("\n") + "\n"
            self._write(target, composed)
            blocks = _count_blocks(composed)
        return {
            "ok": True,
            "replaced": True,
            "file": self.relative(target),
            "heading": wanted,
            "blocks": blocks,
            "bytes": len(composed.encode("utf-8")),
        }

    def check(self, path: str) -> dict[str, Any]:
        target = self.resolve(path)
        checker = self.checker_path
        if not checker.is_file():
            return {"ok": None, "skipped": "validator script not found", "issues": []}
        try:
            completed = subprocess.run(
                [sys.executable, str(checker), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise RecordError(f"cannot run note validator: {exc}") from exc
        try:
            report = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            raise RecordError(
                f"note validator returned unreadable output: {completed.stdout.strip()}"
            ) from None
        return report
