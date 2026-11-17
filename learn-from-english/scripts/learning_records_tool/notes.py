"""删一篇复习笔记，连同它在记录库里的那条记录。

为什么删笔记也要走脚本：笔记是记录的可读副本，两者必须一起消失；记录那一半的写入
（锁、revision、未掌握 / 已掌握拆分、原子替换）只能由 ``RecordStore`` 做，
任何调用方自己改 ``learning-records/*.json`` 都会绕开这套约束。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .cache import invalidate
from .models import CATEGORIES, RecordError
from .service import RecordService


NOTES_DIR = "learning-record-notes"
NOTE_SUFFIX = ".md"
# 「基础信息」表里的记录行：`<tr><td>记录 ID / 试卷 ID</td><td>errors:foo</td></tr>`
# 一行取不到就当作「这篇没有记录（如试卷笔记先不认）」，不靠猜。
RECORD_ID_RE = re.compile(r"记录 ID[^<]{0,40}</td>\s*<td>\s*([^<]*?)\s*</td>")
RECORD_ID_FORMAT_RE = re.compile(r"([a-z]+):([a-z0-9]+(?:-[a-z0-9]+)*)")
# 没有 categories.json 时的兜底：五个记录分类 + 套题
FALLBACK_CATEGORIES = (*CATEGORIES, "paper")


class NoteDeletionService:
    """校验笔记路径、读出它的记录 ID，再按记录 ID 让记录服务删那一条。"""

    def __init__(self, repo_root: Path, records: RecordService):
        self.repo_root = Path(repo_root).resolve()
        self.notes_dir = self.repo_root / NOTES_DIR
        self.records = records

    def categories(self) -> tuple[str, ...]:
        """笔记允许的分类：以 ``learning-record-notes/categories.json`` 为准。"""
        config_path = self.notes_dir / "categories.json"
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return FALLBACK_CATEGORIES
        entries = config.get("categories") if isinstance(config, dict) else None
        keys = tuple(
            entry["key"]
            for entry in entries or []
            if isinstance(entry, dict) and isinstance(entry.get("key"), str)
        )
        return keys or FALLBACK_CATEGORIES

    def resolve(self, note: str) -> Path:
        """把入参收敛成 ``learning-record-notes/<category>/<category>-<slug>.md``。"""
        raw = Path(note)
        path = raw if raw.is_absolute() else self.repo_root / raw
        path = path.resolve()
        if self.notes_dir not in path.parents:
            raise RecordError(f"note must live under {NOTES_DIR}/: {note}")
        if path.suffix != NOTE_SUFFIX:
            raise RecordError(f"note must be a {NOTE_SUFFIX} file: {note}")
        category = path.parent.name
        if category not in self.categories():
            raise RecordError(
                f"note directory must be one of: {', '.join(self.categories())}: {note}"
            )
        if not path.name.startswith(f"{category}-"):
            raise RecordError(
                f"note file name must start with `{category}-`: {path.name}"
            )
        if not path.is_file():
            raise RecordError(f"note does not exist: {note}")
        return path

    @staticmethod
    def record_id_from_text(text: str) -> str:
        match = RECORD_ID_RE.search(text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def record_category(record_id: str) -> str | None:
        """记录 ID 的分类前缀；不是 ``<五类记录分类>:<key>`` 的（如试卷 ID）返回 None。"""
        match = RECORD_ID_FORMAT_RE.fullmatch(record_id)
        if not match or match.group(1) not in CATEGORIES:
            return None
        return match.group(1)

    def _record_target(self, path: Path, record_id: str) -> str | None:
        """确认这条记录确实属于这篇笔记；属于就回分类，不属于回 None。

        只在「分类一致 + key 与文件名对得上」时才删记录：笔记里的 ID 写错或过期时
        宁可留着记录并说明原因，也不能顺着一个错 ID 删掉别人的知识点。
        """
        category = self.record_category(record_id)
        if category is None or category != path.parent.name:
            return None
        # record_category 已经确认过 `<category>:<key>` 的形态，这里直接取 key
        key = record_id.split(":", 1)[1]
        if f"{category}-{key}{NOTE_SUFFIX}" != path.name:
            return None
        return category

    def delete(self, note: str) -> dict[str, Any]:
        """删掉笔记文件，再按记录 ID 删记录；记录那一半失败不掩盖笔记已删的事实。"""
        path = self.resolve(note)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RecordError(f"cannot read note {note}: {exc}") from exc
        record_id = self.record_id_from_text(text)
        category = self._record_target(path, record_id)
        record: dict[str, Any] | None = None
        record_error: str | None = None

        try:
            path.unlink()
        except OSError as exc:
            # 文件没删掉就什么都不算删过：记录一条都还没动，直接把原因抛出去
            raise RecordError(f"cannot delete note file {note}: {exc}") from exc
        invalidate(self.repo_root)

        if category is not None:
            try:
                deleted = self.records.delete_record(record_id, missing_ok=True)
            except RecordError as exc:
                record_error = str(exc)
            else:
                if deleted is not None:
                    # file 由记录服务给出：哪份 JSON 变了不在这一层再判一次
                    record = {
                        **deleted,
                        "mastered": deleted["status"] == "mastered",
                    }
        elif self.record_category(record_id) is not None:
            # 分类是学习记录、但 key 与文件名对不上：说明这条 ID 不属于这篇笔记
            record_error = (
                "记录 ID 与笔记文件不一致，已保留记录只删笔记："
                f"{record_id}"
            )

        return {
            "note": path.relative_to(self.repo_root).as_posix(),
            "note_deleted": True,
            "record_id": record_id,
            "record": record,
            "record_error": record_error,
        }
