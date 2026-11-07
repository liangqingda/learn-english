#!/usr/bin/env python3
"""校验 learning-record-notes 下的复习笔记是否符合固定模板。

用法：
    python3 practice-learning-records/scripts/check_note.py <note.md> [<note.md> ...]

成功时输出 {"ok": true, "checked": [...]}；失败时输出逐条 issue 并以退出码 1 结束。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TRACKING_ROWS = [
    "记录 ID / 试卷 ID",
    "分类 · 状态变化",
    "本轮得分",
    "题量与错题数",
    "目标知识点",
    "累计复习次数",
    "下次复习",
    "主观题得分",
    "笔记生成时间",
]

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
DEFAULT_SUMMARY = "展开错题讲解"
DEFAULT_DETAIL_LABELS = ("考点", "为什么错", "英语的表达逻辑", "正确表达")
DEFAULT_UNANSWERED_LABELS = ("考点", "为什么答不出", "英语的表达逻辑", "正确表达")


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
        return {
            "tracking_rows": TRACKING_ROWS,
            "table_tag": DEFAULT_TABLE_TAG,
            "col_width": DEFAULT_COL_WIDTH,
            "kinds": DEFAULT_KINDS,
            "summaries": (DEFAULT_SUMMARY, "展开讲解"),
            "error_labels": DEFAULT_DETAIL_LABELS,
            "unanswered_labels": DEFAULT_UNANSWERED_LABELS,
        }
    meta = parse_meta(text)
    rows = [
        match.group(1).strip()
        for match in re.finditer(r"<tr><td>(.*?)</td>", text)
        if match.group(1).strip()
    ]
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
    summary_match = re.search(r"<summary>(.*?)</summary>", text)
    detail_labels = tuple(
        match.group(1)
        for match in re.finditer(r"^\d\. \*\*([^*]+)\*\*：", text, re.MULTILINE)
    )
    if "summaries" in meta:
        summaries = tuple(meta["summaries"])
        while len(summaries) < 2:
            summaries += (summaries[0] if summaries else DEFAULT_SUMMARY,)
    elif summary_match:
        summaries = (summary_match.group(1), "展开讲解")
    else:
        summaries = (DEFAULT_SUMMARY, "展开讲解")
    return {
        "tracking_rows": rows or TRACKING_ROWS,
        "table_tag": table_tag_match.group(0) if table_tag_match else DEFAULT_TABLE_TAG,
        "col_width": int(col_width_match.group(1)) if col_width_match else DEFAULT_COL_WIDTH,
        "kinds": kinds or DEFAULT_KINDS,
        "summaries": summaries,
        "error_labels": tuple(meta.get("error-labels", ())) or detail_labels or DEFAULT_DETAIL_LABELS,
        "unanswered_labels": tuple(meta.get("unanswered-labels", ())) or DEFAULT_UNANSWERED_LABELS,
    }


TEMPLATE = load_template()
KIND_PATTERN = "|".join(TEMPLATE["kinds"])
SECTION_RE = re.compile(
    rf"^## (\d{{4}}-\d{{2}}-\d{{2}}) (\d{{2}}:\d{{2}}) · ({KIND_PATTERN})\s*$"
)
QUESTION_RE = re.compile(r"^#### (\d+)\. " r"(\S.*?)\s*$")
FIELD_RE = re.compile(r"^\*\*(题目|我的答案|判定)\*\*：")
VERDICT_RE = re.compile(r"^(\*\*判定\*\*：)(✅|⚠️|❌) ?(.*)$")
DETAIL_ITEM_RE = re.compile(r"^(\d)\. \*\*(考点|为什么错|为什么答不出|英语的表达逻辑|正确表达)\*\*：")
MERGED_CHOICES_RE = re.compile(r"A\.\s.*B\.\s")
MERGED_SUBITEMS_RE = re.compile(r"\(a\)[^\n]*\(b\)")
TABLE_ROW_RE = re.compile(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>")
MENU_ITEM_RE = re.compile(r"^#### (\d+)\. 菜单：(\S.*)$")
MENU_FIELD_RE = re.compile(r"^\*\*(讲解要点|可迁移表达)\*\*：")


def check(path: Path) -> list[dict]:
    issues: list[dict] = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    def add(line_no: int, message: str) -> None:
        issues.append({"line": line_no, "message": message})

    # 1. 不允许一级标题：记录 ID 与知识点写在追踪表格里
    for i, line in enumerate(lines):
        if re.match(r"^# ", line):
            add(i + 1, "不使用一级标题：记录 ID 与知识点写进追踪表格的 `记录 ID / 试卷 ID` 与 `目标知识点` 行")

    # 2. 区块标题
    sections = [(i + 1, m.group(1), m.group(2), m.group(3)) for i, line in enumerate(lines) if (m := SECTION_RE.match(line))]
    if not sections:
        add(1, "缺少轮次区块标题，格式为 `## <YYYY-MM-DD HHMM> · <复习|练习|套题>`")
        return issues

    # 3. 旧的错误标题格式（把时间写进一级标题或区块写成 `## 追踪`）
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

    # 5. 每个区块的内部结构
    for idx, (start, date, time, kind) in enumerate(sections):
        end = sections[idx + 1][0] - 1 if idx + 1 < len(sections) else len(lines)
        body = lines[start:end]

        if any(l.strip() == "### 追踪" for l in body):
            add(start, "不再使用 `### 追踪` 子标题，追踪信息直接以无表头表格紧跟日期区块")
        if not any(l.strip() == "### 本轮习题" for l in body):
            add(start, "区块内缺少 `### 本轮习题`")

        for line_off, line in enumerate(body):
            if line.startswith("### ") and line.strip() not in ("### 本轮习题", "### 菜单与讲解"):
                add(start + line_off, f"不允许出现非模板三级标题：`{line.strip()}`")

        # 追踪表：无表头的 HTML 表格，紧跟日期区块，位于 `### 本轮习题` 之前
        table_open = next((k for k, l in enumerate(body) if l.strip().startswith("<table")), None)
        if table_open is not None and table_open >= 1 and all(l.strip() == "" for l in body[:table_open]):
            add(start + 1, "日期标题与追踪表格之间不能留空行：标题下一行必须直接是 `<table …>`")
        table_close = next((k for k, l in enumerate(body) if l.strip() == "</table>"), None)
        quiz_idx = next((k for k, l in enumerate(body) if l.strip() == "### 本轮习题"), None)
        if table_open is None or table_close is None or table_close < table_open:
            add(start, "缺少无表头追踪表格：必须写成 `<table>` … `</table>`，每行 `<tr><td>字段</td><td>值</td></tr>`")
        else:
            inner = body[table_open + 1 : table_close]
            if any(l.strip() in ("<thead>", "</thead>") or "<th>" in l for l in inner):
                add(start + table_open, "追踪表格不允许表头：不要写 `<thead>` / `<th>`，也不要用 `| 字段 | 值 |`")
            if not any("<colgroup>" in l and f'width="{TEMPLATE["col_width"]}"' in l for l in inner):
                add(
                    start + table_open,
                    f"追踪表格必须固定紧凑列宽：紧跟 `<table …>` 写 `<colgroup><col width=\"{TEMPLATE['col_width']}\"><col></colgroup>`",
                )
            table_tag = next((l for l in body[max(0, table_open - 1) : table_open + 1] if l.strip().startswith("<table")), "").strip()
            if table_tag != TEMPLATE["table_tag"]:
                add(
                    start + table_open,
                    f"追踪表格标签必须与模板一致：`{TEMPLATE['table_tag']}`，避免渲染成整行宽而显得松散",
                )
            rows = [m.group(1).strip() for l in inner if (m := TABLE_ROW_RE.match(l.strip()))]
            if rows != TEMPLATE["tracking_rows"]:
                add(
                    start + table_open,
                    "追踪表格行数与顺序必须与模板一致："
                    + " / ".join(str(row) for row in TEMPLATE["tracking_rows"]),
                )
            if quiz_idx is not None and quiz_idx <= table_close:
                add(start + quiz_idx, "`### 本轮习题` 必须在追踪表格之后")

        for line_off, line in enumerate(body):
            if line.strip().startswith("| 字段 |"):
                add(start + line_off, "追踪信息不再使用 Markdown 表头行，改用无表头 HTML 表格")

        # 6. 题目（只统计 `### 本轮习题` 到 `### 菜单与讲解` 之间的题）
        menu_idx = next((k for k, l in enumerate(body) if l.strip() == "### 菜单与讲解"), None)
        quiz_end = menu_idx if menu_idx is not None else len(body)
        question_starts = [
            (start + k, int(m.group(1)), m.group(2))
            for k, line in enumerate(body[:quiz_end])
            if (m := QUESTION_RE.match(line)) and not MENU_ITEM_RE.match(line)
        ]
        if not question_starts:
            add(start, "区块内没有任何 `#### <n>. <题型>` 题目")
        for order, (line_no, number, qtype) in enumerate(question_starts, start=1):
            if number != order:
                add(line_no, f"题号必须从 1 连续递增，当前第 {order} 题的编号是 {number}")
            if qtype not in QUESTION_TYPES:
                add(line_no, f"题型必须是固定集合之一：{' / '.join(QUESTION_TYPES)}；当前为 `{qtype}`")

        for k in range(len(question_starts)):
            q_start = question_starts[k][0] - start
            q_end = question_starts[k + 1][0] - start if k + 1 < len(question_starts) else quiz_end
            block = body[q_start:q_end]
            base_line = start + q_start

            fields = [m.group(1) for line in block if (m := FIELD_RE.match(line))]
            if fields[:3] != ["题目", "我的答案", "判定"]:
                add(base_line, "每道题必须依次包含 `**题目**：`、`**我的答案**：`、`**判定**：` 三个字段")

            verdict_line = next((l for l in block if VERDICT_RE.match(l)), None)
            if verdict_line is None:
                add(base_line, "`**判定**：` 必须以 ✅ / ⚠️ / ❌ 之一开头")
            else:
                mark = VERDICT_RE.match(verdict_line).group(2)
                if mark not in ("✅", "⚠️", "❌"):
                    add(base_line, "判定标记只能是 ✅ / ⚠️ / ❌")

            details_open = sum(1 for l in block if l.strip() == "<details>")
            details_close = sum(1 for l in block if l.strip() == "</details>")
            summaries = [l.strip() for l in block if l.strip().startswith("<summary>")]
            verdict_text = VERDICT_RE.match(verdict_line).group(3) if verdict_line else ""
            is_unanswered = "未作答" in verdict_text
            error_summary = str(TEMPLATE["summaries"][0])
            unanswered_summary = str(TEMPLATE["summaries"][1])
            if details_open != details_close:
                add(base_line, "`<details>` 与 `</details>` 数量必须一致")
            if not is_unanswered and verdict_line is not None and VERDICT_RE.match(verdict_line).group(2) == "✅" and details_open:
                add(base_line, "完全正确的题不写折叠块")
            summary_texts = [s[len("<summary>") : -len("</summary>")].strip() for s in summaries]
            if is_unanswered:
                if not details_open:
                    add(base_line, f"未作答题也要写讲解折叠块，summary 固定为 `{unanswered_summary}`")
                elif len(summaries) != 1:
                    add(base_line, f"未作答题只写一个折叠块，summary 固定为 `{unanswered_summary}`")
                elif summary_texts[0] != unanswered_summary:
                    add(base_line, f"未作答题的 summary 必须固定为 `{unanswered_summary}`，当前为 `{summaries[0]}`")
            elif len(summaries) == 1 and summary_texts[0] != error_summary:
                add(base_line, f"单个折叠块 summary 必须固定为 `{error_summary}`，当前为 `{summaries[0]}`")
            elif len(summaries) > 1:
                for i, summary_text in enumerate(summary_texts, start=1):
                    if summary_text != f"{error_summary} {i}":
                        add(
                            base_line,
                            f"同一题有多处错误时，summary 必须按顺序写成 `{error_summary} 1`、`2`…，当前第 {i} 个为 `{summary_text}`",
                        )

            # 每个折叠块内部固定四步（同一题有多处错误时，各占一个折叠块）
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
            expected_labels = (
                list(TEMPLATE["unanswered_labels"]) if is_unanswered else list(TEMPLATE["error_labels"])
            )
            for detail_block in blocks:
                items = [m for line in detail_block if (m := DETAIL_ITEM_RE.match(line))]
                order = [int(m.group(1)) for m in items]
                labels = [m.group(2) for m in items]
                if order != [1, 2, 3, 4]:
                    add(base_line, "讲解折叠块必须严格为 1→4 四步")
                if labels != expected_labels:
                    add(
                        base_line,
                        ("未作答题讲解四步标签必须为：" if is_unanswered else "错题讲解四步标签必须与模板一致：")
                        + " / ".join(str(label) for label in expected_labels),
                    )

        # 6b. 菜单与讲解（可选；出现则位于习题之后）
        if menu_idx is not None:
            menu_items = [
                (start + k, int(m.group(1)), m.group(2))
                for k, line in enumerate(body[menu_idx:], start=menu_idx)
                if (m := MENU_ITEM_RE.match(line))
            ]
            if not menu_items:
                add(start + menu_idx, "`### 菜单与讲解` 下至少要有 `#### <n>. 菜单：<选项原文>` 一条")
            if question_starts and menu_items and menu_items[0][0] < question_starts[-1][0]:
                add(start + menu_idx, "`### 菜单与讲解` 必须放在所有习题之后")
            for order, (line_no, number, text) in enumerate(menu_items, start=1):
                if number != order:
                    add(line_no, f"菜单编号必须从 1 连续递增，当前第 {order} 条的编号是 {number}")
                if text.strip() in ("", "—"):
                    add(line_no, "菜单项必须写出用户实际选中的选项原文")
            for k in range(len(menu_items)):
                m_start = menu_items[k][0] - start
                m_end = menu_items[k + 1][0] - start if k + 1 < len(menu_items) else len(body)
                mblock = body[m_start:m_end]
                mfields = [m.group(1) for line in mblock if (m := MENU_FIELD_RE.match(line))]
                if mfields[:2] != ["讲解要点", "可迁移表达"]:
                    add(start + m_start, "每条菜单必须依次包含 `**讲解要点**：`、`**可迁移表达**：` 两个字段")

        # 7. 渲染合并检查
        for k, line in enumerate(body):
            if MERGED_CHOICES_RE.search(line):
                add(start + k, "选择题选项必须在同一行只放一个（用 `- A. …` 列表项），不得挤在一行")
            if MERGED_SUBITEMS_RE.search(line):
                add(start + k, "多小题的 (a)/(b) 必须逐条写成列表项，不得挤在一行")

    return issues


def main(argv: list[str]) -> int:
    paths = [Path(p) for p in argv[1:]]
    if not paths:
        print(__doc__)
        return 2
    report = {"ok": True, "checked": [], "issues": []}
    for path in paths:
        if not path.is_file():
            report["ok"] = False
            report["issues"].append({"file": str(path), "line": 0, "message": "文件不存在"})
            continue
        report["checked"].append(str(path))
        for issue in check(path):
            report["ok"] = False
            report["issues"].append({"file": str(path), **issue})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
