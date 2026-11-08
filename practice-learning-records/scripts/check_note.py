#!/usr/bin/env python3
"""校验 learning-record-notes 下的复习笔记是否符合固定模板。

用法：
    python3 practice-learning-records/scripts/check_note.py <note.md> [<note.md> ...]
    python3 practice-learning-records/scripts/check_note.py --all
    python3 practice-learning-records/scripts/check_note.py --all --fix

`--all` 校验默认 notes 目录（`$LEARN_ENGLISH_REPO_ROOT/learning-record-notes`）下的全部笔记；
`--fix` 只修可以无争议判定的问题（行尾空格、`我的答案` 的题号前缀、区块之间缺失的 `---`、
缺失的 `笔记更新时间` 行按 `笔记生成时间` 补齐、把追踪表移进 `追踪信息` 折叠块、去掉旧版的 `## 基础信息` 标题、
删掉非套题笔记里恒为 `—` 的 `主观题得分` 行），修完再跑一次校验。成功时输出 {"ok": true, "checked": [...]}；失败时输出逐条 issue 并以退出码 1 结束。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# 文件顶部「基础信息」：记录级字段，整个文件唯一一份，与单次复习无关
BASIC_ROWS = [
    "记录 ID / 试卷 ID",
    "目标知识点",
    "累计复习次数",
    "下次复习",
    "笔记生成时间",
    "笔记更新时间",
]

# 每个轮次区块「本轮信息」：只记这一轮发生过什么
ROUND_ROWS = [
    "复习时间",
    "分类 · 状态变化",
    "本轮得分",
    "题量与错题数",
]

# 只有套题笔记才写这一行：普通复习没有主观题，恒为 `—` 反而是噪音
PAPER_ONLY_ROWS = ("主观题得分",)
PAPER_KIND = "套题"


def expected_round_rows(kind: str) -> list[str]:
    """套题在「题量与错题数」之后多一行主观题得分，其余 kind 与模板逐行一致。"""
    rows = list(TEMPLATE["round_rows"])
    if kind == PAPER_KIND:
        for row in PAPER_ONLY_ROWS:
            if row not in rows:
                anchor = "题量与错题数" if "题量与错题数" in rows else len(rows)
                rows.insert(rows.index(anchor) + 1 if isinstance(anchor, str) else anchor, row)
    return rows

QUESTION_TYPES = [
    "单项选择",
    "填空",
    "改错",
    "改写",
    "翻译",
    "语境判断",
    "造句",
    "短写作",
    "综合运用",
]

TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / "review-note.md"
DEFAULT_TABLE_TAG = '<table style="border-collapse:collapse;width:auto">'
DEFAULT_COL_WIDTH = 150
DEFAULT_KINDS = ("复习", "练习", "套题")
DEFAULT_SUMMARY = "知识点讲解"
DEFAULT_ERROR_SUMMARY = "错题讲解"
DEFAULT_DETAIL_LABELS = ("考点", "为什么错", "英语的表达逻辑", "正确表达")
DEFAULT_UNANSWERED_LABELS = ("考点", "为什么答不出", "英语的表达逻辑", "正确表达")
DEFAULT_KNOWLEDGE_LABELS = ("本题知识点", "规则与机制", "英语的表达逻辑", "可迁移表达")


def parse_meta(text: str) -> dict[str, list[str]]:
    """Read the machine-readable variant block at the top of the template."""
    meta: dict[str, list[str]] = {}
    meta_match = re.search(r"<!--\s*\n?note-template-meta:(.*?)-->", text, re.S)
    if not meta_match:
        return meta
    for line in meta_match.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        parts = [part.strip() for part in value.split("|") if part.strip()]
        if parts:
            meta[field.strip()] = parts
    return meta


def load_template(path: Path | None = None) -> dict[str, object]:
    """Read the canonical note template so the validator and the template cannot drift."""
    template_path = path or TEMPLATE_PATH
    try:
        text = template_path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    meta = parse_meta(text)
    tables = re.findall(r"<table.*?</table>", text, re.S)

    def rows_of(block: str) -> list[str]:
        return [
            match.group(1).strip()
            for match in re.finditer(r"<tr><td>(.*?)</td>", block)
            if match.group(1).strip()
        ]

    basic_rows = rows_of(tables[0]) if tables else []
    round_rows = rows_of(tables[1]) if len(tables) > 1 else []
    table_tag_match = re.search(r"<table[^>]*>", text)
    col_width_match = re.search(r'<col width="(\d+)"', text)
    kinds_match = re.search(r"· <([^<>|]+\|[^<>]+)>", text)
    kinds = (
        tuple(meta["kinds"])
        if "kinds" in meta
        else tuple(part.strip() for part in kinds_match.group(1).split("|"))
        if kinds_match
        else DEFAULT_KINDS
    )
    # 折叠块标题与四步标签一律以 meta 声明为准；meta 缺失时退回常量，不从正文猜
    knowledge_summary = (meta.get("knowledge-summary") or [DEFAULT_SUMMARY])[0]
    error_summary = (meta.get("error-summary") or [DEFAULT_ERROR_SUMMARY])[0]
    summaries = (knowledge_summary, error_summary)
    return {
        "basic_rows": basic_rows or BASIC_ROWS,
        "round_rows": round_rows or ROUND_ROWS,
        "table_tag": table_tag_match.group(0) if table_tag_match else DEFAULT_TABLE_TAG,
        "col_width": int(col_width_match.group(1)) if col_width_match else DEFAULT_COL_WIDTH,
        "kinds": kinds or DEFAULT_KINDS,
        "summaries": summaries,
        "knowledge_summary": knowledge_summary,
        "error_summary": error_summary,
        "knowledge_labels": tuple(meta.get("knowledge-labels", ())) or DEFAULT_KNOWLEDGE_LABELS,
        "error_labels": tuple(meta.get("error-labels", ())) or DEFAULT_DETAIL_LABELS,
        "unanswered_labels": tuple(meta.get("unanswered-labels", ())) or DEFAULT_UNANSWERED_LABELS,
    }


TEMPLATE = load_template()
KIND_PATTERN = "|".join(TEMPLATE["kinds"])
SECTION_RE = re.compile(
    rf"^# (\d{{4}}-\d{{2}}-\d{{2}}) (\d{{2}}:\d{{2}}) · ({KIND_PATTERN})\s*$"
)
QUESTION_RE = re.compile(r"^### (\d+)\. " r"(\S.*?)\s*$")
FIELD_RE = re.compile(r"^\*\*(题目|我的答案|判定)\*\*：")
VERDICT_RE = re.compile(r"^(\*\*判定\*\*：)(✅|⚠️|❌) ?(.*)$")
DETAIL_ITEM_RE = re.compile(
    r"^(\d)\. \*\*(本题知识点|规则与机制|考点|为什么错|为什么答不出|英语的表达逻辑|正确表达|可迁移表达)\*\*：(.*)$"
)
MERGED_CHOICES_RE = re.compile(r"^\s*(?:[-*]\s+)?[A-D]\.\s.*[A-D]\.\s")
MERGED_SUBITEMS_RE = re.compile(r"\(a\)[^\n]*\(b\)")
TABLE_ROW_RE = re.compile(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>")
DATE_SUFFIX_RE = re.compile(r"-\d{4}-\d{2}-\d{2}\.md$")
RECORD_CATEGORIES = ("vocabulary", "phrases", "grammar", "usage", "errors")
SCORE_RE = re.compile(
    r"^(?:\d+(?:\.\d+)? / 10|\d+(?:\.\d+)? / 710(?:（无听力模拟折算分）)?|—|评分未保存（已放弃）)$"
)
COUNTS_RE = re.compile(
    r"^(?P<total>\d+) 题 / (?P<errors>\d+) 处错误(?:（另有 (?P<unanswered>\d+) 题未作答）)?$"
)
NUMBER_PREFIX_RE = re.compile(r"^\d+[.)、]\s*")
REVIEW_COUNT_RE = re.compile(r"^(\d+|—)$")
NEXT_REVIEW_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}|—)$")
SUBJECTIVE_RE = re.compile(r"^(—|写作 \d+/15 · 翻译 \d+/15)$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
UPDATED_ROW_RE = re.compile(
    r"(<tr><td>笔记更新时间</td><td>)(\d{4}-\d{2}-\d{2} \d{2}:\d{2})(</td></tr>)"
)
# 记录 key 允许与真实学习记录一致的中文片段（例如 after-不宜直接当-later-连接后续动作），
# 仍保持小写 ASCII + 中文 + 连字符，禁止空白、斜杠与点号，避免路径歧义。
NOTE_KEY_FRAGMENT = r"[a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff\-]*"
RECORD_ID_RE = re.compile(
    rf"^(vocabulary|phrases|grammar|usage|errors):({NOTE_KEY_FRAGMENT})$"
)
NOTE_NAME_RE = re.compile(rf"^([a-z]+)-({NOTE_KEY_FRAGMENT})\.md$")
TRANSITION_RE = re.compile(
    r"^(vocabulary|phrases|grammar|usage|errors|mixed|paper) · "
    r"((learning|familiar|mastered) → (learning|familiar|mastered)|未评分)$"
)
UNANSWERED_WORDS = ("未作答", "未完成", "漏答")
KNOWLEDGE_REF_RE = re.compile(r"^\*\*知识点\*\*：同\s*第\s*(\d+)\s*题")
MENU_ITEM_RE = re.compile(r"^### (\S.*?)\s*$")
QUIZ_SECTION = "本轮习题"
BASE_SECTION = "基础信息"  # 旧版追踪信息的二级标题，迁移时删掉
BASIC_SECTION = "基础信息"
ROUND_SECTION = "本轮信息"
TRACKING_SUMMARY = "追踪信息"  # 旧版轮次折叠块的 summary，迁移时改成 ROUND_SECTION
SECTION2_RE = re.compile(r"^## (?!#|追踪)(\S.*?)\s*$")
LEGACY_MENU_HEADING_RE = re.compile(r"^### \d+\.\s+菜单：")
LEGACY_MENU_ITEM_RE = re.compile(r"^\d+\.\s|^菜单：")
MENU_EMOJI_RE = re.compile(
    "^[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\uFE0F\u200D]"
)
MENU_FIELD_RE = re.compile(r"^\*\*(讲解要点|可迁移表达)\*\*：")
MENU_CHILD_RE = re.compile(r"^(?:\s{2,}|\t)(?:[-*] |\d+\. )")
NOTE_DIR_NAME = "learning-record-notes"
NOTE_CATEGORIES = ("vocabulary", "phrases", "grammar", "usage", "errors", "paper", "mixed")
STRUCTURED_LINE_RE = re.compile(r"^(?:[-*] |\d+\. )")


def filename_category(path: Path) -> str | None:
    """Return the `<category>` prefix of a note file name."""
    match = NOTE_NAME_RE.match(path.name)
    return match.group(1) if match else None


def check_filename(path: Path) -> list[dict]:
    """分类前缀只允许五类学习记录分类，禁止 `mixed` 等自造前缀；文件名不带日期。"""

    if path.parent.name != NOTE_DIR_NAME:
        return []
    issues: list[dict] = []
    if DATE_SUFFIX_RE.search(path.name):
        issues.append(
            {
                "line": 1,
                "message": f"笔记文件名不得带日期：主题相同一律复用同一文件，当前为 `{path.name}`",
            }
        )
    match = NOTE_NAME_RE.match(path.name)
    if not match:
        issues.append(
            {
                "line": 1,
                "message": f"笔记文件名必须是 `<category>-<slug>.md`：category 取 {', '.join(NOTE_CATEGORIES)} 之一，当前为 `{path.name}`",
            }
        )
        return issues
    prefix = match.group(1)
    if prefix not in NOTE_CATEGORIES:
        issues.append(
            {
                "line": 1,
                "message": f"文件名前缀只能取五类学习记录分类（{', '.join(NOTE_CATEGORIES)}），不得使用 `{prefix}` 等自造前缀：主题相同请复用既有文件",
            }
        )
    return issues


def check(path: Path) -> list[dict]:
    issues: list[dict] = []
    if path.name.lower() == "readme.md":
        # 目录说明文件不是轮次笔记，不参与模板校验
        return issues
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    def add(line_no: int, message: str) -> None:
        issues.append({"line": line_no, "message": message})

    for issue in check_filename(path):
        add(issue["line"], issue["message"])

    note_category = filename_category(path)

    # 1. 一级标题只允许日期区块：记录 ID 与知识点写在追踪表格里
    for i, line in enumerate(lines):
        if re.match(r"^# ", line) and not SECTION_RE.match(line):
            add(i + 1, "一级标题只能写成 `# <YYYY-MM-DD HH:MM> · <复习|练习|套题>`：记录 ID 与知识点写进追踪表格的 `记录 ID / 试卷 ID` 与 `目标知识点` 行")

    # 2. 区块标题
    sections = [(i + 1, m.group(1), m.group(2), m.group(3)) for i, line in enumerate(lines) if (m := SECTION_RE.match(line))]
    if not sections:
        add(1, "缺少轮次区块标题，格式为 `# <YYYY-MM-DD HH:MM> · <复习|练习|套题>`")
        return issues

    # 2b. 区块标题不得重复，且必须按时间升序排列（新轮次只能追加在末尾）
    headings = [f"{date} {time} · {kind}" for _, date, time, kind in sections]
    # 排序只比较时间戳：同一分钟的两轮（复习后再练习）用不同 kind 是合法的，
    # 不能因为 `· 复习` / `· 练习` 的字符顺序被判成倒序。
    stamps = [f"{date} {time}" for _, date, time, _kind in sections]
    for index, heading in enumerate(headings):
        if headings.count(heading) > 1 and headings.index(heading) == index:
            add(sections[index][0], f"同一日期区块标题重复出现：`# {heading}`；一轮只能有一个区块")
    for index in range(len(stamps) - 1):
        if stamps[index] > stamps[index + 1]:
            add(
                sections[index + 1][0],
                "日期区块必须按时间从早到晚排列：旧区块保留在文件前部，新一轮只追加到末尾",
            )

    # 3. 旧的错误标题格式（把日期区块写成 `## 追踪` 或降成二级标题）
    for i, line in enumerate(lines):
        if re.match(r"^## 追踪\s*$", line):
            add(i + 1, "`## 追踪` 应为无表头表格，且必须位于日期区块内")

    # 4. 区块之间必须有 --- 分隔
    if len(sections) >= 2:
        for idx in range(len(sections) - 1):
            start_next = sections[idx + 1][0]
            gap = [l.strip() for l in lines[sections[idx][0] : start_next - 1]]
            if "---" not in gap:
                add(start_next, "两个日期区块之间必须有一行 `---` 分隔")

    # 5. 文件顶部的「## 基础信息」：整个文件唯一一份、用二级标题做导航、固定展示
    head_end = sections[0][0] - 1 if sections else len(lines)
    head = lines[:head_end]
    base_heads = [
        k
        for k, l in enumerate(head)
        if SECTION2_RE.match(l) and SECTION2_RE.match(l).group(1).strip() == BASIC_SECTION
    ]
    other_heads = [
        k for k, l in enumerate(head) if SECTION2_RE.match(l) and k not in base_heads
    ]
    h_table = next((k for k, l in enumerate(head) if l.strip().startswith("<table")), None)
    h_table_close = next((k for k, l in enumerate(head) if l.strip() == "</table>"), None)
    if not base_heads:
        add(1, f"文件顶部必须有 `## {BASIC_SECTION}` 标题与追踪表（整个文件唯一一份）：记录 ID、目标知识点、累计复习次数、下次复习、笔记生成时间、笔记更新时间都放在这里")
    elif len(base_heads) > 1:
        add(base_heads[1] + 1, f"`## {BASIC_SECTION}` 整个文件只能出现一次：基础信息与单次复习无关，不要每轮各写一份")
    else:
        h_base = base_heads[0]
        if other_heads:
            add(
                other_heads[0] + 1,
                f"`## {BASIC_SECTION}` 之前不要写其它二级标题，文件从 `## {BASIC_SECTION}` 开始",
            )
        if any(l.strip().startswith("<details") for l in head):
            add(h_base + 1, f"`## {BASIC_SECTION}` 固定展示，不要包进 `<details>` 折叠块")
        if h_table is None or h_table_close is None or h_table_close < h_table:
            add(h_base + 1, "`## 基础信息` 下缺少无表头追踪表：必须写成 `<table>` … `</table>`，每行 `<tr><td>字段</td><td>值</td></tr>`")
        elif h_table < h_base:
            add(h_table + 1, f"追踪表必须写在 `## {BASIC_SECTION}` 之后")
        else:
            inner = head[h_table + 1 : h_table_close]
            if any(l.strip() in ("<thead>", "</thead>") or "<th>" in l for l in inner):
                add(h_table + 1, "追踪表不允许表头：不要写 `<thead>` / `<th>`，也不要用 `| 字段 | 值 |`")
            if not any("<colgroup>" in l and f'width="{TEMPLATE["col_width"]}"' in l for l in inner):
                add(
                    h_table + 1,
                    f"表格必须固定紧凑列宽：紧跟 `<table …>` 写 `<colgroup><col width=\"{TEMPLATE['col_width']}\"><col></colgroup>",
                )
            basic_lines: list[tuple[int, str, str]] = []
            for offset, line in enumerate(inner):
                match = TABLE_ROW_RE.match(line.strip())
                if match:
                    basic_lines.append((h_table + offset + 2, match.group(1).strip(), match.group(2).strip()))
            basic_rows = [row for _, row, _value in basic_lines]
            if basic_rows != TEMPLATE["basic_rows"]:
                add(
                    h_table + 1,
                    "基础信息表行数与顺序必须与模板一致：" + " / ".join(str(row) for row in TEMPLATE["basic_rows"]),
                )
            basic = dict(zip(basic_rows, [value for _, _row, value in basic_lines]))
            basic_line = {row: line_no for line_no, row, _value in basic_lines}
            for line_no, row, value in basic_lines:
                if not value:
                    add(line_no, f"基础信息 `{row}` 的值不能为空；未知时写 `—`")
            record_id = basic.get("记录 ID / 试卷 ID", "")
            if record_id:
                if note_category in RECORD_CATEGORIES:
                    match = RECORD_ID_RE.match(record_id)
                    if not match:
                        add(
                            basic_line.get("记录 ID / 试卷 ID", h_table + 1),
                            f"`记录 ID / 试卷 ID` 必须写成 `<category>:<key>`：当前为 `{record_id}`",
                        )
                    else:
                        if match.group(1) != note_category:
                            add(
                                basic_line.get("记录 ID / 试卷 ID", h_table + 1),
                                f"记录 ID 的分类 `{match.group(1)}` 与文件名前缀 `{note_category}` 不一致",
                            )
                        if f"{note_category}-{match.group(2)}.md" != path.name:
                            add(
                                basic_line.get("记录 ID / 试卷 ID", h_table + 1),
                                f"记录 ID 与文件名不一致：`{record_id}` 应对应 `{note_category}-{match.group(2)}.md`，当前为 `{path.name}`",
                            )
                elif note_category not in ("mixed", "paper") and not RECORD_ID_RE.match(record_id):
                    add(h_table + 1, f"`记录 ID / 试卷 ID` 格式无效：`{record_id}`")
            title_value = basic.get("目标知识点", "")
            if title_value in ("", "—"):
                add(basic_line.get("目标知识点", h_table + 1), "`目标知识点` 必须写记录的 title，不能是 `—`")
            review_count = basic.get("累计复习次数", "")
            if review_count and not REVIEW_COUNT_RE.match(review_count):
                add(basic_line.get("累计复习次数", h_table + 1), f"`累计复习次数` 只能是数字或 `—`：当前为 `{review_count}`")
            next_review = basic.get("下次复习", "")
            if next_review and not NEXT_REVIEW_RE.match(next_review):
                add(
                    basic_line.get("下次复习", h_table + 1),
                    f"`下次复习` 必须是 `YYYY-MM-DD HH:MM` 或 `—`：当前为 `{next_review}`",
                )
            generated_at = basic.get("笔记生成时间", "")
            updated_at = basic.get("笔记更新时间", "")
            if generated_at and not TIMESTAMP_RE.match(generated_at):
                add(
                    basic_line.get("笔记生成时间", h_table + 1),
                    f"`笔记生成时间` 必须是 `YYYY-MM-DD HH:MM`：当前为 `{generated_at}`",
                )
            if updated_at and not TIMESTAMP_RE.match(updated_at):
                add(
                    basic_line.get("笔记更新时间", h_table + 1),
                    f"`笔记更新时间` 必须是 `YYYY-MM-DD HH:MM`：当前为 `{updated_at}`",
                )
            if generated_at and updated_at and TIMESTAMP_RE.match(generated_at) and TIMESTAMP_RE.match(updated_at):
                if updated_at < generated_at:
                    add(
                        basic_line.get("笔记更新时间", h_table + 1),
                        f"`笔记更新时间` 不能早于 `笔记生成时间`：{updated_at} < {generated_at}",
                    )
            if updated_at and TIMESTAMP_RE.match(updated_at) and sections:
                newest_round = max(
                    f"{date} {time}" for _, date, time, _kind in sections
                )
                if updated_at < newest_round:
                    add(
                        basic_line.get("笔记更新时间", h_table + 1),
                        f"`笔记更新时间` 不能早于最后一个日期区块的时间：{updated_at} < {newest_round}；文件改动后必须更新该字段",
                    )

    # 编号条目直接顶格写：`- 1.` / `* 1.` / `- 1)` 都会被 Markdown 解析成无序列表里再套一层有序列表
    for number, line in enumerate(lines, start=1):
        if re.match(r"^\s*[-*+] \d+[.)] ", line):
            add(
                number,
                "编号条目不要写成 `- 1.` / `* 1.` / `- 1)`：Markdown 会把编号解析成无序列表内嵌的有序列表；编号直接顶格写 `1.`",
            )

    # 6. 每个区块的内部结构：二级标题分组（## 本轮习题 + 每个菜单项各一组）
    for idx, (start, date, time, kind) in enumerate(sections):
        end = sections[idx + 1][0] - 1 if idx + 1 < len(sections) else len(lines)
        body = lines[start:end]
        section_tracking: dict[str, str] = {}

        legacy_heading = next(
            (
                k
                for k, l in enumerate(body)
                if SECTION2_RE.match(l)
                and SECTION2_RE.match(l).group(1).strip() in ("追踪", "追踪信息", ROUND_SECTION, BASIC_SECTION)
            ),
            None,
        )
        if legacy_heading is not None:
            add(
                start + legacy_heading + 1,
                "本轮信息不加小标题：表格直接写在日期标题之后；基础信息只在文件顶部写一次",
            )

        group_heads = [k for k, l in enumerate(body) if SECTION2_RE.match(l)]
        if not group_heads:
            add(start, "区块内缺少 `## 本轮习题`")

        if any(
            l.strip().startswith("<details")
            for l in body[: group_heads[0] if group_heads else len(body)]
        ):
            add(start, "本轮信息表固定展示，不要包进 `<details>` 折叠块")

        table_open = next((k for k, l in enumerate(body) if l.strip().startswith("<table")), None)
        table_line = start + table_open + 1 if table_open is not None else start
        table_close = next((k for k, l in enumerate(body) if l.strip() == "</table>"), None)
        if table_open is None or table_close is None or table_close < table_open:
            add(start, "缺少无表头轮次信息表：日期标题下必须直接写 `<table>` … `</table>`，每行 `<tr><td>字段</td><td>值</td></tr>`")
        elif group_heads and table_open > group_heads[0]:
            add(table_line, "轮次信息表必须写在 `## 本轮习题` 之前，紧跟日期标题")
        else:
            inner = body[table_open + 1 : table_close]
            if any(l.strip() in ("<thead>", "</thead>") or "<th>" in l for l in inner):
                add(table_line, "轮次信息表不允许表头：不要写 `<thead>` / `<th>`，也不要用 `| 字段 | 值 |`")
            if not any("<colgroup>" in l and f'width="{TEMPLATE["col_width"]}"' in l for l in inner):
                add(
                    table_line,
                    f"表格必须固定紧凑列宽：紧跟 `<table …>` 写 `<colgroup><col width=\"{TEMPLATE['col_width']}\"><col></colgroup>",
                )
            table_tag = next((l for l in inner if l.strip().startswith("<table")), "").strip()
            table_tag = next((l for l in body[max(0, table_open) : table_open + 1] if l.strip().startswith("<table")), "").strip()
            if table_tag != TEMPLATE["table_tag"]:
                add(
                    table_line,
                    f"表格标签必须与模板一致：`{TEMPLATE['table_tag']}`，避免渲染成整行宽而显得松散",
                )
            row_lines: list[tuple[int, str, str]] = []
            for offset, line in enumerate(inner):
                match = TABLE_ROW_RE.match(line.strip())
                if match:
                    row_lines.append(
                        (
                            start + table_open + offset + 2,
                            match.group(1).strip(),
                            match.group(2).strip(),
                        )
                    )
            rows = [row for _, row, _value in row_lines]
            values = [value for _, _row, value in row_lines]
            expected_rows = expected_round_rows(kind)
            if rows != expected_rows:
                add(
                    table_line,
                    "轮次信息表行数与顺序必须与模板一致：" + " / ".join(str(row) for row in expected_rows),
                )
            tracking = dict(zip(rows, values))
            row_line = {row: line_no for line_no, row, _value in row_lines}
            section_tracking = tracking
            for line_no, row, value in row_lines:
                if not value:
                    add(line_no, f"轮次信息 `{row}` 的值不能为空；未知时写 `—`")
            stamp_text = f"{date} {time}"
            review_time = tracking.get("复习时间", "")
            if review_time != stamp_text:
                add(
                    row_line.get("复习时间", table_line),
                    f"`复习时间` 必须与轮次标题时间一致：应为 `{stamp_text}`，当前为 `{review_time}`",
                )
            transition = tracking.get("分类 · 状态变化", "")
            if transition and not TRANSITION_RE.match(transition):
                add(
                    row_line.get("分类 · 状态变化", table_line),
                    f"`分类 · 状态变化` 必须写成 `<category> · <旧状态> → <新状态>` 或 `<category> · 未评分`：当前为 `{transition}`",
                )
            score = tracking.get("本轮得分", "")
            if score and not SCORE_RE.match(score):
                add(
                    row_line.get("本轮得分", table_line),
                    f"`本轮得分` 只能是 `x / 10`、`xxx / 710（无听力模拟折算分）` 或 `—`：当前为 `{score}`",
                )
            counts_value = tracking.get("题量与错题数", "")
            if counts_value and not COUNTS_RE.match(counts_value):
                add(
                    row_line.get("题量与错题数", table_line),
                    f"`题量与错题数` 必须写成 `N 题 / M 处错误`（有未作答时补 `（另有 K 题未作答）`）：当前为 `{counts_value}`",
                )
            subjective = tracking.get("主观题得分", "")
            if subjective and not SUBJECTIVE_RE.match(subjective):
                add(
                    row_line.get("主观题得分", table_line),
                    f"`主观题得分` 必须是 `写作 x/15 · 翻译 x/15` 或 `—`：当前为 `{subjective}`",
                )
            quiz_pos = next(
                (
                    k
                    for k, l in enumerate(body)
                    if SECTION2_RE.match(l) and SECTION2_RE.match(l).group(1).strip() == QUIZ_SECTION
                ),
                None,
            )
            if quiz_pos is not None and quiz_pos <= table_close:
                add(start + quiz_pos + 1, f"`## {QUIZ_SECTION}` 必须在轮次信息表之后")
        for line_off, line in enumerate(body):
            if line.strip().startswith("| 字段 |"):
                add(start + line_off + 1, "追踪信息不再使用 Markdown 表头行，改用无表头 HTML 表格")

        # 6. 二级标题分组：第一个必须是 `## 本轮习题`，其余每组对应一个菜单项
        groups: list[tuple[int, str, int]] = []
        for gidx, k in enumerate(group_heads):
            title = SECTION2_RE.match(body[k]).group(1).strip()
            g_end = group_heads[gidx + 1] if gidx + 1 < len(group_heads) else len(body)
            groups.append((k, title, g_end))

        quiz_index = next((i for i, (_, title, _) in enumerate(groups) if title == QUIZ_SECTION), None)
        if quiz_index is None:
            if group_heads:  # 一个二级标题都没有时只报一次，避免重复提示
                add(start, "区块内缺少 `## 本轮习题`")
        elif quiz_index != 0:
            add(
                start + groups[quiz_index][0] + 1,
                f"`## {QUIZ_SECTION}` 必须是区块内第一个二级标题：轮次信息表不加小标题，直接跟在日期标题后",
            )

        # 旧写法：菜单项仍写成三级标题
        for k, line in enumerate(body):
            if MENU_ITEM_RE.match(line) and not QUESTION_RE.match(line):
                add(
                    start + k,
                    "菜单项标题必须与 `## 本轮习题` 同级：写成 `## <选项原文>`，其下再按 `### <n>. <题型>` 记录练习",
                )

        for gidx, (g_start, g_title, g_end) in enumerate(groups):
            if gidx == 0 or g_title == QUIZ_SECTION:
                continue
            line_no = start + g_start
            if g_title in ("", "—"):
                add(line_no, "菜单项必须写出用户实际选中的选项原文")
            elif g_title == "菜单与讲解":
                add(line_no, "不允许出现非模板二级标题：`## 菜单与讲解`；菜单项标题直接写选项原文")
            elif LEGACY_MENU_ITEM_RE.match(g_title):
                add(line_no, "菜单标题直接写选项原文：不要加编号，也不要写 `菜单：` 前缀")
            elif g_title in QUESTION_TYPES:
                add(line_no, f"题目必须写成 `### <n>. <题型>`：`{g_title}` 缺少题号")
            elif MENU_EMOJI_RE.match(g_title):
                add(line_no, "菜单标题只写选项原文：去掉 emoji")
            if quiz_index is not None and gidx < quiz_index:
                add(line_no, "菜单项必须放在 `## 本轮习题` 之后：某道习题出现在菜单项之后")

            q_positions = [g_start + k for k, line in enumerate(body[g_start:g_end]) if QUESTION_RE.match(line)]
            intro = body[g_start + 1 : (q_positions[0] if q_positions else g_end)]
            mfields = [m.group(1) for line in intro if (m := MENU_FIELD_RE.match(line))]
            if mfields and mfields[0] != "讲解要点":
                add(
                    line_no,
                    "每个菜单项的第一组字段必须是 `**讲解要点**：`，不要先写 `**可迁移表达**：`",
                )
            if "可迁移表达" in mfields:
                add(
                    line_no,
                    "菜单项只写一组 `**讲解要点**：`：把可迁移表达/示例写成对应要点的缩进子项，不要另起 `**可迁移表达**：`",
                )
            if not mfields:
                add(line_no, "每个菜单项必须有 `**讲解要点**：`，其下用列表逐条写要点")
            points = [
                line
                for line in intro
                if STRUCTURED_LINE_RE.match(line.strip()) and not MENU_CHILD_RE.match(line)
            ]
            children = [line for line in intro if MENU_CHILD_RE.match(line)]
            if mfields[:1] == ["讲解要点"] and not points:
                add(line_no, "`**讲解要点**：` 必须用无序/有序列表逐条写要点，不要揉成一段文字")
            if points and not children:
                add(
                    line_no,
                    "每条讲解要点至少要有一个缩进子项写出对应的可迁移表达或示例（`  - 例句`）",
                )
            section_text = "\n".join(body[g_start:g_end])
            if "场景对话" in g_title and "场景对话原文" not in section_text:
                add(
                    line_no,
                    "场景对话小节必须保留完整对话原文：`<details><summary>场景对话原文</summary>` 不能省，"
                    "只写讲解要点不算完成",
                )
            if "场景对话" in g_title:
                turns = [
                    line
                    for line in section_text.split("\n")
                    if re.match(r"^- \*\*[^*]+\*\*：", line.strip())
                ]
                if len(turns) < 4:
                    add(
                        line_no,
                        f"场景对话原文至少要有 4 句台词（当前 {len(turns)} 句）：对话被截断或只写了开场白，"
                        "等于这一段没有交付",
                    )
            section_opens = section_text.count("<details>")
            section_closes = section_text.count("</details>")
            if section_opens != section_closes:
                add(
                    line_no,
                    f"折叠块必须成对闭合：本小节 `<details>` {section_opens} 个、`</details>` {section_closes} 个，"
                    "漏写闭合标签会把后面的小节整段折进上一个折叠块",
                )
            if not any(
                STRUCTURED_LINE_RE.match(line.strip()) or line.strip().startswith("<table")
                for line in intro
            ):
                add(
                    line_no,
                    "菜单项的讲解必须拆成有序列表、无序列表或表格逐条记录：不要把多条规则揉成一整段文字",
                )

        # 7. 逐组、逐题校验（每组题号都从 1 开始，练习与主习题共用同一套模板）
        for g_start, g_title, g_end in groups:
            q_all = [g_start + k for k, line in enumerate(body[g_start:g_end]) if QUESTION_RE.match(line)]
            errors_count = 0
            unanswered_count = 0
            if not q_all:
                if g_title == QUIZ_SECTION:
                    add(start, "`## 本轮习题` 内没有任何 `### <n>. <题型>` 题目")
                continue
            for order, q_pos in enumerate(q_all, start=1):
                number = int(QUESTION_RE.match(body[q_pos]).group(1))
                qtype = QUESTION_RE.match(body[q_pos]).group(2)
                if number != order:
                    add(start + q_pos + 1, f"题号必须从 1 连续递增，当前第 {order} 题的编号是 {number}")
                if qtype not in QUESTION_TYPES:
                    add(start + q_pos + 1, f"题型必须是固定集合之一：{' / '.join(QUESTION_TYPES)}；当前为 `{qtype}`")

            knowledge_by_number: dict[int, bool] = {}
            for qi, q_pos in enumerate(q_all):
                block = body[q_pos : (q_all[qi + 1] if qi + 1 < len(q_all) else g_end)]
                base_line = start + q_pos
                question_number = int(QUESTION_RE.match(body[q_pos]).group(1))

                fields = [m.group(1) for line in block if (m := FIELD_RE.match(line))]
                if fields[:3] != ["题目", "我的答案", "判定"]:
                    add(base_line, "每道题必须依次包含 `**题目**：`、`**我的答案**：`、`**判定**：` 三个字段")

                field_values: dict[str, str] = {}
                for line in block:
                    match = re.match(r"^\*\*(题目|我的答案|判定)\*\*：\s*(.*)$", line)
                    if match and match.group(1) not in field_values:
                        field_values[match.group(1)] = match.group(2).strip()
                question_text = field_values.get("题目", "")
                answer_text = field_values.get("我的答案", "")
                if not question_text:
                    add(base_line, "`**题目**：` 必须写出完整题干，不能为空")
                if not answer_text:
                    add(base_line, "`**我的答案**：` 必须写出用户实际答案（未作答也要写明，如“不会”），不能为空")
                elif NUMBER_PREFIX_RE.match(answer_text):
                    add(base_line, "`**我的答案**：` 只写答案本身，去掉题号前缀与列表标记（例如 `1. B` 记为 `B`）")

                verdict_line = next((l for l in block if VERDICT_RE.match(l)), None)
                mark = ""
                verdict_text = ""
                if verdict_line is None:
                    add(base_line, "`**判定**：` 必须以 ✅ / ⚠️ / ❌ 之一开头")
                else:
                    mark = VERDICT_RE.match(verdict_line).group(2)
                    verdict_text = VERDICT_RE.match(verdict_line).group(3)
                    if mark not in ("✅", "⚠️", "❌"):
                        add(base_line, "判定标记只能是 ✅ / ⚠️ / ❌")

                details_open = sum(1 for l in block if l.strip() == "<details>")
                details_close = sum(1 for l in block if l.strip() == "</details>")
                if details_open != details_close:
                    add(base_line, "`<details>` 与 `</details>` 数量必须一致")

                blocks: list[list[str]] = []
                current: list[str] | None = None
                for line in block:
                    if line.strip() == "<details>":
                        current = []
                    elif line.strip() == "</details>" and current is not None:
                        blocks.append(current)
                        current = None
                    elif current is not None:
                        current.append(line)

                def block_summary(detail_block: list[str]) -> str:
                    for line in detail_block:
                        stripped = line.strip()
                        if stripped.startswith("<summary>"):
                            return stripped[len("<summary>") : -len("</summary>")].strip()
                    return ""

                summaries = [block_summary(detail_block) for detail_block in blocks]
                knowledge_summary = str(TEMPLATE["knowledge_summary"])
                error_summary = str(TEMPLATE["error_summary"])

                reference_line = next(
                    (line.strip() for line in block if KNOWLEDGE_REF_RE.match(line.strip())),
                    None,
                )
                merged_ref = (
                    int(KNOWLEDGE_REF_RE.match(reference_line).group(1))
                    if reference_line
                    else None
                )
                if not blocks:
                    if note_category == "paper" and merged_ref is not None:
                        if not (1 <= merged_ref < question_number) or not knowledge_by_number.get(merged_ref):
                            add(
                                base_line,
                                f"`**知识点**：同第 {merged_ref} 题` 必须指向本节内更早、且已写 `{knowledge_summary}` 的题目",
                            )
                    else:
                        add(
                            base_line,
                            f"每道题都必须有 `{knowledge_summary}` 折叠块，答对的题也要写；"
                            f"套题可按 Passage/Part 合并讲解，写成 `**知识点**：同第 <n> 题`",
                        )
                elif merged_ref is not None:
                    add(base_line, "已经写了折叠块时不要再写 `**知识点**：同第 <n> 题`")
                elif summaries[0] != knowledge_summary:
                    add(base_line, f"每题第一个折叠块必须是 `{knowledge_summary}`，当前为 `{summaries[0]}`")
                if summaries.count(knowledge_summary) > 1:
                    add(base_line, f"`{knowledge_summary}` 每题只能有一个")
                knowledge_by_number[question_number] = bool(blocks) and summaries[0] == knowledge_summary

                is_unanswered = any(word in verdict_text for word in UNANSWERED_WORDS)
                error_blocks = [summary for summary in summaries[1:] if summary != knowledge_summary]
                if is_unanswered:
                    unanswered_count += 1
                else:
                    errors_count += len(error_blocks)
                chinese_mark = {"✅": "完全正确", "⚠️": "⚠️", "❌": "❌"}.get(mark, mark)
                if mark == "✅" and error_blocks:
                    add(base_line, f"完全正确的题只写 `{knowledge_summary}`，不写 `{error_summary}`")
                elif mark in ("⚠️", "❌"):
                    if not error_blocks:
                        add(base_line, f"判定为 {chinese_mark} 的题必须再写 `{error_summary}` 折叠块")
                    elif len(error_blocks) == 1:
                        if error_blocks[0] != error_summary:
                            add(base_line, f"单个错误折叠块 summary 必须固定为 `{error_summary}`，当前为 `{error_blocks[0]}`")
                    elif len(error_blocks) > 1:
                        for i, summary in enumerate(error_blocks, start=1):
                            if summary != f"{error_summary} {i}":
                                add(
                                    base_line,
                                    f"同一题有多处错误时，summary 必须按顺序写成 `{error_summary} 1`、`2`…，当前第 {i} 个为 `{summary}`",
                                )

                knowledge_labels = list(TEMPLATE["knowledge_labels"])
                error_labels = list(TEMPLATE["unanswered_labels"]) if is_unanswered else list(TEMPLATE["error_labels"])
                for detail_block in blocks:
                    summary = block_summary(detail_block)
                    items = [m for line in detail_block if (m := DETAIL_ITEM_RE.match(line))]
                    order = [int(m.group(1)) for m in items]
                    labels = [m.group(2) for m in items]
                    empty_labels = [m.group(2) for m in items if not m.group(3).strip()]
                    if empty_labels:
                        add(
                            base_line,
                            "讲解折叠块的步骤不能只写标签：`" + "`/`".join(empty_labels) + "` 后面必须写出内容",
                        )
                    if order != [1, 2, 3, 4]:
                        add(base_line, "讲解折叠块必须严格为 1→4 四步")
                    if summary == knowledge_summary:
                        expected_labels = knowledge_labels
                        hint = "知识点讲解四步标签必须为："
                    elif is_unanswered:
                        expected_labels = error_labels
                        hint = "未作答/未完成题的四步标签必须为："
                    else:
                        expected_labels = error_labels
                        hint = "错题讲解四步标签必须与模板一致："
                    if labels != expected_labels:
                        add(base_line, hint + " / ".join(str(label) for label in expected_labels))

            if g_title == QUIZ_SECTION and section_tracking.get("题量与错题数"):
                counts_match = COUNTS_RE.match(section_tracking["题量与错题数"])
                if counts_match:
                    declared_total = int(counts_match.group("total"))
                    declared_errors = int(counts_match.group("errors"))
                    declared_unanswered = int(counts_match.group("unanswered") or 0)
                    if declared_total != len(q_all):
                        add(
                            start,
                            f"`题量与错题数` 的题量写成 {declared_total}，本轮实际 {len(q_all)} 题",
                        )
                    if declared_errors != errors_count:
                        add(
                            start,
                            f"`题量与错题数` 的错误数写成 {declared_errors}，本轮实际写出 {errors_count} 个 `{TEMPLATE['error_summary']}` 块（不含未作答）",
                        )
                    if declared_unanswered != unanswered_count:
                        add(
                            start,
                            f"`题量与错题数` 的未作答数写成 {declared_unanswered}，本轮实际 {unanswered_count} 题未作答",
                        )

        # 8. 渲染合并检查
        for k, line in enumerate(body):
            if MERGED_CHOICES_RE.search(line):
                add(start + k + 1, "选择题选项必须在同一行只放一个（用 `- A. …` 列表项），不得挤在一行")
            if MERGED_SUBITEMS_RE.search(line):
                add(start + k + 1, "多小题的 (a)/(b) 必须逐条写成列表项，不得挤在一行")

    return issues


def repo_root() -> Path:
    override = os.environ.get("LEARN_ENGLISH_REPO_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    # practice-learning-records/scripts/check_note.py → 仓库根
    return Path(__file__).resolve().parents[2]


def all_note_paths() -> list[Path]:
    notes_dir = repo_root() / "learning-record-notes"
    return sorted(path for path in notes_dir.glob("*.md") if path.name.lower() != "readme.md")


def apply_safe_fixes(text: str) -> tuple[str, list[str]]:
    """只修无争议项；任何会改变语义或版式取舍的问题都留给调用方。"""
    fixes: list[str] = []
    lines = text.splitlines()
    cleaned = [line.rstrip() for line in lines]
    if cleaned != lines:
        fixes.append("去掉行尾空格")
        lines = cleaned

    rewritten: list[str] = []
    changed = False
    for line in lines:
        match = re.match(r"^(\*\*我的答案\*\*：)(\d+[.)、]\s*)(\S.*)$", line)
        if match:
            rewritten.append(f"{match.group(1)}{match.group(3)}")
            changed = True
        else:
            rewritten.append(line)
    if changed:
        fixes.append("去掉 `我的答案` 的题号前缀")
        lines = rewritten

    migrated: list[str] = []
    added_updated = False
    for index, line in enumerate(lines):
        migrated.append(line)
        stamp = re.match(
            r"<tr><td>笔记生成时间</td><td>(\d{4}-\d{2}-\d{2} \d{2}:\d{2})</td></tr>", line.strip()
        )
        if not stamp:
            continue
        following = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if following.startswith("<tr><td>笔记更新时间</td>"):
            continue
        migrated.append(f"<tr><td>笔记更新时间</td><td>{stamp.group(1)}</td></tr>")
        added_updated = True
    if added_updated:
        fixes.append("补齐缺失的 `笔记更新时间` 行（按 `笔记生成时间` 迁移）")
        lines = migrated

    # 每轮信息不加小标题：`## 本轮信息` 直接删掉，表格紧跟日期标题
    untitled: list[str] = []
    untitled_any = False
    for line in lines:
        if line.strip() == f"## {ROUND_SECTION}":
            untitled_any = True
            if untitled and not untitled[-1].strip():
                untitled.pop()
            continue
        untitled.append(line)
    if untitled_any:
        fixes.append("去掉每轮多余的 `## 本轮信息` 标题，让表格直接跟在日期标题后")
        lines = untitled

    # 只压缩「日期标题后」与「表格后」的连续空行（删标题迁移的副产物），不动正文里的空行
    compact: list[str] = []
    compact_any = False
    for line in lines:
        if not line.strip() and compact and not compact[-1].strip():
            anchor = next((l for l in reversed(compact) if l.strip()), "")
            if SECTION_RE.match(anchor) or anchor.strip() == "</table>":
                compact_any = True
                continue
        compact.append(line)
    if compact_any:
        fixes.append("把连续空行压缩成一行")
        lines = compact

    # 结构迁移：记录级字段上移到文件顶部唯一一份「基础信息」，每轮只留本轮字段并补 `复习时间`
    headings = [k for k, line in enumerate(lines) if line.startswith("# ") and SECTION_RE.match(line)]
    head_text = "\n".join(lines[: headings[0]]) if headings else "\n".join(lines)
    migrated_split = False
    has_file_head = (
        f"## {BASIC_SECTION}" in head_text or f"<summary>{BASIC_SECTION}</summary>" in head_text
    )
    if headings and not has_file_head:
        blocks = [
            (h, headings[n + 1] if n + 1 < len(headings) else len(lines)) for n, h in enumerate(headings)
        ]
        basic: dict[str, str] = {}
        stamps: list[str] = []
        for h, end in blocks:
            match = SECTION_RE.match(lines[h])
            stamps.append(f"{match.group(1)} {match.group(2)}")
            for k in range(h + 1, end):
                row = TABLE_ROW_RE.match(lines[k].strip())
                if not row:
                    continue
                field = row.group(1).strip()
                value = row.group(2).strip()
                if field in ("累计复习次数", "下次复习", "笔记更新时间"):
                    basic[field] = value
                elif field in BASIC_ROWS and field not in basic:
                    basic[field] = value
        basic.setdefault("笔记生成时间", stamps[0])
        basic.setdefault("笔记更新时间", stamps[-1])
        rebuilt: list[str] = []
        for h, end in blocks:
            match = SECTION_RE.match(lines[h])
            stamp = f"{match.group(1)} {match.group(2)}"
            rebuilt.append(lines[h])
            inserted_time = False
            for k in range(h + 1, end):
                line = lines[k]
                if line.strip() == f"<summary>{TRACKING_SUMMARY}</summary>":
                    rebuilt.append(f"<summary>{ROUND_SECTION}</summary>")
                    continue
                row = TABLE_ROW_RE.match(line.strip())
                if row and row.group(1).strip() in BASIC_ROWS:
                    continue
                rebuilt.append(line)
                if not inserted_time and "<colgroup>" in line:
                    rebuilt.append(f"<tr><td>复习时间</td><td>{stamp}</td></tr>")
                    inserted_time = True
        head_lines = [
            f"<details>",
            f"<summary>{BASIC_SECTION}</summary>",
            "",
            TEMPLATE["table_tag"],
            f'<colgroup><col width="{TEMPLATE["col_width"]}"><col></colgroup>',
        ]
        for field in TEMPLATE["basic_rows"]:
            head_lines.append(f"<tr><td>{field}</td><td>{basic.get(field, '—')}</td></tr>")
        head_lines.extend(["</table>", "</details>", ""])
        prefix = list(lines[: headings[0]])
        while prefix and not prefix[-1].strip():
            prefix.pop()
        if prefix:
            prefix.append("")
        lines = prefix + head_lines + rebuilt
        migrated_split = True
    if migrated_split:
        fixes.append(
            f"把记录级字段上移到文件顶部唯一一份 `{BASIC_SECTION}` 折叠块，并把每轮追踪信息改为 `{ROUND_SECTION}` 且补 `复习时间` 行"
        )

    # 折叠块写法 → 二级标题固定展示：基础信息与本轮信息都不再收起
    promoted: list[str] = []
    promoted_any = False
    index = 0
    summaries = {
        "基础信息": BASIC_SECTION,
        "本轮信息": ROUND_SECTION,
        "追踪信息": ROUND_SECTION,
    }
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        is_summary = stripped.startswith("<summary>") and stripped.endswith("</summary>")
        if (
            stripped == "<details>"
            and index + 1 < len(lines)
            and lines[index + 1].strip().startswith("<summary>")
        ):
            inner = lines[index + 1].strip()[len("<summary>") : -len("</summary>")].strip()
            if inner in summaries:
                promoted.extend([f"## {summaries[inner]}", ""])
                promoted_any = True
                index += 2
                while index < len(lines) and not lines[index].strip():
                    index += 1
                continue
        if stripped == "</details>":
            last = next((l for l in reversed(promoted) if l.strip()), "")
            if last.strip() == "</table>":
                promoted_any = True
                index += 1
                continue
        promoted.append(line)
        index += 1
    if promoted_any:
        fixes.append(f"把 `基础信息` / `本轮信息` 从折叠块改为二级标题固定展示")
        lines = promoted

    joined = "\n".join(lines)
    if "</table>\n\n</details>" in joined:
        lines = joined.replace("</table>\n\n</details>", "</table>\n</details>").split("\n")
        fixes.append("收紧追踪表与 `</details>` 之间的空行")

    pruned: list[str] = []
    current_kind = ""
    pruned_any = False
    for line in lines:
        heading = SECTION_RE.match(line)
        if heading:
            current_kind = heading.group(3)
        if current_kind != PAPER_KIND and re.match(
            r"<tr><td>主观题得分</td><td>—</td></tr>", line.strip()
        ):
            pruned_any = True
            continue
        pruned.append(line)
    if pruned_any:
        fixes.append("删掉非套题笔记里恒为 `—` 的 `主观题得分` 行")
        lines = pruned

    # `笔记更新时间` 必须反映最后一次写入：早于最后一个日期区块时抬到该区块时间
    newest_round = None
    for line in lines:
        match = SECTION_RE.match(line)
        if match:
            stamp = f"{match.group(1)} {match.group(2)}"
            if newest_round is None or stamp > newest_round:
                newest_round = stamp
    if newest_round:
        bumped = False
        for index, line in enumerate(lines):
            row = UPDATED_ROW_RE.match(line.strip())
            if not row or row.group(2) >= newest_round:
                continue
            lines[index] = f"{row.group(1)}{newest_round}{row.group(3)}"
            bumped = True
        if bumped:
            fixes.append("把过期的 `笔记更新时间` 抬到最后一个日期区块的时间")

    output: list[str] = []
    inserted = False
    removed_leading = False
    seen_heading = False
    for line in lines:
        if line.startswith("# ") and SECTION_RE.match(line) and output:
            while output and not output[-1].strip():
                output.pop()
            last = output[-1].strip() if output else ""
            if not seen_heading:
                # 第一个日期区块前只有文件级「基础信息」，不需要 `---` 分隔
                if last == "---":
                    output.pop()
                    while output and not output[-1].strip():
                        output.pop()
                    removed_leading = True
                output.append("")
            elif last != "---":
                output.extend(["", "---", ""])
                inserted = True
            seen_heading = True
        output.append(line)
    if inserted:
        fixes.append("补上区块之间缺失的 `---` 分隔")
    if removed_leading:
        fixes.append("删掉基础信息与第一个日期区块之间多余的 `---` 分隔")

    result = "\n".join(output)
    if text.endswith("\n") or not text:
        result += "\n"
    return result, fixes


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=True, description="校验复习笔记格式")
    parser.add_argument("paths", nargs="*", help="要校验的笔记文件")
    parser.add_argument("--all", action="store_true", help="校验默认 notes 目录下的全部笔记")
    parser.add_argument("--fix", action="store_true", help="修复无争议问题后再校验")
    args = parser.parse_args(argv[1:])

    paths = [Path(item) for item in args.paths]
    if args.all or not paths:
        paths = paths or all_note_paths()
    if not paths:
        print(__doc__)
        return 2

    report: dict = {"ok": True, "checked": [], "issues": []}
    if args.fix:
        report["fixed"] = []
    for path in paths:
        if not path.is_file():
            report["ok"] = False
            report["issues"].append({"file": str(path), "line": 0, "message": "文件不存在"})
            continue
        if args.fix:
            before = path.read_text(encoding="utf-8")
            after, fixes = apply_safe_fixes(before)
            if fixes:
                path.write_text(after, encoding="utf-8")
                report["fixed"].append({"file": str(path), "fixes": fixes})
        report["checked"].append(str(path))
        for issue in check(path):
            report["ok"] = False
            report["issues"].append({"file": str(path), **issue})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
