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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import cache
from .models import RecordError


NOTES_DIR_NAME = "learning-record-notes"
LOCK_FILE_NAME = ".notes.lock"
SLUG_FILE_RE = re.compile(r"^[a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff\-]*\.md$")
HEADING_RE = re.compile(
    r"^# (?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}) · (?P<kind>复习|练习|套题|讲解)$"
)
DIVIDER = "---"
RECORD_ID_ROW_RE = re.compile(r"<tr><td>记录 ID / 试卷 ID</td><td>(.*?)</td></tr>")
UPDATED_ROW_RE = re.compile(r"<tr><td>笔记更新时间</td><td>[^<]*</td></tr>")
GENERATED_ROW_RE = re.compile(
    r"<tr><td>笔记生成时间</td><td>(\d{4}-\d{2}-\d{2} \d{2}:\d{2})</td></tr>"
)
# 文件级「基础信息」折叠块：整份笔记唯一一份，只随第一个区块一起写入
BASIC_HEAD_RE = re.compile(r"^## 基础信息\s*\n.*?(?=^# )", re.S | re.M)


def _split_head(text: str) -> tuple[str, str]:
    """把 基础信息 折叠块与轮次区块拆开：head 只在首次写入时落地。"""
    normalized = _normalize_text(text).strip("\n")
    match = BASIC_HEAD_RE.match(normalized)
    if not match:
        return "", normalized
    return match.group(0).rstrip("\n"), normalized[match.end() :].lstrip("\n")


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
            "note block must start with '# <YYYY-MM-DD> <HH:MM> · <复习|练习|套题|讲解>'"
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


def _comparable(text: str) -> str:
    """Normalize a block so trivial whitespace and separators do not register.

    ``_split_blocks`` keeps the ``---`` separator that follows a block, so a
    retried append inside a multi-round file must ignore it; otherwise the
    same round looks new and gets appended a second time under a bumped minute.
    """
    lines = [line.rstrip() for line in _normalize_text(text).strip("\n").split("\n")]
    while lines and (not lines[-1] or lines[-1] == "---"):
        lines.pop()
    return "\n".join(lines)


def _split_blocks(text: str) -> list[tuple[str, str]]:
    """Return ``(heading, block text)`` for each level-1 block in a note."""
    lines = _normalize_text(text).split("\n")
    starts = [index for index, line in enumerate(lines) if line.startswith("# ")]
    blocks: list[tuple[str, str]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        body = "\n".join(lines[start:end])
        blocks.append((lines[start].strip(), body))
    return blocks


def _sections(text: str) -> list[tuple[str, str]]:
    """Split a round block into its ``## section`` chunks, heading included."""
    lines = _normalize_text(text).split("\n")
    starts = [index for index, line in enumerate(lines) if line.startswith("## ")]
    chunks: list[tuple[str, str]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        body = "\n".join(lines[start:end]).rstrip("\n")
        chunks.append((lines[start].strip(), body))
    return chunks


def _next_free_heading(heading: str, existing: list[str]) -> str:
    """Give the incoming block a heading that keeps the file in ascending order.

    Two rounds can legitimately finish within the same minute (concurrent
    conversations, or a review followed by a practice). Reusing the heading
    would either drop the new block or overwrite the previous one, so the
    timestamp is moved to ``max(existing)+1min`` until it is both unique and
    monotonic.
    """
    match = HEADING_RE.match(heading)
    if not match:
        raise RecordError(f"note heading is invalid: {heading}")
    requested = datetime.strptime(
        f"{match.group('date')} {match.group('time')}", "%Y-%m-%d %H:%M"
    )
    latest = requested
    for existing_heading in existing:
        other = HEADING_RE.match(existing_heading.strip())
        if not other:
            continue
        stamp = datetime.strptime(
            f"{other.group('date')} {other.group('time')}", "%Y-%m-%d %H:%M"
        )
        if stamp > latest:
            latest = stamp
    candidate_stamp = max(requested, latest)
    taken = {item.strip() for item in existing}
    while True:
        candidate = (
            f"# {candidate_stamp.strftime('%Y-%m-%d %H:%M')} · {match.group('kind')}"
        )
        if candidate not in taken:
            return candidate
        candidate_stamp += timedelta(minutes=1)


def _swap_heading(block: str, heading: str) -> str:
    body = block.split("\n", 1)
    return heading if len(body) == 1 else f"{heading}\n{body[1]}"


def _bump_updated_at(text: str, when: datetime) -> str:
    """Rewrite the file-level `笔记更新时间` whenever the note file changes.

    Every append, block replace, or section insert edits the file, so the field
    must show that moment; leaving it at the first write made the stamp look
    like the note never changed. The stamp never goes below the newest round
    heading, which keeps it monotonic even when a block is saved under a
    bumped minute.
    """
    normalized = _normalize_text(text)
    if not UPDATED_ROW_RE.search(normalized):
        return normalized
    latest = when
    for pattern in (GENERATED_ROW_RE, HEADING_RE):
        for line in normalized.split("\n"):
            match = pattern.match(line.strip())
            if not match:
                continue
            stamp_text = (
                f"{match.group('date')} {match.group('time')}"
                if pattern is HEADING_RE
                else match.group(1)
            )
            stamp = datetime.strptime(stamp_text, "%Y-%m-%d %H:%M")
            if stamp > latest:
                latest = stamp
    return UPDATED_ROW_RE.sub(
        f"<tr><td>笔记更新时间</td><td>{latest.strftime('%Y-%m-%d %H:%M')}</td></tr>",
        normalized,
        count=1,
    )


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
    def _lock_handle(handle: Any) -> Any:
        # POSIX 分支有并发用例覆盖；Windows 分支只在无 fcntl 的平台走到，
        # 无法在 CI（Ubuntu / macOS）里验证，改动该分支时需手工确认。
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

    def _write(self, path: Path, text: str) -> None:
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
        # the snapshot must never describe a file this write just changed
        try:
            cache.refresh_note(self.repo_root, path, text)
        except OSError:
            cache.invalidate(self.repo_root)

    # -- public operations ----------------------------------------------
    def find_note_for_record(self, record_id: str) -> str | None:
        for entry in self.list_notes(record_id):
            if entry["record_id"] == record_id:
                return entry["file"]
        return None

    def append(self, path: str, content: str) -> dict[str, Any]:
        target = self.resolve(path)
        head, raw_block = _split_head(content)
        block = _normalize_block(raw_block)
        declared = RECORD_ID_ROW_RE.search(content)
        if declared and not target.exists():
            tracked = self.find_note_for_record(declared.group(1).strip())
            if tracked and tracked != self.relative(target):
                raise RecordError(
                    f"record {declared.group(1).strip()} already has a note at {tracked}; "
                    f"append to that file instead of creating {self.relative(target)}"
                )
        requested_heading = _block_heading(block)
        with self._exclusive_lock():
            existing = self._read(target)
            existing_blocks = _split_blocks(existing)
            headings = [item[0] for item in existing_blocks]
            if requested_heading in headings:
                written = next(
                    item for item in existing_blocks if item[0] == requested_heading
                )
                if _comparable(written[1]) == _comparable(block):
                    return {
                        "ok": True,
                        "appended": False,
                        "duplicate": True,
                        "heading_adjusted": False,
                        "requested_heading": requested_heading,
                        "hint": (
                            "this round is already saved with identical content; do not "
                            "append again and do not rewrite it"
                        ),
                        "file": self.relative(target),
                        "heading": requested_heading,
                        "blocks": _count_blocks(existing),
                    }
            heading = _next_free_heading(requested_heading, headings)
            adjusted = heading != requested_heading
            if adjusted:
                block = _swap_heading(block, heading)
            body = _normalize_text(existing).rstrip("\n")
            # 历史区块之间缺少分隔符时只追加本轮，不回填历史，
            # 以免“整理旧格式”改写别的会话已经写下的内容。
            if not body.strip():
                if not head:
                    raise RecordError(
                        "a new note must start with the file-level `## 基础信息` section "
                        "(记录 ID / 试卷 ID、目标知识点、累计复习次数、下次复习、笔记生成时间、笔记更新时间)"
                    )
                composed = f"{head}\n\n{block}"
            elif _ends_with_divider(body):
                composed = f"{body}\n\n{block}"
            else:
                composed = f"{body}\n\n{DIVIDER}\n\n{block}"
            composed = _bump_updated_at(composed, datetime.now())
            self._write(target, composed)
            blocks = _count_blocks(composed)
        return {
            "ok": True,
            "appended": True,
            "duplicate": False,
            "heading_adjusted": adjusted,
            "requested_heading": requested_heading,
            "hint": (
                f"{requested_heading} is already taken or would break the ascending order; "
                f"this block was saved as {heading} instead, with both rounds kept"
                if adjusted
                else None
            ),
            "file": self.relative(target),
            "heading": heading,
            "blocks": blocks,
            "bytes": len(composed.encode("utf-8")),
        }

    def replace_block(
        self,
        path: str,
        heading: str,
        content: str,
        allow_drop: tuple[str, ...] = (),
        allow_sections: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        target = self.resolve(path)
        # 替换只针对轮次区块；模型若顺手带了文件级基础信息头，直接忽略避免重复
        _head, raw_block = _split_head(content)
        block = _normalize_block(raw_block)
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
            # 替换是整块覆盖，而同一个区块会被多个会话持续追加小节，
            # 所以锁内把「旧有但新内容没带上」的小节原样保留在区块末尾，
            # 只有调用方显式列出的小节才允许真的删掉。
            existing_sections = _sections("\n".join(lines[start:end]))
            replacement_sections = {heading for heading, _ in _sections(block)}
            preserved = [
                (section_heading, body)
                for section_heading, body in existing_sections
                if section_heading not in replacement_sections
                and section_heading not in allow_drop
            ]
            tail = lines[end:]
            before = lines[:start]
            # Keep the divider that separated the replaced block from the next one.
            while tail and not tail[0].strip():
                tail.pop(0)
            replacement = block.split("\n")[:-1]
            for _section_heading, body in preserved:
                replacement = replacement + ["", *body.split("\n")]
            if tail:
                replacement = replacement + ["", DIVIDER, ""] + tail
            # 一次替换只允许改一个小节：改多个小节意味着在别人的小节里动刀，
            # 必须由调用方逐个用 --rewrite-section 声明（批量迁移才这么做），
            # 否则一次范围写宽的替换会静默吃掉整段内容。
            new_sections = {heading_text: body_text for heading_text, body_text in _sections("\n".join(replacement))}
            modified = [
                heading_text
                for heading_text, body_text in existing_sections
                if heading_text in new_sections
                and _comparable(new_sections[heading_text]) != _comparable(body_text)
            ]
            undeclared = [
                heading_text
                for heading_text in modified
                if heading_text not in allow_sections
            ]
            if len(undeclared) > 1:
                raise RecordError(
                    "replacement would rewrite "
                    f"{len(undeclared)} sections at once: "
                    + ", ".join(undeclared)
                    + "; 一次只改一个小节，要批量迁移请对每个小节显式加 --rewrite-section"
                )
            composed = "\n".join(before + replacement).rstrip("\n") + "\n"
            composed = _bump_updated_at(composed, datetime.now())
            self._write(target, composed)
            blocks = _count_blocks(composed)
        return {
            "ok": True,
            "replaced": True,
            "file": self.relative(target),
            "heading": wanted,
            "blocks": blocks,
            "modified_sections": modified,
            "preserved_sections": [section_heading for section_heading, _ in preserved],
            "bytes": len(composed.encode("utf-8")),
        }

    def append_section(
        self, path: str, heading: str, content: str
    ) -> dict[str, Any]:
        """Insert one ``## section`` (a menu follow-up) into an existing round block.

        Menus keep adding sections to the same date block from several
        conversations. Rebuilding the whole block to add one section is what
        used to drop another session's work, so adding a section gets its own
        lock-protected operation: the existing block is read under the lock,
        the new section is appended to it, and nothing else is touched.
        """
        target = self.resolve(path)
        section = _normalize_text(content).strip("\n")
        if not section:
            raise RecordError("note section is empty")
        first = section.split("\n")[0].strip()
        if not first.startswith("## "):
            raise RecordError("a note section must start with a '## ' heading")
        for line in section.split("\n")[1:]:
            if line.startswith("# "):
                raise RecordError(
                    "a note section cannot contain a level-1 heading; "
                    "sections are added inside an existing round block"
                )
        section_heading = first
        wanted = _normalize_text(heading).strip()
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
                    f"heading appears {len(matches)} times; refusing an ambiguous append: {wanted}"
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
            block_lines = lines[start:end]
            for existing_heading, body in _sections("\n".join(block_lines)):
                if existing_heading != section_heading:
                    continue
                if _comparable(body) == _comparable(section):
                    return {
                        "ok": True,
                        "appended_section": False,
                        "duplicate": True,
                        "file": self.relative(target),
                        "heading": wanted,
                        "section": section_heading,
                        "hint": "this section is already in the block; do not append it again",
                    }
                raise RecordError(
                    f"section {section_heading} already exists in this block; "
                    "replace the block (sections that are missing from the new content "
                    "are preserved) instead of adding a second one"
                )
            block_end = end
            while end > start + 1 and not lines[end - 1].strip():
                end -= 1
            tail = lines[block_end:]
            before = lines[:end]
            body = [""] + section.split("\n")
            if tail:
                body = body + ["", DIVIDER, ""] + tail
            composed = "\n".join(before + body).rstrip("\n") + "\n"
            composed = _bump_updated_at(composed, datetime.now())
            self._write(target, composed)
            blocks = _count_blocks(composed)
        return {
            "ok": True,
            "appended_section": True,
            "duplicate": False,
            "file": self.relative(target),
            "heading": wanted,
            "section": section_heading,
            "blocks": blocks,
            "bytes": len(composed.encode("utf-8")),
        }

    def list_notes(self, record_id: str | None = None) -> list[dict[str, Any]]:
        """List note blocks, optionally filtered by the record id they track.

        Cheap path first: a snapshot entry is only trusted while the file's
        ``size``/``mtime`` still match, so a file edited outside this tool
        falls back to a real parse instead of returning a stale heading list.
        """
        if not self.notes_dir.is_dir():
            return []
        snapshot = cache.get_snapshot(self.repo_root)
        entries: list[dict[str, Any]] = []
        for path in sorted(self.notes_dir.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            relative = self.relative(path)
            cached = cache.note_entry_current(self.repo_root, snapshot, relative)
            if cached is not None:
                blocks = [
                    (block["heading"], block.get("record_id"))
                    for block in cached["blocks"]
                ]
                file_record = cached["record_id"]
            else:
                text = path.read_text(encoding="utf-8")
                blocks = [
                    (
                        heading,
                        (lambda m: m.group(1).strip() if m else None)(
                            RECORD_ID_ROW_RE.search(block)
                        ),
                    )
                    for heading, block in _split_blocks(text)
                ]
                file_record = self._file_record_id(text)
            for heading, block_record in blocks:
                # 区块内的记录 ID 行优先于文件级，与真实解析同口径
                tracked = block_record if block_record is not None else file_record
                if record_id is not None and tracked != record_id:
                    continue
                entries.append(
                    {"file": relative, "heading": heading, "record_id": tracked}
                )
        return entries

    @staticmethod
    def _file_record_id(text: str) -> str | None:
        # 记录 ID 在文件顶部的「基础信息」里，不在任何轮次区块内
        match = RECORD_ID_ROW_RE.search(text)
        return match.group(1).strip() if match else None

    def sections(self, path: str, *, heading: str | None = None) -> dict[str, Any]:
        """Read-only index of a note's round blocks and their `##` sections.

        Answers "does this section already exist?" from the cached index, so a
        caller never has to compose a full section and discover the conflict
        only when the write is rejected.
        """
        target = self.resolve(path)
        if not target.is_file():
            raise RecordError(f"note does not exist: {self.relative(target)}")
        relative = self.relative(target)
        snapshot = cache.get_snapshot(self.repo_root)
        entry = cache.note_entry_current(self.repo_root, snapshot, relative)
        if entry is None:
            entry = cache.note_entry(target, repo_root=self.repo_root)
            # 让下一次读取命中缓存；写缓存失败不影响本次结果
            try:
                cache.refresh_note(
                    self.repo_root, target, target.read_text(encoding="utf-8")
                )
            except OSError:
                pass
        blocks = [
            {
                "heading": block["heading"],
                "sections": list(block["sections"]),
            }
            for block in entry["blocks"]
            if heading is None or block["heading"] == heading
        ]
        return {
            "file": relative,
            "record_id": entry["record_id"],
            "blocks": blocks,
            "block_count": len(entry["blocks"]),
        }

    def check(self, path: str, *, fix: bool = False) -> dict[str, Any]:
        target = self.resolve(path)
        checker = self.checker_path
        if not checker.is_file():
            return {"ok": None, "skipped": "validator script not found", "issues": []}
        try:
            completed = subprocess.run(
                [sys.executable, str(checker), str(target), *(["--fix"] if fix else [])],
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
