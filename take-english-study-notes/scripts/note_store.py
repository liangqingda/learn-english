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

import hashlib
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



class NoteError(Exception):
    """Any refusal or failure raised by the note writer."""


NOTES_DIR_NAME = "learning-record-notes"
LOCK_FILE_NAME = ".notes.lock"
# 笔记按分类分目录存放（`learning-record-notes/errors/errors-xxx.md`），目录名就是文件名前缀；
# 分类键本身由 `learning-record-notes/categories.json` 定义、由 `check_note.py` 校验，
# 写入器只强制「目录名 == 文件名前缀」，不再抄一份分类表。
# slug 只允许小写 ASCII 字母、数字与连字符；中文主题要意译成英文短语（与 check_note 一致）。
SLUG_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*\.md$")
HEADING_RE = re.compile(
    r"^# (?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2}) · (?P<kind>复习|练习|套题)$"
)
DIVIDER = "---"
RECORD_ID_ROW_RE = re.compile(r"<tr><td>记录 ID / 试卷 ID</td><td>(.*?)</td></tr>")
UPDATED_ROW_RE = re.compile(r"<tr><td>笔记更新时间</td><td>[^<]*</td></tr>")
GENERATED_ROW_RE = re.compile(
    r"<tr><td>笔记生成时间</td><td>(\d{4}-\d{2}-\d{2} \d{2}:\d{2})</td></tr>"
)
# 记录级追踪行：累计复习次数与下次复习由规范记录决定，写入后自动回填，
# 不能让笔记顶部长期停在首轮手抄的旧值（append/replace 只写日期区块）。
ROUND_COUNT_ROW_RE = re.compile(r"<tr><td>累计复习次数</td><td>[^<]*</td></tr>")
NEXT_REVIEW_ROW_RE = re.compile(r"<tr><td>下次复习</td><td>[^<]*</td></tr>")
SYNCABLE_ROWS = {
    "累计复习次数": ROUND_COUNT_ROW_RE,
    "下次复习": NEXT_REVIEW_ROW_RE,
}
# 每个带习题的小节（含 `## 本轮习题`）的表格首行：这一节写进笔记的真实时刻。
# 它只在小节首次落盘时盖章，之后重写、补题、重建索引都原样保留；讲解区的
# `复习历史` 链接文案与锚点 id 都从这个值取时间，不再拿日期区块标题当时间来源。
GENERATED_AT_FIELD = "生成时间"
GENERATED_AT_ROW_RE = re.compile(
    r"<tr><td>\s*生成时间\s*</td><td>(?P<value>[^<]*)</td></tr>"
)
GENERATED_AT_STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
# 文件级「基础信息」折叠块：整份笔记唯一一份，只随第一个区块一起写入
BASIC_HEAD_RE = re.compile(r"^## 基础信息\s*\n.*?(?=^# )", re.S | re.M)
# 讲解是一个知识点唯一的一份说明，写成文件级小节，不参与轮次编号
EXPLAIN_SECTION = "讲解"
QUIZ_SECTION = "本轮习题"
EXPLAIN_HEAD_RE = re.compile(r"^## 讲解\s*$", re.M)


def filename_category(name: str) -> str | None:
    """文件名前缀，也就是它该待的分类目录名：`errors-out-west.md` → `errors`。

    没有连字符（如 `headquarters.md`）或前缀含数字说明缺分类前缀，返回 None。
    """
    stem = name[:-3] if name.endswith(".md") else name
    separator = stem.find("-")
    if separator <= 0:
        return None
    prefix = stem[:separator]
    return prefix if prefix.isalpha() else None


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
        raise NoteError("note block is empty")
    if not HEADING_RE.match(lines[0].strip()):
        raise NoteError(
            "note block must start with '# <YYYY-MM-DD> <HH:MM> · <复习|练习|套题>'"
        )
    for line in lines[1:]:
        if line.startswith("# "):
            raise NoteError(
                "one append must contain exactly one round block; "
                "a second level-1 heading was found"
            )
    return "\n".join(lines).rstrip("\n") + "\n"


def _block_heading(block: str) -> str:
    return block.split("\n", 1)[0].strip()


def _count_blocks(text: str) -> int:
    return sum(1 for line in _normalize_text(text).split("\n") if line.startswith("# "))


INDEX_START = "<!-- practice-index -->"
INDEX_END = "<!-- /practice-index -->"
ROUND_INDEX_START = "<!-- round-index -->"
ROUND_INDEX_END = "<!-- /round-index -->"
# 索引块的小标题：写在讲解内容之后、索引链接之前，渲染时显示成一行「复习历史：」
INDEX_TITLE = "复习历史："
INLINE_ANCHOR_RE = re.compile(
    r'\s*<a id="(?P<id>'
    r"practice-\d{4}-\d{2}-\d{2}-\d{4}-[0-9a-f]{8}(?:-\d{2})?"
    r"|round-\d{4}-\d{2}-\d{2}-\d{4}"
    r')"></a>$'
)
INDEX_LINE_RE = re.compile(r"^- \[[^\]]+\]\(#(?:practice|round)-[\w-]+\)$")


def _split_inline_anchor(title: str) -> tuple[str, str]:
    """标题行右侧的隐藏锚点：`## 小节 <a id="practice-…"></a>` → (`## 小节`, id)。"""
    match = INLINE_ANCHOR_RE.search(title.rstrip())
    if not match:
        return title.rstrip(), ""
    return title[: match.start()].rstrip(), match.group("id")


def _strip_practice_index(text: str) -> str:
    """去掉派生内容（标题行内的锚点与两类索引块），只留调用方真正提交的正文。

    索引块连同它插入时带的空行一起吞掉，重试同一轮才不会被派生内容算成新内容。
    """
    lines: list[str] = []
    inside = False
    for raw in _normalize_text(text).split("\n"):
        stripped = _split_inline_anchor(raw.rstrip())[0]
        marker = stripped.strip()
        if marker == INDEX_TITLE:
            while lines and not lines[-1].strip():
                lines.pop()
            continue
        if marker in (INDEX_START, ROUND_INDEX_START):
            while lines and not lines[-1].strip():
                lines.pop()
            inside = True
            continue
        if inside:
            if marker in (INDEX_END, ROUND_INDEX_END):
                inside = False
            continue
        lines.append(stripped)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def _without_generated_at(text: str) -> str:
    """去掉 `生成时间` 行，用于判重：写入时盖章，重试的同一份内容不会因此被判成新的。"""
    return GENERATED_AT_ROW_RE.sub("", _normalize_text(text))


def _comparable(text: str) -> str:
    """Normalize a block so trivial whitespace, separators and section numbering do not register.

    ``_split_blocks`` keeps the ``---`` separator that follows a block, so a
    retried append inside a multi-round file must ignore it; otherwise the
    same round looks new and gets appended a second time under a bumped minute.
    The day's `` - 01`` / `` - 02`` suffixes and the inline anchors are derived
    too: stripping them keeps a retried round identical to the stored one.
    """
    lines = [
        _section_base(line.rstrip())[0] if line.lstrip().startswith("## ") else line.rstrip()
        for line in _strip_practice_index(text).strip("\n").split("\n")
    ]
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
        chunks.append((_section_text(lines[start]), body))
    return chunks


SECTION_SEQ_RE = re.compile(r"^(?P<base>## .+?) - (?P<seq>\d{2})$")


def _section_text(line: str) -> str:
    """行尾隐藏锚点剥掉后的标题文本，用于按标题查找小节。"""
    return _split_inline_anchor(line.rstrip())[0].strip()


def _section_base(title: str) -> tuple[str, int | None]:
    """拆分小节标题的序号后缀：`## 练习… - 02` → (`## 练习…`, 2)。"""
    text = _split_inline_anchor(title.strip())[0]
    match = SECTION_SEQ_RE.match(text)
    if not match:
        return text, None
    return match.group("base").strip(), int(match.group("seq"))


def _day_menu_sections(lines: list[str], date: str) -> dict[str, list[tuple[int, int | None]]]:
    """同一天所有区块里的菜单项小节：base 标题 → [(行号, 序号)]。

    同日多次练同一个菜单时，标题靠 ` - 01`、` - 02` 区分；单份不带后缀。
    """
    result: dict[str, list[tuple[int, int | None]]] = {}
    current: str | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("# "):
            match = HEADING_RE.match(stripped)
            current = match.group("date") if match else None
            continue
        if current != date or not stripped.startswith("## "):
            continue
        base, seq = _section_base(stripped)
        result.setdefault(base, []).append((index, seq))
    return result


def _number_day_sections(
    block_lines: list[str], day_lines: list[str], date: str
) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """同一天同一菜单项的第二份起统一编号，并给已有那份补 ` - 01`。

    返回新的区块行、改写后的既有文件行，以及每一处标题变更的记录。
    """
    day = _day_menu_sections(day_lines, date)
    renamed: list[dict[str, str]] = []
    new_block = list(block_lines)
    for index, line in enumerate(block_lines):
        stripped = line.strip()
        if not stripped.startswith("## "):
            continue
        base, seq = _section_base(stripped)
        if base == f"## {QUIZ_SECTION}" or seq is not None:
            continue
        taken = day.get(base, [])
        if not taken:
            day[base] = [(index, None)]
            continue
        if len(taken) == 1 and taken[0][1] is None:
            position = taken[0][0]
            day_lines[position] = f"{base} - 01"
            renamed.append({"from": base, "to": f"{base} - 01", "line": str(position + 1)})
            taken = [(position, 1)]
        number = max(item[1] or 1 for item in taken) + 1
        title = f"{base} - {number:02d}"
        new_block[index] = title
        renamed.append({"from": base, "to": title, "line": f"block:{index + 1}"})
        day[base] = taken + [(index, number)]
    return new_block, day_lines, renamed


def practice_anchor_id(date: str, time: str, base: str, seq: int | None = None) -> str:
    """每一份习题小节的稳定锚点：日期 + 时间 + 菜单项标题的短哈希。

    不展示在正文里，只给文件级小节的索引条目做跳转目标；时间落在 id 里。同一区块内
    重复练同一菜单项时两份小节的日期与时间完全相同，再拼上标题序号（` - 01`、` - 02`）
    才能各自唯一。
    """
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    anchor = f"practice-{date}-{time.replace(':', '')}-{digest}"
    return f"{anchor}-{seq:02d}" if seq is not None else anchor


def section_index_labels(items: list[tuple[str, str]]) -> list[str]:
    """按给定顺序给同名小节生成索引展示文本：`<date> <HH:MM> · <kind>`。

    同一天同一菜单项有多份（不同区块，或同一区块里重复练）时按顺序补 ` - 01`、` - 02`，
    一天只有一份时不带后缀。`items` 是按时间升序排好的 `(stamp, kind)`。
    """
    totals: dict[str, int] = {}
    for stamp, _kind in items:
        totals[stamp[:10]] = totals.get(stamp[:10], 0) + 1
    counters: dict[str, int] = {}
    labels: list[str] = []
    for stamp, kind in items:
        date = stamp[:10]
        counters[date] = counters.get(date, 0) + 1
        label = f"{date} {stamp[11:]} · {kind}"
        labels.append(f"{label} - {counters[date]:02d}" if totals[date] > 1 else label)
    return labels


def generated_at(text: str) -> str | None:
    """读一节表格里的 `生成时间`（`YYYY-MM-DD HH:MM`）；没有或格式不对时返回 None。"""
    match = GENERATED_AT_ROW_RE.search(_normalize_text(text))
    if not match:
        return None
    stamp = match.group("value").strip()
    return stamp if GENERATED_AT_STAMP_RE.match(stamp) else None


def _stamp_one_table(text: str, stamp: str) -> str:
    """给一节里的第一张表补一行 `生成时间`；已经有这一行时一字不动。"""
    start = text.find("<table")
    if start == -1:
        return text
    close = "</table>"
    end = text.find(close, start)
    if end == -1:
        return text
    table = text[start : end + len(close)]
    if GENERATED_AT_ROW_RE.search(table):
        return text
    colgroup = table.find("</colgroup>")
    insert_at = table.find("\n", colgroup) + 1 if colgroup != -1 else table.find("\n") + 1
    if insert_at == 0:
        insert_at = 0
    row = f"<tr><td>{GENERATED_AT_FIELD}</td><td>{stamp}</td></tr>\n"
    table = table[:insert_at] + row + table[insert_at:]
    return text[:start] + table + text[end + len(close) :]


def fill_generated_at(
    text: str, stamp: str, overrides: dict[str, str] | None = None
) -> str:
    """给每个 `## ` 小节的第一张表盖上 `生成时间`。

    `overrides`（小节标题 → 时间）用来在重写时保留原有值：`生成时间` 只在小节首次
    落盘时盖章，之后的补题、重写、索引重建都不改它。
    """
    overrides = overrides or {}
    parts = re.split(r"(?m)^(?=## )", _normalize_text(text))
    filled: list[str] = []
    for part in parts:
        heading = part.split("\n", 1)[0].strip() if part.startswith("## ") else ""
        filled.append(_stamp_one_table(part, overrides.get(heading, stamp)))
    return "".join(filled)


def _now_stamp(when: datetime | None = None) -> str:
    """写入时刻的 `生成时间` 文本：小节首次落盘时盖一次，之后不再变动。"""
    return (when or datetime.now()).strftime("%Y-%m-%d %H:%M")


def generated_at_by_line(lines: list[str]) -> dict[int, str]:
    """`## 小节` 标题所在行号 → 该节的 `生成时间`；缺这一行时回落到区块标题时间。"""
    stamps: dict[int, str] = {}
    date: str | None = None
    time: str | None = None
    section_line: int | None = None
    for index, line in enumerate(lines):
        heading = HEADING_RE.match(line.strip())
        if heading:
            if section_line is not None and date and time:
                stamps.setdefault(section_line, f"{date} {time}")
            date, time = heading.group("date"), heading.group("time")
            section_line = None
            continue
        if line.startswith("## "):
            if section_line is not None and date and time:
                stamps.setdefault(section_line, f"{date} {time}")
            section_line = index
            continue
        if section_line is not None:
            match = GENERATED_AT_ROW_RE.search(line)
            if match:
                value = match.group("value").strip()
                if GENERATED_AT_STAMP_RE.match(value):
                    stamps[section_line] = value
                else:
                    stamps.setdefault(section_line, "?")
    if section_line is not None and date and time:
        stamps.setdefault(section_line, f"{date} {time}")
    return {line: value for line, value in stamps.items() if value != "?"}


def round_anchor_id(date: str, time: str) -> str:
    """日期区块里 `## 本轮习题` 的锚点；一个区块固定一份，用日期 + 时间即可唯一。"""
    return f"round-{date}-{time.replace(':', '')}"


def practice_entries(lines: list[str]) -> dict[str, list[tuple[str, str]]]:
    """菜单项 → [(索引展示文本, 锚点 id)]，按时间倒序排列（新的在前）。

    时间取该小节表格里的 `生成时间`（这一节真正写进笔记的时刻），不取日期区块标题；
    同一天同一菜单项有多份时按时间先后补 ` - 01`、` - 02`，同一分钟落到两份时再按
    标题序号区分，锚点 id 与展示文本用的是同一个时间。
    """
    stamps = generated_at_by_line(lines)
    occurrences: dict[str, list[tuple[str, str, int | None]]] = {}
    date = time = kind = None
    for index, line in enumerate(lines):
        stripped = _split_inline_anchor(line.strip())[0]
        heading = HEADING_RE.match(stripped)
        if heading:
            date, time, kind = heading.group("date"), heading.group("time"), heading.group("kind")
            continue
        if date is None or not stripped.startswith("## "):
            continue
        base, seq = _section_base(stripped)
        if base == f"## {QUIZ_SECTION}":
            continue
        stamp = stamps.get(index) or f"{date} {time}"
        occurrences.setdefault(base, []).append((stamp, kind, seq))
    grouped: dict[str, list[tuple[str, str]]] = {}
    for base, items in occurrences.items():
        ordered = sorted(items, key=lambda item: (item[0], item[2] or 0))
        labels = section_index_labels([(stamp, kind) for stamp, kind, _seq in ordered])
        entries = [
            (labels[position], practice_anchor_id(item[0][:10], item[0][11:], base, item[2]))
            for position, item in enumerate(ordered)
        ]
        entries.reverse()
        grouped[base] = entries
    return grouped


def day_labels(stamps: list[tuple[str, str]]) -> dict[str, str]:
    """索引条目的展示文本，与日期区块标题一致：`<date> <HH:MM> · <kind>`。

    `stamps` 是 ``[(<date> <HH:MM>, <kind>)]``。同一天有多条时按时间先后补 ` - 01`、` - 02`，
    否则两条同日区块在目录里分不清先后。
    """
    by_date: dict[str, list[tuple[str, str]]] = {}
    for stamp, kind in stamps:
        by_date.setdefault(stamp[:10], []).append((stamp, kind))
    labels: dict[str, str] = {}
    for date, day_stamps in by_date.items():
        ordered = sorted(day_stamps)
        for position, (stamp, kind) in enumerate(ordered, 1):
            label = f"{date} {stamp[11:]} · {kind}"
            labels[stamp] = f"{label} - {position:02d}" if len(ordered) > 1 else label
    return labels


def _round_entries(lines: list[str]) -> list[tuple[str, str]]:
    """每个日期区块的 `## 本轮习题` → [(展示文本, 锚点 id)]，按时间倒序（新的在前）。"""
    entries: dict[str, str] = {}
    date = time = kind = None
    for line in lines:
        stripped = _split_inline_anchor(line.strip())[0]
        heading = HEADING_RE.match(stripped)
        if heading:
            date, time, kind = heading.group("date"), heading.group("time"), heading.group("kind")
            continue
        if date is None or not stripped.startswith("## "):
            continue
        base, _seq = _section_base(stripped)
        if base != f"## {QUIZ_SECTION}":
            continue
        entries[f"{date} {time}"] = kind
    labels = day_labels(sorted(entries.items()))
    return [
        (labels[stamp], round_anchor_id(stamp[:10], stamp[11:]))
        for stamp in sorted(entries, reverse=True)
    ]


def apply_practice_index(text: str) -> str:
    """重建隐藏锚点与两份索引块（幂等）。

    - 每个日期区块里的菜单项小节、以及 `## 本轮习题`，都在标题行右侧挂一行
      `<a id="practice-…"></a>` / `<a id="round-…"></a>`：标题本身不显示它，跳转直接落在标题上。
    - 文件级同名小节的**讲解内容之后**写 `复习历史：` + `<!-- practice-index -->` …
      `<!-- /practice-index -->`，按时间倒序列出该菜单项的全部习题小节（新的在前）。
    - `## 讲解` 的讲解内容之后写 `复习历史：` + `<!-- round-index -->` …
      `<!-- /round-index -->`，列出整份笔记每个日期区块的 `## 本轮习题`（新的在前）。
    """
    lines = _normalize_text(text).split("\n")
    entries = practice_entries(lines)
    stamps = generated_at_by_line(lines)
    rounds = _round_entries(lines)
    out: list[str] = []
    index = 0
    in_block = False
    pending: list[str] | None = None

    def flush_index() -> None:
        """把当前文件级小节待写的索引块落到小节末尾（讲解内容之后）。"""
        nonlocal pending
        if pending is None:
            return
        while out and not out[-1].strip():
            out.pop()
        out.extend(["", INDEX_TITLE, *pending, ""])
        pending = None

    while index < len(lines):
        line = lines[index]
        title, old_anchor = _split_inline_anchor(line)
        stripped = title.strip()
        if old_anchor and not stripped:
            # 旧版把锚点单独占一行，统一改成挂在标题右侧
            index += 1
            continue
        if stripped.startswith("# "):
            flush_index()
            in_block = True
            out.append(title)
            index += 1
            continue
        if stripped.startswith("## "):
            flush_index()
            base, seq = _section_base(stripped)
            if in_block:
                date = time = None
                for back in range(len(out) - 1, -1, -1):
                    heading = HEADING_RE.match(out[back].strip())
                    if heading:
                        date, time = heading.group("date"), heading.group("time")
                        break
                out.append(title)
                stamp = stamps.get(index)
                # `## 本轮习题` 的锚点标的是这一轮开始的时间（与区块标题一致）；
                # 只有带菜单项标题的习题小节才用表格里的 `生成时间`。
                if stamp and base != f"## {QUIZ_SECTION}":
                    date, time = stamp[:10], stamp[11:]
                index += 1
                if date and time:
                    anchor = (
                        round_anchor_id(date, time)
                        if base == f"## {QUIZ_SECTION}"
                        else practice_anchor_id(date, time, base, seq)
                    )
                    out[-1] = f'{title} <a id="{anchor}"></a>'
                continue
            out.append(title)
            index += 1
            if base == f"## {EXPLAIN_SECTION}" and rounds:
                pending = [
                    ROUND_INDEX_START,
                    *[f"- [{label}](#{anchor})" for label, anchor in rounds],
                    ROUND_INDEX_END,
                ]
            elif base not in (f"## {EXPLAIN_SECTION}", "## 基础信息") and base in entries:
                pending = [
                    INDEX_START,
                    *[f"- [{label}](#{anchor})" for label, anchor in entries[base]],
                    INDEX_END,
                ]
            continue
        marker = stripped
        if marker in (INDEX_TITLE, INDEX_START, ROUND_INDEX_START):
            # 旧索引块（标题行紧跟索引的旧位置、或已在末尾）整体吞掉，稍后按新位置重建
            while out and not out[-1].strip():
                out.pop()
            while index < len(lines) and (
                lines[index].strip()
                in (INDEX_TITLE, INDEX_START, INDEX_END, ROUND_INDEX_START, ROUND_INDEX_END)
                or INDEX_LINE_RE.match(lines[index].strip())
                or not lines[index].strip()
            ):
                index += 1
            out.append("")
            continue
        out.append(line)
        index += 1
    flush_index()
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + "\n"


def _split_head_and_rounds(text: str) -> tuple[str, str]:
    """Split a note into its file-level head and the region holding date blocks.

    The head is everything above the first level-1 heading (``## 基础信息`` and
    ``## 讲解``). The rounds region keeps every date block in file order, so a
    caller can insert or reorder blocks without touching the head.
    """
    lines = _normalize_text(text).split("\n")
    for index, line in enumerate(lines):
        if line.startswith("# "):
            head = "\n".join(lines[:index]).rstrip("\n")
            rounds = "\n".join(lines[index:]).rstrip("\n")
            return head, rounds
    return "\n".join(lines).rstrip("\n"), ""


def _strip_trailing_dividers(rounds: str) -> str:
    """Drop separators left at the very end of the rounds region."""
    lines = rounds.rstrip("\n").split("\n")
    while lines and (not lines[-1].strip() or lines[-1].strip() == DIVIDER):
        lines.pop()
    return "\n".join(lines).rstrip("\n")


DETAIL_BASES = ("场景对话原文", "故事原文")
DETAIL_SUMMARY_RE = re.compile(r"<summary>\s*([^<]+?)\s*</summary>")

ROUND_BLOCK_EXPLAINED = (
    "日期区块只放习题：`{title}` 写的是讲解内容（讲解要点 / 场景对话原文 / 故事原文），"
    "必须放在文件级讲解区（`## 讲解` 之后、所有日期区块之前）；日期区块里的同名小节只写 "
    "`### <n>. <题型>` 习题，不重复讲解"
)
ROUND_BLOCK_EMPTY = (
    "日期区块里的菜单项小节只放习题：`{title}` 里没有 `### <n>. <题型>` 题目，"
    "等于这一节没有交付内容；讲解要点写进文件级讲解区，习题写进本轮区块"
)


def _check_round_sections(block: str) -> None:
    """Refuse explanation content inside a round block.

    The split between the file-level explanation area and the dated round
    blocks was a rule that only the docs enforced once, so menu follow-ups kept
    landing in ``# <date> · 复习`` blocks; validating it at the write path (and
    in ``check_note.py``) is the only guard that actually holds.
    """
    for title, body in _sections(block):
        if title == f"## {QUIZ_SECTION}":
            continue
        if "**讲解要点**" in body or any(
            f"<summary>{base}" in body for base in DETAIL_BASES
        ):
            raise NoteError(ROUND_BLOCK_EXPLAINED.format(title=title))
        if not re.search(r"^### \d+\.", body, re.M):
            raise NoteError(ROUND_BLOCK_EMPTY.format(title=title))


def _normalize_detail_summaries(text: str) -> str:
    """同一小节里只剩一段原文时不编号，出现第二段起按 1、2、3… 编号。

    旧的单段原文写的是 ``<summary>故事原文</summary>``，追加第二段时它要变成
    ``故事原文 1``，否则校验器会把两段都判成编号错位。
    """
    for base in DETAIL_BASES:
        while True:
            current = [
                match
                for match in DETAIL_SUMMARY_RE.finditer(text)
                if re.fullmatch(rf"{re.escape(base)}(?:\s+\d+)?", match.group(1).strip())
            ]
            if len(current) < 2:
                break
            wrong = next(
                (
                    (index, match)
                    for index, match in enumerate(current, 1)
                    if match.group(1).strip() != f"{base} {index}"
                ),
                None,
            )
            if wrong is None:
                break
            index, match = wrong
            replacement = f"<summary>{base} {index}</summary>"
            text = text[: match.start()] + replacement + text[match.end() :]
    return text


def _explain_area_bounds(lines: list[str]) -> tuple[int, int]:
    """Return the file-level explanation region: after ``## 讲解``, before the first date block.

    ``end`` is the index of the first level-1 heading (or ``len(lines)``), which
    is exactly where a new file-level menu section may be inserted.
    """
    first_round = next(
        (index for index, line in enumerate(lines) if line.startswith("# ")), len(lines)
    )
    explain_start = next(
        (index for index, line in enumerate(lines[:first_round]) if EXPLAIN_HEAD_RE.match(line)),
        None,
    )
    if explain_start is None:
        return first_round, first_round
    return explain_start, first_round


def _next_free_heading(heading: str, existing: list[str]) -> str:
    """Give the incoming block a heading that keeps the file's headings unique.

    Blocks are ordered newest-first, so the incoming round belongs at the top;
    its timestamp must still be newer than every existing round, otherwise the
    newest-first order and the ``笔记更新时间`` stamp would both drift. Two rounds
    can legitimately finish within the same minute (concurrent conversations,
    or a review followed by a practice), so the timestamp is moved to
    ``max(existing)+1min`` until it is both unique and monotonic.
    """
    match = HEADING_RE.match(heading)
    if not match:
        raise NoteError(f"note heading is invalid: {heading}")
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


HEADING_KIND_RE = re.compile(
    r"^# \d{4}-\d{2}-\d{2} \d{2}:\d{2} · (?P<kind>复习|练习|套题)$"
)


def _sync_basic_rows(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    """Rewrite record-level rows of the file-level ``## 基础信息`` table.

    Only the two rows the canonical record owns (累计复习次数 / 下次复习) are
    touched, and only inside the head region before the first dated block: the
    per-round tables look similar and must never be rewritten.
    """
    lines = _normalize_text(text).split("\n")
    first_block = next(
        (index for index, line in enumerate(lines) if line.startswith("# ")), len(lines)
    )
    changed: list[str] = []
    for field, pattern in SYNCABLE_ROWS.items():
        wanted = values.get(field)
        if wanted is None:
            continue
        for index in range(first_block):
            if not pattern.search(lines[index]):
                continue
            row = f"<tr><td>{field}</td><td>{wanted}</td></tr>"
            if lines[index].strip() != row:
                lines[index] = row
                changed.append(field)
            break
    return "\n".join(lines), changed


def _note_index(text: str) -> dict[str, Any]:
    """Index one note without the records snapshot cache: file-level id + blocks' sections."""
    normalized = _normalize_text(text)
    record = RECORD_ID_ROW_RE.search(normalized)
    blocks: list[dict[str, Any]] = []
    explain_sections: list[str] = []
    current: dict[str, Any] | None = None
    chunk: list[str] = []
    for line in normalized.split("\n"):
        if line.startswith("# "):
            if current is not None:
                block_match = RECORD_ID_ROW_RE.search("\n".join(chunk))
                current["record_id"] = (
                    block_match.group(1).strip() if block_match else None
                )
            match = HEADING_KIND_RE.match(line.strip())
            current = {
                "heading": line.strip(),
                "kind": match.group("kind") if match else None,
                "sections": [],
                "record_id": None,
            }
            blocks.append(current)
            chunk = [line]
        elif current is not None:
            chunk.append(line)
            if line.startswith("## "):
                current["sections"].append(_section_text(line))
        elif line.startswith("## ") and _section_text(line) != "## 基础信息":
            # 文件级讲解区：`## 讲解` 与只讲解、不带习题的菜单小节
            explain_sections.append(_section_text(line))
    if current is not None:
        block_match = RECORD_ID_ROW_RE.search("\n".join(chunk))
        current["record_id"] = block_match.group(1).strip() if block_match else None
    return {
        "record_id": record.group(1).strip() if record else None,
        "blocks": blocks,
        "explain_sections": explain_sections,
    }


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
        """Prefer the validator in the repo's own take-english-study-notes skill, then the installed one."""
        repo_candidate = self.repo_root / "take-english-study-notes" / "scripts" / "check_note.py"
        if repo_candidate.is_file():
            return repo_candidate
        installed = Path(__file__).resolve().parent / "check_note.py"
        return installed if installed.is_file() else repo_candidate

    # -- path handling ---------------------------------------------------
    def resolve(self, path: str) -> Path:
        """Resolve a note path to ``<notes>/<category>/<category>-<slug>.md``.

        Accepts the canonical relative form, an absolute path, a bare file
        name, and the pre-directory form ``learning-record-notes/<name>.md``:
        the category directory is always derived from the file name prefix, so
        an old flat path keeps working and the file is moved into its category
        directory the first time it is touched.
        """
        raw = Path(path).expanduser()
        if raw.is_symlink():
            raise NoteError("refusing to write through a symbolic link")
        notes_dir = self.notes_dir.resolve()
        if raw.is_absolute():
            candidate = raw.resolve()
        elif raw.parent == Path("."):
            candidate = self.notes_dir / raw.name
        else:
            candidate = (self.repo_root / raw).resolve()
        if candidate.is_symlink():
            raise NoteError("refusing to write through a symbolic link")
        if not SLUG_FILE_RE.match(candidate.name):
            raise NoteError(
                "note file name must look like <category>-<slug>.md "
                "(lowercase letters, digits, and hyphens only)"
            )
        category = filename_category(candidate.name)
        if category is None:
            raise NoteError(
                "note file name must start with a `<category>-` prefix, "
                "e.g. errors-out-west.md"
            )
        parent = candidate.parent
        if parent.name and parent.parent == notes_dir:
            if parent.name != category:
                raise NoteError(
                    f"note {candidate.name} belongs in {NOTES_DIR_NAME}/{category}/, "
                    f"not {NOTES_DIR_NAME}/{parent.name}/"
                )
            target = candidate
        elif parent == notes_dir:
            # 旧版平铺路径：落到分类目录里（若旧文件还在，稍后随写入迁移）
            target = notes_dir / category / candidate.name
        else:
            raise NoteError(
                f"note path must live under {NOTES_DIR_NAME}/<category>/: {path}"
            )
        if target.is_symlink():
            raise NoteError("refusing to write through a symbolic link")
        if target.exists() and not target.is_file():
            raise NoteError(f"note path is not a regular file: {path}")
        legacy = notes_dir / candidate.name
        if not target.exists() and legacy.is_file() and not legacy.is_symlink():
            # 一次性升级：旧平铺文件在第一次被引用时移进分类目录。
            # 另一个会话可能刚移过，取不到旧文件就当作已迁移。
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(legacy, target)
            except FileNotFoundError:
                pass
        return target

    def relative(self, target: Path) -> str:
        category = (
            target.parent.name
            if target.parent.parent == self.notes_dir.resolve()
            else filename_category(target.name) or ""
        )
        return f"{NOTES_DIR_NAME}/{category}/{target.name}"

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
                raise NoteError(
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
            raise NoteError(f"cannot read note {path}: {exc}") from exc

    def _write(self, path: Path, text: str) -> None:
        text = apply_practice_index(text)
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
    def find_note_for_record(self, record_id: str) -> str | None:
        for entry in self.list_notes(record_id):
            if entry["record_id"] == record_id:
                return entry["file"]
        return None

    def append(self, path: str, content: str) -> dict[str, Any]:
        target = self.resolve(path)
        head, raw_block = _split_head(content)
        block = _normalize_block(raw_block)
        _check_round_sections(block)
        block = fill_generated_at(block, _now_stamp())
        declared = RECORD_ID_ROW_RE.search(content)
        if declared and not target.exists():
            tracked = self.find_note_for_record(declared.group(1).strip())
            if tracked and tracked != self.relative(target):
                raise NoteError(
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
                if _comparable(_without_generated_at(written[1])) == _comparable(
                    _without_generated_at(block)
                ):
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
            block_date = HEADING_RE.match(_block_heading(block)).group("date")
            numbered_block, day_lines, renamed = _number_day_sections(
                block.split("\n"), body.split("\n"), block_date
            )
            block = "\n".join(numbered_block).rstrip("\n") + "\n"
            body = "\n".join(day_lines)
            # 新一轮按时间倒序插在最前：最新一轮紧跟文件级讲解区（`## 讲解` 与只讲解的菜单小节），
            # 旧区块整体原样保留在下方，不重排、不改写别的会话已经写下的内容。
            if not body.strip():
                if not head:
                    raise NoteError(
                        "a new note must start with the file-level `## 基础信息` section "
                        "(记录 ID / 试卷 ID、目标知识点、累计复习次数、下次复习、笔记生成时间、笔记更新时间)"
                    )
                composed = f"{head}\n\n{block}"
            elif not existing_blocks:
                # 只有文件级 `## 基础信息` 与 `## 讲解` 时，本轮区块直接接在讲解之后
                composed = f"{body}\n\n{block}"
            else:
                head_text, rounds_text = _split_head_and_rounds(body)
                rounds_text = _strip_trailing_dividers(rounds_text)
                prefix = f"{head_text}\n\n" if head_text.strip() else ""
                composed = f"{prefix}{block}\n\n{DIVIDER}\n\n{rounds_text}"
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
                f"{requested_heading} is already taken or would break the newest-first order; "
                f"this block was saved as {heading} instead, with both rounds kept"
                if adjusted
                else None
            ),
            "file": self.relative(target),
            "heading": heading,
            "blocks": blocks,
            "section_renamed": renamed,
            "bytes": len(composed.encode("utf-8")),
        }

    def write_explanation(
        self, path: str, content: str, *, update: bool = False
    ) -> dict[str, Any]:
        """Create a note whose only content is 基础信息 + 文件级 `## 讲解`.

        A knowledge point has exactly one explanation, so it cannot be appended
        as a dated round: it lives directly under the file header, and every
        later review round is added below it by :meth:`append`.
        """
        target = self.resolve(path)
        normalized = _normalize_text(content).strip("\n")
        if normalized.startswith("# ") or "\n# " in normalized:
            raise NoteError(
                "an explanation note cannot contain a date heading; reviews are "
                "added later as `# <date> <time> · 复习` blocks"
            )
        if f"## {EXPLAIN_SECTION}" not in normalized:
            raise NoteError(
                f"an explanation note must contain a file-level `## {EXPLAIN_SECTION}` section"
            )
        if not update and "## 基础信息" not in normalized and not target.exists():
            raise NoteError(
                "an explanation note must start with the file-level `## 基础信息` section"
            )
        declared = RECORD_ID_ROW_RE.search(content)
        if declared:
            tracked = self.find_note_for_record(declared.group(1).strip())
            if tracked and tracked != self.relative(target):
                raise NoteError(
                    f"record {declared.group(1).strip()} already has a note at {tracked}; "
                    f"write the explanation into that file instead of creating {self.relative(target)}"
                )
        with self._exclusive_lock():
            existing = self._read(target)
            if existing.strip() and update:
                return self._rewrite_explanation(target, normalized)
            if existing.strip():
                if EXPLAIN_HEAD_RE.search(_normalize_text(existing)):
                    return {
                        "ok": True,
                        "appended": False,
                        "duplicate": True,
                        "hint": (
                            "this note already has an `## 讲解` section; a knowledge point "
                            "keeps exactly one explanation, so do not write a second one"
                        ),
                        "file": self.relative(target),
                    }
                raise NoteError(
                    f"note already exists without an `## {EXPLAIN_SECTION}` section: "
                    f"{self.relative(target)}; append a round block instead of overwriting it"
                )
            composed = _bump_updated_at(f"{normalized}\n", datetime.now())
            self._write(target, composed)
        return {
            "ok": True,
            "appended": True,
            "duplicate": False,
            "explanation": True,
            "file": self.relative(target),
            "bytes": len(composed.encode("utf-8")),
        }

    def _rewrite_explanation(self, target: Path, content: str) -> dict[str, Any]:
        """Rewrite the existing `## 讲解` section only, leaving every other line intact."""
        existing = _normalize_text(self._read(target))
        lines = existing.split("\n")
        start = next(
            (index for index, line in enumerate(lines) if EXPLAIN_HEAD_RE.match(line)),
            None,
        )
        if start is None:
            # 旧笔记（尤其历史补建、只追加过复习区块的）可能没有讲解小节：
            # 补一份插在基础信息表之后、所有日期区块之前，不覆盖任何已有内容。
            return self._insert_explanation(target, lines, content)
        end = next(
            (
                index
                for index in range(start + 1, len(lines))
                if lines[index].startswith("# ") or lines[index].startswith("## ")
            ),
            len(lines),
        )
        declared = RECORD_ID_ROW_RE.search(content)
        if declared:
            kept = self._file_record_id(existing)
            if kept and kept != declared.group(1).strip():
                raise NoteError(
                    f"this note tracks {kept}; refusing to overwrite it with {declared.group(1).strip()}"
                )
        new_lines = _normalize_text(content).strip("\n").split("\n")
        head_index = next(
            (index for index, line in enumerate(new_lines) if EXPLAIN_HEAD_RE.match(line)),
            None,
        )
        if head_index is None:
            raise NoteError(f"replacement content must contain `## {EXPLAIN_SECTION}`")
        body = new_lines[head_index:]
        tail = lines[end:]
        while body and not body[-1].strip():
            body.pop()
        while tail and not tail[0].strip():
            tail.pop(0)
        composed = "\n".join(lines[:start] + body + ([""] + tail if tail else []))
        composed = _bump_updated_at(composed.rstrip("\n") + "\n", datetime.now())
        self._write(target, composed)
        return {
            "ok": True,
            "appended": False,
            "updated": True,
            "explanation": True,
            "file": self.relative(target),
            "bytes": len(composed.encode("utf-8")),
        }

    def _insert_explanation(
        self, target: Path, lines: list[str], content: str
    ) -> dict[str, Any]:
        """Insert the missing `## 讲解` section without touching any other line.

        Historical notes were often created by review rounds only, so they carry
        `## 基础信息` plus dated blocks and no explanation. The section belongs
        right after the basic-info table and before every dated block.
        """
        new_lines = _normalize_text(content).strip("\n").split("\n")
        head_index = next(
            (index for index, line in enumerate(new_lines) if EXPLAIN_HEAD_RE.match(line)),
            None,
        )
        if head_index is None:
            raise NoteError(f"replacement content must contain `## {EXPLAIN_SECTION}`")
        body = new_lines[head_index:]
        while body and not body[-1].strip():
            body.pop()
        declared = RECORD_ID_ROW_RE.search(content)
        if declared:
            kept = self._file_record_id("\n".join(lines))
            if kept and kept != declared.group(1).strip():
                raise NoteError(
                    f"this note tracks {kept}; refusing to insert an explanation for "
                    f"{declared.group(1).strip()} into it"
                )
        # 只在第一个日期区块之前找基础信息表的结尾，避免把讲解插进某一轮区块
        block_start = next(
            (index for index, line in enumerate(lines) if line.startswith("# ")),
            len(lines),
        )
        insert_at = next(
            (
                index + 1
                for index, line in enumerate(lines[:block_start])
                if line.strip() == "</table>"
            ),
            None,
        )
        if insert_at is None:
            insert_at = block_start
        prefix = lines[:insert_at]
        suffix = lines[insert_at:]
        while suffix and not suffix[0].strip():
            suffix.pop(0)
        composed = "\n".join(prefix + ["", *body, ""] + suffix)
        composed = _bump_updated_at(composed.rstrip("\n") + "\n", datetime.now())
        self._write(target, composed)
        return {
            "ok": True,
            "appended": False,
            "updated": False,
            "inserted": True,
            "explanation": True,
            "file": self.relative(target),
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
        _check_round_sections(block)
        wanted = _normalize_text(heading).strip()
        if _block_heading(block) != wanted:
            raise NoteError(
                "replacement block must keep the original heading line unchanged"
            )
        with self._exclusive_lock():
            existing = _normalize_text(self._read(target))
            if not existing:
                raise NoteError(f"note does not exist: {self.relative(target)}")
            lines = existing.split("\n")
            matches = [index for index, line in enumerate(lines) if line.strip() == wanted]
            if not matches:
                raise NoteError(f"heading not found in note: {wanted}")
            if len(matches) > 1:
                raise NoteError(
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
            keep_stamps = {
                section_heading: stamp
                for section_heading, body in existing_sections
                if (stamp := generated_at(body))
            }
            block = fill_generated_at(block, _now_stamp(), keep_stamps)
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
                raise NoteError(
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
            raise NoteError("note section is empty")
        section = fill_generated_at(section, _now_stamp())
        first = section.split("\n")[0].strip()
        if not first.startswith("## "):
            raise NoteError("a note section must start with a '## ' heading")
        for line in section.split("\n")[1:]:
            if line.startswith("# "):
                raise NoteError(
                    "a note section cannot contain a level-1 heading; "
                    "sections are added inside an existing round block"
                )
        _check_round_sections(section)
        section_heading = first
        wanted = _normalize_text(heading).strip()
        with self._exclusive_lock():
            existing = _normalize_text(self._read(target))
            if not existing:
                raise NoteError(f"note does not exist: {self.relative(target)}")
            lines = existing.split("\n")
            matches = [index for index, line in enumerate(lines) if line.strip() == wanted]
            if not matches:
                raise NoteError(f"heading not found in note: {wanted}")
            if len(matches) > 1:
                raise NoteError(
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
            incoming_base, incoming_seq = _section_base(section_heading)
            for existing_heading, body in _sections("\n".join(block_lines)):
                if _section_base(existing_heading)[0] != incoming_base:
                    continue
                if _comparable(_without_generated_at(body)) == _comparable(
                    _without_generated_at(section)
                ):
                    return {
                        "ok": True,
                        "appended_section": False,
                        "duplicate": True,
                        "file": self.relative(target),
                        "heading": wanted,
                        "section": section_heading,
                        "hint": "this section is already in the block; do not append it again",
                    }
                # 同一区块里重复练同一菜单项：交给 _number_day_sections 编号成
                # `## <标题> - 01` / ` - 02`，两轮各自一张得分表，不再并进同一个小节。
                continue
            renamed: list[dict[str, str]] = []
            date_match = HEADING_RE.match(lines[start].strip())
            if date_match and incoming_seq is None:
                numbered_section, lines, renamed = _number_day_sections(
                    section.split("\n"), lines, date_match.group("date")
                )
                section = "\n".join(numbered_section).rstrip("\n") + "\n"
                section_heading = numbered_section[0].strip()
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
            "section_renamed": renamed,
            "blocks": blocks,
            "bytes": len(composed.encode("utf-8")),
        }

    def append_part(
        self, path: str, heading: str, section_heading: str, content: str
    ) -> dict[str, Any]:
        """在已有 ``## section`` 的末尾追加一段正文（不新建小节）。

        日期区块里的小节只放习题，所以这里只在某一个小节里补写题目；同一菜单项再选一次
        应当另建带序号的同标题小节（` - 01` / ` - 02`），不并节；
        讲解要点、故事 / 对话原文再选一次时走 ``append_explain_part``，追加到文件级
        讲解区里的同名小节（那里才会把 ``故事原文`` 自动改成 ``故事原文 1`` 再编号）。
        新增小节用 ``append_section``，这里只往既有小节末尾补一段，别的小节一字不动。
        """
        part = _normalize_text(content).strip("\n")
        if not part:
            raise NoteError("note section part is empty")
        for line in part.split("\n"):
            if line.startswith("# "):
                raise NoteError(
                    "a section part cannot contain a level-1 heading; "
                    "new sections go through append-section"
                )
            if line.startswith("## "):
                raise NoteError(
                    "a section part cannot start a new '## section'; "
                    "use append-section for a new section"
                )
        if "**讲解要点**" in part or any(
            f"<summary>{base}" in part for base in DETAIL_BASES
        ):
            raise NoteError(
                ROUND_BLOCK_EXPLAINED.format(title=_normalize_text(section_heading).strip())
            )
        wanted_block = _normalize_text(heading).strip()
        wanted_section = _normalize_text(section_heading).strip()
        if not wanted_section.startswith("## "):
            raise NoteError("section heading must start with '## '")
        target = self.resolve(path)
        with self._exclusive_lock():
            existing = _normalize_text(self._read(target))
            if not existing:
                raise NoteError(f"note does not exist: {self.relative(target)}")
            lines = existing.split("\n")
            matches = [index for index, line in enumerate(lines) if line.strip() == wanted_block]
            if not matches:
                raise NoteError(f"heading not found in note: {wanted_block}")
            if len(matches) > 1:
                raise NoteError(
                    f"heading appears {len(matches)} times; refusing an ambiguous append: {wanted_block}"
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
            section_start = next(
                (
                    index
                    for index in range(start + 1, end)
                    if _section_text(lines[index]) == wanted_section
                ),
                None,
            )
            if section_start is None:
                raise NoteError(
                    f"section not found in block {wanted_block}: {wanted_section}; "
                    "use append-section to add it first"
                )
            section_end = next(
                (
                    index
                    for index in range(section_start + 1, end)
                    if lines[index].startswith("## ")
                ),
                end,
            )
            while section_end > section_start + 1 and not lines[section_end - 1].strip():
                section_end -= 1
            before = lines[:section_end]
            after = lines[section_end:]
            merged = "\n".join(before[section_start:] + ["", *part.split("\n")])
            merged = _normalize_detail_summaries(merged)
            spacer = [""] if after and after[0].strip() else []
            composed = "\n".join(
                before[:section_start] + merged.split("\n") + spacer + after
            ).rstrip("\n") + "\n"
            composed = _bump_updated_at(composed, datetime.now())
            self._write(target, composed)
            blocks = _count_blocks(composed)
        return {
            "ok": True,
            "appended_part": True,
            "file": self.relative(target),
            "heading": wanted_block,
            "section": wanted_section,
            "blocks": blocks,
            "bytes": len(composed.encode("utf-8")),
        }

    def append_explain_section(
        self, path: str, content: str, *, rewrite: bool = False
    ) -> dict[str, Any]:
        """在文件级讲解区（``## 讲解`` 之后、所有日期区块之前）追加一个 ``## 小节``。

        菜单项的讲解要点只在第一轮写一次，重复选择同一项时不再新建小节；
        已存在同名小节时返回 ``duplicate``，调用方据此停止重复记录。
        ``rewrite=True`` 时改成就地替换这个同名小节（用于修正首轮写错的内容），
        别的小节一字不动。
        """
        target = self.resolve(path)
        section = _normalize_text(content).strip("\n")
        if not section:
            raise NoteError("note section is empty")
        first = section.split("\n")[0].strip()
        if not first.startswith("## "):
            raise NoteError("a note section must start with a '## ' heading")
        for line in section.split("\n")[1:]:
            if line.startswith("# "):
                raise NoteError(
                    "a note section cannot contain a level-1 heading; date blocks own those"
                )
        with self._exclusive_lock():
            existing = _normalize_text(self._read(target))
            if not existing:
                raise NoteError(f"note does not exist: {self.relative(target)}")
            lines = existing.split("\n")
            explain_start, area_end = _explain_area_bounds(lines)
            if area_end <= explain_start:
                raise NoteError(
                    f"note has no `## {EXPLAIN_SECTION}` section: write the explanation first, "
                    "then file-level menu sections go after it"
                )
            for index in range(explain_start + 1, area_end):
                if lines[index].strip() == first:
                    if rewrite:
                        return self._rewrite_explain_section(
                            target, lines, index, area_end, section, first
                        )
                    return {
                        "ok": True,
                        "appended_section": False,
                        "duplicate": True,
                        "exists": True,
                        "file": self.relative(target),
                        "section": first,
                        "hint": (
                            "this menu item is already explained in the file-level area; "
                            "do not record it a second time"
                        ),
                    }
            prefix = lines[:area_end]
            while prefix and not prefix[-1].strip():
                prefix.pop()
            tail = lines[area_end:]
            composed = "\n".join(prefix + ["", *section.split("\n")] + ([""] + tail if tail else []))
            composed = _bump_updated_at(composed.rstrip("\n") + "\n", datetime.now())
            self._write(target, composed)
            blocks = _count_blocks(composed)
        return {
            "ok": True,
            "appended_section": True,
            "duplicate": False,
            "file": self.relative(target),
            "section": first,
            "blocks": blocks,
            "bytes": len(composed.encode("utf-8")),
        }

    def _rewrite_explain_section(
        self,
        target: Path,
        lines: list[str],
        section_start: int,
        area_end: int,
        section: str,
        first: str,
    ) -> dict[str, Any]:
        """就地替换讲解区的一个同名小节，尾部空行与后续小节保持原样。"""
        section_end = next(
            (
                index
                for index in range(section_start + 1, area_end)
                if lines[index].startswith("## ")
            ),
            area_end,
        )
        while section_end > section_start + 1 and not lines[section_end - 1].strip():
            section_end -= 1
        original = "\n".join(lines[section_start:section_end])
        replacement = _normalize_text(section)
        dropped = []
        for base in DETAIL_BASES:
            kept = original.count(f"<summary>{base}")
            now = replacement.count(f"<summary>{base}")
            if now < kept:
                dropped.append(f"{base}（{kept} 段 → {now} 段）")
        if dropped:
            raise NoteError(
                f"重写 `{first}` 会丢掉已有的原文折叠块：{'、'.join(dropped)}。"
                "`--rewrite` 是整节替换，新小节必须把原有原文全部带上；"
                "只想再补一段原文时用 append-explain-part"
            )
        merged = _normalize_detail_summaries(replacement)
        after = lines[section_end:]
        spacer = [""] if after and after[0].strip() else []
        composed = "\n".join(
            lines[:section_start] + merged.split("\n") + spacer + after
        ).rstrip("\n") + "\n"
        composed = _bump_updated_at(composed, datetime.now())
        self._write(target, composed)
        return {
            "ok": True,
            "appended_section": False,
            "rewritten": True,
            "duplicate": False,
            "file": self.relative(target),
            "section": first,
            "blocks": _count_blocks(composed),
            "bytes": len(composed.encode("utf-8")),
        }

    def append_explain_part(
        self, path: str, section_heading: str, content: str
    ) -> dict[str, Any]:
        """往文件级小节末尾追加一段原文（同一菜单项第二次生成的故事 / 对话）。

        小节里出现第二段原文时，第一段的 summary 自动从 ``故事原文`` 改成
        ``故事原文 1``，其余段落按顺序编号。
        """
        part = _normalize_text(content).strip("\n")
        if not part:
            raise NoteError("note section part is empty")
        for line in part.split("\n"):
            if line.startswith("# "):
                raise NoteError(
                    "a section part cannot contain a level-1 heading; "
                    "date blocks go through append"
                )
            if line.startswith("## "):
                raise NoteError(
                    "a section part cannot start a new '## section'; "
                    "use append-explain-section for a new section"
                )
        wanted = _normalize_text(section_heading).strip()
        if not wanted.startswith("## "):
            raise NoteError("section heading must start with '## '")
        target = self.resolve(path)
        with self._exclusive_lock():
            existing = _normalize_text(self._read(target))
            if not existing:
                raise NoteError(f"note does not exist: {self.relative(target)}")
            lines = existing.split("\n")
            explain_start, area_end = _explain_area_bounds(lines)
            section_start = next(
                (
                    index
                    for index in range(explain_start + 1, area_end)
                    if _section_text(lines[index]) == wanted
                ),
                None,
            )
            if section_start is None:
                raise NoteError(
                    f"section not found in the file-level explanation area: {wanted}; "
                    "use append-explain-section to add it first"
                )
            section_end = next(
                (
                    index
                    for index in range(section_start + 1, area_end)
                    if lines[index].startswith("## ")
                ),
                area_end,
            )
            while section_end > section_start + 1 and not lines[section_end - 1].strip():
                section_end -= 1
            merged = "\n".join(lines[section_start:section_end] + ["", *part.split("\n")])
            merged = _normalize_detail_summaries(merged)
            after = lines[section_end:]
            spacer = [""] if after and after[0].strip() else []
            composed = "\n".join(
                lines[:section_start] + merged.split("\n") + spacer + after
            ).rstrip("\n") + "\n"
            composed = _bump_updated_at(composed, datetime.now())
            self._write(target, composed)
            blocks = _count_blocks(composed)
        return {
            "ok": True,
            "appended_part": True,
            "file": self.relative(target),
            "section": wanted,
            "blocks": blocks,
            "bytes": len(composed.encode("utf-8")),
        }

    def sync_basic_info(self, path: str, values: dict[str, str]) -> dict[str, Any]:
        """Refresh the record-level rows of the file-level ``基础信息`` table.

        ``append``/``replace`` keep only the dated round block, so the head
        table would otherwise stay at the values copied when the note was
        created. The canonical values come from the record store; this method
        is the only supported way to bring them up to date.
        """
        target = self.resolve(path)
        with self._exclusive_lock():
            existing = self._read(target)
            if not existing.strip():
                raise NoteError(f"note does not exist: {self.relative(target)}")
            composed, changed = _sync_basic_rows(existing, values)
            if changed:
                composed = _bump_updated_at(composed.rstrip("\n") + "\n", datetime.now())
                self._write(target, composed)
        return {
            "ok": True,
            "file": self.relative(target),
            "synced": changed,
            "bytes": len(composed.encode("utf-8")) if changed else None,
        }

    def _note_paths(self) -> list[Path]:
        """Every note file: one level of category directories plus any not-yet-migrated flat file."""
        paths: list[Path] = []
        try:
            directories = [
                entry
                for entry in sorted(self.notes_dir.iterdir())
                if entry.is_dir() and not entry.is_symlink()
            ]
        except OSError:
            directories = []
        for directory in directories:
            paths.extend(
                path
                for path in directory.glob("*.md")
                if path.is_file() and path.name.lower() != "readme.md"
            )
        for path in self.notes_dir.glob("*.md"):
            if path.is_file() and path.name.lower() != "readme.md":
                paths.append(path)
        return sorted(paths)

    def list_notes(self, record_id: str | None = None) -> list[dict[str, Any]]:
        """List note blocks, optionally filtered by the record id they track.

        Cheap path first: a snapshot entry is only trusted while the file's
        ``size``/``mtime`` still match, so a file edited outside this tool
        falls back to a real parse instead of returning a stale heading list.
        """
        if not self.notes_dir.is_dir():
            return []
        entries: list[dict[str, Any]] = []
        for path in self._note_paths():
            relative = self.relative(path)
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
            if not blocks and file_record is not None:
                # 只有「基础信息 + 讲解」、还没有任何复习轮次的笔记：按文件级记录 ID 计入索引
                if record_id is None or file_record == record_id:
                    entries.append(
                        {"file": relative, "heading": None, "record_id": file_record}
                    )
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
            raise NoteError(f"note does not exist: {self.relative(target)}")
        relative = self.relative(target)
        entry = _note_index(target.read_text(encoding="utf-8"))
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
            "explain_sections": entry["explain_sections"],
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
            raise NoteError(f"cannot run note validator: {exc}") from exc
        try:
            report = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            raise NoteError(
                f"note validator returned unreadable output: {completed.stdout.strip()}"
            ) from None
        return report
