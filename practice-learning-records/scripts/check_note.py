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
    # 折叠块标题与四步标签一律以 meta 声明为准；meta 缺失时退回常量，不从正文猜
    knowledge_summary = (meta.get("knowledge-summary") or [DEFAULT_SUMMARY])[0]
    error_summary = (meta.get("error-summary") or [DEFAULT_ERROR_SUMMARY])[0]
    summaries = (knowledge_summary, error_summary)
    return {
        "tracking_rows": rows or TRACKING_ROWS,
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
    r"^(\d)\. \*\*(本题知识点|规则与机制|考点|为什么错|为什么答不出|英语的表达逻辑|正确表达|可迁移表达)\*\*："
)
MERGED_CHOICES_RE = re.compile(r"A\.\s.*B\.\s")
MERGED_SUBITEMS_RE = re.compile(r"\(a\)[^\n]*\(b\)")
TABLE_ROW_RE = re.compile(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>")
MENU_ITEM_RE = re.compile(r"^### (\S.*?)\s*$")
LEGACY_MENU_HEADING_RE = re.compile(r"^### \d+\.\s+菜单：")
LEGACY_MENU_ITEM_RE = re.compile(r"^\d+\.\s|^菜单：")
MENU_EMOJI_RE = re.compile(
    "^[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2190-\u21FF\uFE0F\u200D]"
)
MENU_FIELD_RE = re.compile(r"^\*\*(讲解要点|可迁移表达)\*\*：")
NOTE_DIR_NAME = "learning-record-notes"
NOTE_CATEGORIES = ("vocabulary", "phrases", "grammar", "usage", "errors", "paper")
STRUCTURED_LINE_RE = re.compile(r"^(?:[-*] |\d+\. )")


def check_filename(path: Path) -> list[dict]:
    """分类前缀只允许五类学习记录分类，禁止 `mixed` 等自造前缀。"""

    if path.parent.name != NOTE_DIR_NAME:
        return []
    match = re.match(r"^([a-z]+)-[a-z0-9][a-z0-9-]*\.md$", path.name)
    if not match:
        return [
            {
                "line": 1,
                "message": f"笔记文件名必须是 `<category>-<slug>.md`：category 取 {', '.join(NOTE_CATEGORIES)} 之一，当前为 `{path.name}`",
            }
        ]
    prefix = match.group(1)
    if prefix not in NOTE_CATEGORIES:
        return [
            {
                "line": 1,
                "message": f"文件名前缀只能取五类学习记录分类（{', '.join(NOTE_CATEGORIES)}），不得使用 `{prefix}` 等自造前缀：主题相同请复用既有文件",
            }
        ]
    return []


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

    # 1. 一级标题只允许日期区块：记录 ID 与知识点写在追踪表格里
    for i, line in enumerate(lines):
        if re.match(r"^# ", line) and not SECTION_RE.match(line):
            add(i + 1, "一级标题只能写成 `# <YYYY-MM-DD HH:MM> · <复习|练习|套题>`：记录 ID 与知识点写进追踪表格的 `记录 ID / 试卷 ID` 与 `目标知识点` 行")

    # 2. 区块标题
    sections = [(i + 1, m.group(1), m.group(2), m.group(3)) for i, line in enumerate(lines) if (m := SECTION_RE.match(line))]
    if not sections:
        add(1, "缺少轮次区块标题，格式为 `# <YYYY-MM-DD HH:MM> · <复习|练习|套题>`")
        return issues

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

    # 5. 每个区块的内部结构
    for idx, (start, date, time, kind) in enumerate(sections):
        end = sections[idx + 1][0] - 1 if idx + 1 < len(sections) else len(lines)
        body = lines[start:end]

        if any(l.strip() == "## 追踪" for l in body):
            add(start, "不再使用 `## 追踪` 子标题，追踪信息直接以无表头表格紧跟日期区块")
        if not any(l.strip() == "## 本轮习题" for l in body):
            add(start, "区块内缺少 `## 本轮习题`")

        for line_off, line in enumerate(body):
            if line.startswith("## ") and line.strip() != "## 本轮习题":
                add(start + line_off, f"不允许出现非模板二级标题：`{line.strip()}`")

        # 追踪表：无表头的 HTML 表格，紧跟日期区块，位于 `## 本轮习题` 之前
        table_open = next((k for k, l in enumerate(body) if l.strip().startswith("<table")), None)
        if table_open is not None and table_open >= 1 and all(l.strip() == "" for l in body[:table_open]):
            add(start + 1, "日期标题与追踪表格之间不能留空行：标题下一行必须直接是 `<table …>`")
        table_close = next((k for k, l in enumerate(body) if l.strip() == "</table>"), None)
        quiz_idx = next((k for k, l in enumerate(body) if l.strip() == "## 本轮习题"), None)
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
                add(start + quiz_idx, "`## 本轮习题` 必须在追踪表格之后")

        for line_off, line in enumerate(body):
            if line.strip().startswith("| 字段 |"):
                add(start + line_off, "追踪信息不再使用 Markdown 表头行，改用无表头 HTML 表格")

        # 6. 题目与菜单项：各自在整块内独立定位，先得到真实位置再判断两者顺序
        heading_positions = [k for k, line in enumerate(body) if MENU_ITEM_RE.match(line)]
        menu_starts = [
            (k, MENU_ITEM_RE.match(body[k]).group(1))
            for k in heading_positions
            if not QUESTION_RE.match(body[k]) or LEGACY_MENU_HEADING_RE.match(body[k])
        ]
        question_starts = [
            (start + k, int(m.group(1)), m.group(2))
            for k, line in enumerate(body)
            if (m := QUESTION_RE.match(line)) and not LEGACY_MENU_HEADING_RE.match(line)
        ]
        if not question_starts:
            add(start, "区块内没有任何 `### <n>. <题型>` 题目")
        for order, (line_no, number, qtype) in enumerate(question_starts, start=1):
            if number != order:
                add(line_no, f"题号必须从 1 连续递增，当前第 {order} 题的编号是 {number}")
            if qtype not in QUESTION_TYPES:
                add(line_no, f"题型必须是固定集合之一：{' / '.join(QUESTION_TYPES)}；当前为 `{qtype}`")

        for k in range(len(question_starts)):
            q_start = question_starts[k][0] - start
            q_end = next((pos for pos in heading_positions if pos > q_start), len(body))
            block = body[q_start:q_end]
            base_line = start + q_start

            fields = [m.group(1) for line in block if (m := FIELD_RE.match(line))]
            if fields[:3] != ["题目", "我的答案", "判定"]:
                add(base_line, "每道题必须依次包含 `**题目**：`、`**我的答案**：`、`**判定**：` 三个字段")

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

            # 折叠块：每题第一个必须是 `知识点讲解`，错误/未作答再追加 `错题讲解`
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

            if not blocks:
                add(base_line, f"每道题都必须有 `{knowledge_summary}` 折叠块，答对的题也要写")
            elif summaries[0] != knowledge_summary:
                add(base_line, f"每题第一个折叠块必须是 `{knowledge_summary}`，当前为 `{summaries[0]}`")
            if summaries.count(knowledge_summary) > 1:
                add(base_line, f"`{knowledge_summary}` 每题只能有一个")

            # 未作答、未完成、漏答一律按“没答出来”处理，四步第 2 步写“为什么答不出”
            is_unanswered = any(word in verdict_text for word in ("未作答", "未完成", "漏答"))
            error_blocks = [summary for summary in summaries[1:] if summary != knowledge_summary]
            chinese_mark = {"✅": "完全正确", "⚠️": "⚠️", "❌": "❌"}.get(mark, mark)
            if mark == "✅" and error_blocks:
                add(base_line, f"完全正确的题只写 `{knowledge_summary}`，不写 `{error_summary}`")
            elif mark in ("⚠️", "❌"):
                if not error_blocks:
                    add(base_line, f"判定为 {chinese_mark} 的题必须再写 `{error_summary}` 折叠块")
                elif len(error_blocks) == 1 and error_blocks[0] != error_summary:
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

        # 6b. 菜单项（可选）：不写小节标题，直接以 `### <选项原文>` 接在习题之后
        if menu_starts:
            first_menu_pos = menu_starts[0][0]
            if question_starts and first_menu_pos < question_starts[-1][0] - start:
                add(start + first_menu_pos, "菜单项必须放在所有习题之后：某道习题出现在菜单项之后")
            for k, text in menu_starts:
                line_no = start + k
                stripped = text.strip()
                if stripped in ("", "—"):
                    add(line_no, "菜单项必须写出用户实际选中的选项原文")
                elif stripped == "菜单与讲解":
                    add(line_no, "不再写 `菜单与讲解` 小节标题：直接以 `### <选项原文>` 展示所选菜单")
                elif LEGACY_MENU_ITEM_RE.match(stripped):
                    add(line_no, "菜单标题直接写选项原文：不要加编号，也不要写 `菜单：` 前缀")
                elif stripped in QUESTION_TYPES:
                    add(line_no, f"题目必须写成 `### <n>. <题型>`：`{stripped}` 缺少题号")
                elif MENU_EMOJI_RE.match(stripped):
                    add(line_no, "菜单标题只写选项原文：去掉 emoji")
            for k, _ in menu_starts:
                m_start = k
                malformed_question = MENU_ITEM_RE.match(body[k]).group(1).strip() in QUESTION_TYPES
                if malformed_question:
                    continue
                m_end = next((pos for pos in heading_positions if pos > m_start), len(body))
                mblock = body[m_start:m_end]
                mfields = [m.group(1) for line in mblock if (m := MENU_FIELD_RE.match(line))]
                if mfields[:2] != ["讲解要点", "可迁移表达"]:
                    add(start + m_start, "每条菜单必须依次包含 `**讲解要点**：`、`**可迁移表达**：` 两个字段")
                structured = any(
                    STRUCTURED_LINE_RE.match(line.strip()) or line.strip().startswith("<table")
                    for line in mblock
                )
                if not structured:
                    add(
                        start + m_start,
                        "菜单项的讲解必须拆成有序列表、无序列表或表格逐条记录：不要把多条规则揉成一整段文字",
                    )

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
