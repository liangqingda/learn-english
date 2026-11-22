"""内容层校验：这些写法以前能静默通过，现在必须被 check_note 拦下。"""

from __future__ import annotations

import sys
import tempfile
import re
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from note_store import INDEX_TITLE, apply_practice_index, find_repo_root  # noqa: E402

REPO_ROOT = find_repo_root(Path(__file__))

import check_note  # noqa: E402

NOTES_DIR = "learning-record-notes"


def basic_block(values: dict[str, str]) -> str:
    """文件顶部的「基础信息」折叠块：整个文件唯一一份。"""
    rows = "\n".join(
        f"<tr><td>{row}</td><td>{values.get(row, '—')}</td></tr>" for row in check_note.BASIC_ROWS
    )
    return (
        "## 基础信息\n\n"
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        f"{rows}\n"
        "</table>\n\n"
    )


def sentence_making_note(*, stem: str, answer_block: str) -> str:
    """一道造句题：题干与答案块按参数拼接，用于校验题干 / 答案分区与多句答案分行。"""
    basic = {
        "记录 ID / 试卷 ID": "errors:out-west",
        "目标知识点": "out west 不是 outwest",
        "累计复习次数": "1",
        "下次复习": "2026-11-20 12:00",
        "笔记生成时间": "2026-11-07 12:05",
        "笔记更新时间": "2026-11-07 12:05",
    }
    table = (
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        "<tr><td>生成时间</td><td>2026-11-07 12:00</td></tr>\n"
        "<tr><td>本轮得分</td><td>9 / 10</td></tr>\n"
        "<tr><td>题量与错题数</td><td>1 题 / 0 处错误</td></tr>\n"
        "</table>\n"
    )
    knowledge = (
        "<details>\n<summary>知识点讲解</summary>\n\n"
        "- **本题知识点**：out west 作方向状语\n"
        "- **规则与机制**：方位短语保持分写\n"
        "- **英语的表达逻辑**：方向用副词短语表示\n"
        "- **可迁移表达**：head out west\n\n"
        "</details>\n"
    )
    return (
        basic_block(basic)
        + "# 2026-11-07 12:00 · 复习\n\n"
        + "## 本轮习题\n\n"
        + table
        + "\n### 1. 造句\n\n"
        + f"**题目**：{stem}\n\n"
        + answer_block
        + "\n**判定**：✅ 正确\n\n"
        + knowledge
    )


def note_with_explanation(**kwargs) -> str:
    """在第一个日期区块之前插一份 `## 讲解`，用于校验文件级菜单小节的位置。"""
    text = note_text(**kwargs)
    marker = "\n# "
    index = text.index(marker)
    explain = (
        "\n## 讲解\n\n**错误机制**：\n\n- 一条机制\n\n"
        "**可迁移表达**：\n\n- `She headed out west.`（她往西边出发。）\n"
    )
    return text[:index] + explain + text[index:]


def note_text(
    *,
    stamp: str = "2026-11-07 12:00",
    record_id: str = "errors:out-west",
    score: str = "9 / 10",
    counts: str = "1 题 / 0 处错误",
    question: str = "Pick one.",
    answer: str = "B",
    knowledge: str = "out west 是两词短语",
) -> str:
    basic = {
        "记录 ID / 试卷 ID": record_id,
        "目标知识点": "out west 不是 outwest",
        "累计复习次数": "2",
        "下次复习": "2026-11-20 12:00",
        "笔记生成时间": "2026-11-07 12:05",
        "笔记更新时间": "2026-11-07 12:05",
    }
    rows = {
        "生成时间": stamp,
        "分类 · 状态变化": "errors · learning → familiar",
        "本轮得分": score,
        "题量与错题数": counts,
    }
    table = "\n".join(
        f"<tr><td>{row}</td><td>{rows[row]}</td></tr>"
        for row in check_note.ROUND_ROWS
        if rows[row]  # 空值 = 本轮没有这项事实，整行不写
    )
    return (
        basic_block(basic)
        + f"# {stamp} · 复习\n"
        "\n"
        "## 本轮习题\n\n"
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        f"{table}\n"
        "</table>\n\n"
        "### 1. 单项选择\n\n"
        f"**题目**：{question}\n\n"
        "- A. out west\n"
        "- B. outwest\n\n"
        f"**我的答案**：{answer}\n\n"
        "**判定**：✅ 正确\n\n"
        "<details>\n"
        "<summary>知识点讲解</summary>\n\n"
        f"- **本题知识点**：{knowledge}\n"
        "- **规则与机制**：方位短语保持分写\n"
        "- **英语的表达逻辑**：方向用副词短语表示\n"
        "- **可迁移表达**：head out west\n\n"
        "</details>\n"
    )


def paper_note_text(*, second_reference: str | None = "第 1 题", second_details: bool = False) -> str:
    """两题套题笔记；第二题可以只用 `**知识点**：同第 <n> 题` 合并讲解。"""
    basic = {
        "记录 ID / 试卷 ID": "paper:cet4-20261107T220000-abcdef12",
        "目标知识点": "CET-4 阅读 Passage 1",
        "累计复习次数": "—",
        "下次复习": "—",
        "笔记生成时间": "2026-11-07 12:05",
        "笔记更新时间": "2026-11-07 12:05",
    }
    rows = {
        "生成时间": "2026-11-07 12:00",
        "分类 · 状态变化": "",
        "本轮得分": "—",
        "题量与错题数": "2 题 / 0 处错误",
        "主观题得分": "写作 8/15 · 翻译 9/15",
    }
    table = "\n".join(
        f"<tr><td>{row}</td><td>{rows[row]}</td></tr>"
        for row in check_note.expected_round_rows("套题")
        if rows[row]  # 空值 = 本轮没有这项事实，整行不写
    )
    knowledge = (
        "<details>\n<summary>知识点讲解</summary>\n\n"
        "- **本题知识点**：Passage 1 的主旨句在首段末句\n"
        "- **规则与机制**：主题句常带转折连词\n"
        "- **英语的表达逻辑**：先让步后转折\n"
        "- **可迁移表达**：While …, the study argues …\n\n"
        "</details>\n"
    )
    second_tail = (
        knowledge
        if second_details
        else (f"**知识点**：同 {second_reference}\n" if second_reference else "")
    )
    return (
        basic_block(basic)
        + "# 2026-11-07 12:00 · 套题\n"
        "\n"
        "## 本轮习题\n\n"
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        f"{table}\n"
        "</table>\n\n"
        "### 1. 单项选择\n\n"
        "**题目**：What is the main idea?\n\n"
        "- A. first\n"
        "- B. second\n\n"
        "**我的答案**：A\n\n"
        "**判定**：✅ 正确\n\n"
        f"{knowledge}"
        "\n### 2. 单项选择\n\n"
        "**题目**：Which detail supports it?\n\n"
        "- A. line 1\n"
        "- B. line 2\n\n"
        "**我的答案**：B\n\n"
        "**判定**：✅ 正确\n\n"
        f"{second_tail}"
    )


STORY_SENTENCES = (
    "Lin walked out west on a cold morning. "
    "She carried a torch and a map. "
    "The trail bent west after the river. "
    "Rain started before noon. "
    "She found the camp near the old mill. "
    "Nobody was waiting there. "
    "She lit the torch anyway. "
    "By night the rain stopped. "
    "She headed out west again at dawn."
)

STORY_TABLE = (
    "| 故事里的位置 | 当时想表达什么 | 为什么不换别的表达 |\n"
    "|---|---|---|\n"
    "| 第 1 段「walked out west」 | 往西边出发 | out west 是固定方位短语 |\n"
)


DEFAULT_STORY_TITLE = "往西的那条路"


def story_block(
    summary: str,
    sentences: str = STORY_SENTENCES,
    *,
    table: bool = True,
    title: str = DEFAULT_STORY_TITLE,
) -> str:
    """一段故事原文折叠块：summary 按 `<base> [n] · <标题>` 拼。"""
    body = f"{sentences}\n\n她在一个寒冷的早晨往西走。\n\n"
    if table:
        body += STORY_TABLE + "\n"
    head = f"{summary} · {title}" if title else summary
    return f"<details><summary>{head}</summary>\n\n{body}</details>\n\n"


def story_section(*parts: str) -> str:
    return (
        "## 读一个围绕 out west 的小故事\n\n"
        "**讲解要点**：\n"
        "- out west 表示“往西边、在西边”\n"
        "  - `She headed out west.`（她往西边出发。）\n\n"
        + "".join(parts)
    )


def with_menu_section(base: str, section: str) -> str:
    return base + "\n" + section


def second_round(stamp: str, section: str = "") -> str:
    """一个最小的后续轮次区块（最新在前），用于同一天多次练习的校验。"""
    return (
        f"# {stamp} · 复习\n\n"
        "## 本轮习题\n\n"
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        f"<tr><td>生成时间</td><td>{stamp}</td></tr>\n"
        "<tr><td>分类 · 状态变化</td><td>errors · learning → familiar</td></tr>\n"
        "<tr><td>本轮得分</td><td>9 / 10</td></tr>\n"
        "<tr><td>题量与错题数</td><td>1 题 / 0 处错误</td></tr>\n"
        "</table>\n\n"
        "### 1. 单项选择\n\n"
        "**题目**：Pick one.\n\n"
        "**我的答案**：B\n\n"
        "**判定**：✅ 正确\n\n"
        "<details>\n<summary>知识点讲解</summary>\n\n"
        "- **本题知识点**：x\n"
        "- **规则与机制**：x\n"
        "- **英语的表达逻辑**：x\n"
        "- **可迁移表达**：x\n\n"
        "</details>\n"
        + section
    )


def with_second_round(base: str, stamp: str, section: str = "") -> str:
    """把同一天更晚的一轮插到最前，并把 `笔记更新时间` 抬到该轮时间。"""
    index = base.index("\n# ")
    head = base[:index].replace(
        "<tr><td>笔记更新时间</td><td>2026-11-07 12:05</td></tr>",
        f"<tr><td>笔记更新时间</td><td>{stamp}</td></tr>",
        1,
    )
    return (
        head
        + second_round(stamp, section)
        + "\n---\n\n"
        + base[index:].lstrip("\n")
        + "\n"
    )


def menu_practice(title: str = "## 练习「out west」的关键语法结构") -> str:
    return (
        "\n" + title + "\n\n"
        "### 1. 翻译\n\n"
        "**题目**：中译英：她往西边出发了。\n\n"
        "**我的答案**：She headed out west.\n\n"
        "**判定**：✅ 正确\n\n"
        "<details>\n<summary>知识点讲解</summary>\n\n"
        "- **本题知识点**：out west 作方向状语\n"
        "- **规则与机制**：out 与 west 分写\n"
        "- **英语的表达逻辑**：方向副词短语\n"
        "- **可迁移表达**：head out west\n\n"
        "</details>\n"
    )


def menu_practice_scored(
    score: str = "9 / 10",
    counts: str = "1 题 / 0 处错误",
    stamp: str = "2026-11-06 21:00",
) -> str:
    """带三行得分表的菜单项小节：有习题就计分，得分只落在笔记里。"""
    title = "## 练习「out west」的关键语法结构"
    table = (
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        f"<tr><td>生成时间</td><td>{stamp}</td></tr>\n"
        f"<tr><td>本轮得分</td><td>{score}</td></tr>\n"
        f"<tr><td>题量与错题数</td><td>{counts}</td></tr>\n"
        "</table>\n\n"
    )
    return menu_practice(title).replace(title + "\n\n", title + "\n\n" + table, 1)


def practice_note_text(*, menu_counts: str = "1 题 / 0 处错误") -> str:
    """练习轮次：题目自带菜单项标题，该轮不写 `## 本轮习题`，轮次信息表挂在该小节标题下。"""
    base = note_text().replace(
        "# 2026-11-07 12:00 · 复习", "# 2026-11-07 12:00 · 练习"
    ).replace('<tr><td>分类 · 状态变化</td><td>errors · learning → familiar</td></tr>\n', "")
    head, _sep, rest = base.partition("## 本轮习题\n\n")
    table_end = rest.index("</table>") + len("</table>\n\n")
    table = rest[:table_end].replace("1 题 / 0 处错误", menu_counts)
    return head + "## 练习「out west」的关键语法结构\n\n" + table + rest[table_end:]


def with_file_level_section(base: str, section: str) -> str:
    """把讲解型小节放在 `## 讲解` 之后、所有日期区块之前（文件级讲解区）。"""
    index = base.index("\n# ")
    head, rest = base[:index], base[index:]
    if "## 讲解" not in head:
        head += (
            "\n## 讲解\n\n**错误机制**：\n\n- 一条机制\n\n"
            "**可迁移表达**：\n\n- `She headed out west.`（她往西边出发。）\n"
        )
    return head + "\n" + section + rest


class NoteContentValidationTest(unittest.TestCase):
    def check(self, text: str, name: str = "errors-out-west.md") -> list[dict]:
        # 写入命令会给每份习题小节补隐藏锚点与文件级索引，测试样例先跑同一套重建再校验
        text = apply_practice_index(text)
        with tempfile.TemporaryDirectory() as directory:
            notes = Path(directory) / NOTES_DIR
            notes.mkdir()
            # 笔记按分类分目录存放：目录名取文件名前缀
            category = name.split("-", 1)[0]
            path = notes / category / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return check_note.check(path)

    def test_numbered_story_blocks_are_validated_one_by_one(self) -> None:
        text = with_menu_section(
            note_text(),
            story_section(
                story_block("故事原文 1"),
                story_block("故事原文 2", "Only two sentences here. And another one."),
            ),
        )
        self.assert_caught(text, "折叠块 `故事原文 2 · 往西的那条路` 至少要有 8 句英文叙事")

    def test_story_numbering_must_be_consecutive(self) -> None:
        text = with_menu_section(
            note_text(),
            story_section(
                story_block("故事原文 1"),
                story_block("故事原文 3"),
            ),
        )
        self.assert_caught(text, "第 2 段应写")

    def test_every_story_block_needs_its_own_table(self) -> None:
        text = with_menu_section(
            note_text(),
            story_section(
                story_block("故事原文 1"),
                story_block("故事原文 2", table=False),
            ),
        )
        self.assert_caught(text, "折叠块 `故事原文 2 · 往西的那条路` 内必须包含收尾三列表")

    def test_story_table_outside_the_block_is_rejected(self) -> None:
        """收尾三列表必须折叠进故事原文块内，留在块外要被拦下。"""
        text = with_file_level_section(
            note_text(),
            story_section(story_block("故事原文", table=False) + STORY_TABLE),
        )
        self.assert_caught(text, "表格不要留在")

    def test_two_complete_story_blocks_pass(self) -> None:
        text = with_file_level_section(
            note_text(),
            story_section(
                story_block("故事原文 1"),
                story_block("故事原文 2"),
            ),
        )
        self.assertEqual(self.check(text), [])

    def test_single_story_block_must_not_be_numbered(self) -> None:
        text = with_file_level_section(
            note_text(), story_section(story_block("故事原文 1"))
        )
        self.assert_caught(text, "不要编号")

    def test_single_story_block_without_number_passes(self) -> None:
        text = with_file_level_section(
            note_text(), story_section(story_block("故事原文"))
        )
        self.assertEqual(self.check(text), [])

    def test_story_block_without_title_is_rejected(self) -> None:
        """每段原文都要有自己的标题：summary 只有 `故事原文` 时拦下。"""
        text = with_file_level_section(
            note_text(), story_section(story_block("故事原文", title=""))
        )
        self.assert_caught(text, "必须带上标题")

    def test_story_block_with_an_over_long_title_is_rejected(self) -> None:
        text = with_file_level_section(
            note_text(),
            story_section(story_block("故事原文", title="一个长到完全不像标题的故事主题描述文字整整超过二十四个字符")),
        )
        self.assert_caught(text, "标题太长")

    def test_numbered_story_blocks_keep_their_own_titles(self) -> None:
        """编号段各自带标题，校验逐段认标题而不是套用第一段的。"""
        text = with_file_level_section(
            note_text(),
            story_section(
                story_block("故事原文 1", title="先到的那班车"),
                story_block("故事原文 2", title="后来那场雨"),
            ),
        )
        self.assertEqual(self.check(text), [])

    def test_story_section_in_a_round_block_is_rejected(self) -> None:
        """小故事属于文件级讲解区：留在日期区块里必须被拦下。"""
        text = with_menu_section(
            note_text(), story_section(story_block("故事原文"))
        )
        self.assert_caught(text, "日期区块只放习题")

    def test_dialogue_section_in_a_round_block_is_rejected(self) -> None:
        text = with_menu_section(
            note_text(),
            "## 看一套围绕 out west 的完整场景对话\n\n"
            "**讲解要点**：\n- out west 表示往西边\n"
            "  - `She headed out west.`（她往西边出发。）\n\n"
            "<details><summary>场景对话原文 · 问路</summary>\n\n"
            "- **Ann**：Where are you going?（你去哪儿？）\n"
            "- **Ben**：Out west, past the river.（往西，过了河。）\n"
            "- **Ann**：How far?（多远？）\n"
            "- **Ben**：Two days on foot.（走路两天。）\n\n"
            "</details>\n",
        )
        self.assert_caught(text, "日期区块只放习题")

    def test_round_section_with_explanation_points_is_rejected(self) -> None:
        """日期区块里的同名小节只写习题：重复写讲解要点必须被拦下。"""
        text = note_text() + (
            "\n## 用 out west 做翻译练习\n\n"
            "**讲解要点**：\n- 方位短语保持分写\n"
            "  - `She headed out west.`（她往西边出发。）\n"
        )
        self.assert_caught(text, "日期区块只放习题")

    def assert_caught(self, text: str, keyword: str, name: str = "errors-out-west.md") -> None:
        issues = self.check(text, name)
        self.assertTrue(issues, "该写法应当被拦下，但校验通过")
        self.assertTrue(
            any(keyword in issue["message"] for issue in issues),
            [issue["message"] for issue in issues],
        )

    def test_file_level_menu_section_after_explanation_passes(self) -> None:
        """讲解型菜单项写在 `## 讲解` 之后、日期区块之前是合法结构。"""
        text = note_with_explanation().replace(
            "\n# 2026-11-07 12:00 · 复习",
            "\n## 对比 out west 和 in the west\n\n**讲解要点**：\n- 方位短语保持分写\n"
            "  - `She headed out west.`（她往西边出发。）\n"
            "\n# 2026-11-07 12:00 · 复习",
        )
        self.assertEqual(self.check(text), [])

    def test_file_level_menu_section_with_exercises_is_rejected(self) -> None:
        text = note_with_explanation().replace(
            "\n# 2026-11-07 12:00 · 复习",
            "\n## 用 out west 做翻译练习\n\n**讲解要点**：\n- 方位短语保持分写\n\n"
            "### 1. 翻译\n\n**题目**：中译英。\n\n**我的答案**：She headed out west.\n"
            "\n# 2026-11-07 12:00 · 复习",
        )
        self.assert_caught(text, "不要写习题")

    def test_menu_section_before_explanation_is_rejected(self) -> None:
        text = note_with_explanation().replace(
            "## 讲解",
            "## 对比 out west 和 in the west\n\n**讲解要点**：\n- 一条要点\n\n## 讲解",
        )
        self.assert_caught(text, "必须写在 `## 讲解` 之后")

    def test_round_section_with_exercises_only_passes(self) -> None:
        """带习题的菜单项在日期区块里只写习题，不重复讲解要点。"""
        text = with_file_level_section(
            note_text() + (
                "\n## 用 out west 做翻译练习\n\n"
                "### 1. 翻译\n\n"
                "**题目**：中译英：她往西边出发了。\n\n"
                "**我的答案**：She headed out west.\n\n"
                "**判定**：✅ 正确\n\n"
                "<details>\n<summary>知识点讲解</summary>\n\n"
                "- **本题知识点**：out west 作方向状语\n"
                "- **规则与机制**：out 与 west 分写\n"
                "- **英语的表达逻辑**：方向副词短语\n"
                "- **可迁移表达**：head out west\n\n"
                "</details>\n"
            ),
            "## 用 out west 做翻译练习\n",
        )
        self.assertEqual(self.check(text), [])

    def test_same_day_repeated_menu_section_needs_sequence(self) -> None:
        """同一天两份同名习题小节必须按时间升序带 ` - 01`、` - 02`。"""
        text = with_second_round(
            note_text() + menu_practice(), "2026-11-07 21:00", menu_practice()
        )
        self.assert_caught(text, "标题必须带序号")

    def test_same_day_repeated_menu_section_with_sequence_passes(self) -> None:
        text = with_file_level_section(
            with_second_round(
                note_text() + menu_practice("## 练习「out west」的关键语法结构 - 01"),
                "2026-11-07 21:00",
                menu_practice("## 练习「out west」的关键语法结构 - 02"),
            ),
            "## 练习「out west」的关键语法结构\n",
        )
        self.assertEqual(self.check(text), [])

    def check_raw(self, text: str, name: str = "errors-out-west.md") -> list[dict]:
        """不经重建直接校验，用于验证手写笔记会踩到的锚点与索引规则。"""
        with tempfile.TemporaryDirectory() as directory:
            notes = Path(directory) / NOTES_DIR
            notes.mkdir()
            # 笔记按分类分目录存放：目录名取文件名前缀
            category = name.split("-", 1)[0]
            path = notes / category / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return check_note.check(path)

    def test_practice_anchor_and_file_level_index_are_generated(self) -> None:
        """同日两份习题：各自标题行右侧隐藏锚点，文件级小节按时间倒序列出两条索引。"""
        text = with_file_level_section(
            note_text() + menu_practice("## 练习「out west」的关键语法结构 - 01"),
            "## 练习「out west」的关键语法结构\n\n"
            "**讲解要点**：\n\n- 方向副词短语\n"
            "  - `She headed out west.`（她往西边出发。）\n",
        )
        text = apply_practice_index(
            with_second_round(
                text, "2026-11-07 21:00", menu_practice("## 练习「out west」的关键语法结构 - 02")
            )
        )
        self.assertEqual(self.check_raw(text), [])
        self.assertIn("<!-- practice-index -->", text)
        self.assertEqual(text.count("<a id=\"practice-2026-11-07-1200-"), 1)
        self.assertEqual(text.count("<a id=\"practice-2026-11-07-2100-"), 1)
        index_ids = [
            line
            for line in text.split("\n")
            if line.startswith("- [2026-11-07") and "#practice-" in line
        ]
        self.assertEqual(len(index_ids), 2)
        # 索引按时间倒序：21:00 在前，12:00 在后
        self.assertIn("(#practice-2026-11-07-2100-", index_ids[0])
        self.assertIn("(#practice-2026-11-07-1200-", index_ids[-1])

    def test_practice_index_time_comes_from_the_generated_time_row(self) -> None:
        """索引链接的时间取该小节的 `生成时间`，不取日期区块标题：13:10 写的节显示 13:10。"""
        text = with_file_level_section(
            note_text() + menu_practice_scored(stamp="2026-11-07 13:10"),
            "## 练习「out west」的关键语法结构\n\n"
            "**讲解要点**：\n\n- 方向副词短语\n"
            "  - `She headed out west.`（她往西边出发。）\n",
        )
        text = apply_practice_index(text)
        self.assertEqual(self.check_raw(text), [])
        self.assertIn('<a id="practice-2026-11-07-1310-', text)
        self.assertIn("- [2026-11-07 13:10 · 复习](#practice-2026-11-07-1310-", text)

    def test_menu_section_table_must_start_with_generated_time(self) -> None:
        """菜单项小节的表首行必须是 `生成时间`：缺了它，索引链接就没有真实时间可写。"""
        text = with_menu_section(note_text(), menu_practice_scored())
        text = text.replace(
            "<tr><td>生成时间</td><td>2026-11-06 21:00</td></tr>\n", "", 1
        )
        self.assert_caught(text, "信息表行数与顺序必须与模板一致")

    def test_generated_time_may_not_precede_the_round_heading(self) -> None:
        """`生成时间` 可以晚于轮次标题时间，但不能更早。"""
        text = note_text().replace(
            "<tr><td>生成时间</td><td>2026-11-07 12:00</td></tr>",
            "<tr><td>生成时间</td><td>2026-11-07 11:50</td></tr>",
            1,
        )
        self.assert_caught(text, "`生成时间` 不得早于轮次标题时间")

    def test_fix_reports_nothing_on_an_valid_note(self) -> None:
        """合规文件再跑 `--fix` 必须零修复：标题行右侧的锚点不能被当成序号的一部分。"""
        text = apply_practice_index(
            with_file_level_section(
                note_with_explanation() + menu_practice(),
                "## 练习「out west」的关键语法结构\n\n"
                "**讲解要点**：\n\n- 方向副词短语\n"
                "  - `She headed out west.`（她往西边出发。）\n",
            )
        )
        self.assertEqual(self.check_raw(text), [])
        fixed, fixes = check_note.apply_safe_fixes(text)
        self.assertEqual(fixes, [])
        self.assertEqual(fixed, text)

    def test_index_block_sits_after_the_explanation(self) -> None:
        """`复习历史：` 与索引块都落在讲解内容之后、小节末尾，不再挡在正文前面。"""
        text = apply_practice_index(
            with_file_level_section(
                note_with_explanation() + menu_practice(),
                "## 练习「out west」的关键语法结构\n\n"
                "**讲解要点**：\n\n- 方向副词短语\n"
                "  - `She headed out west.`（她往西边出发。）\n",
            )
        )
        self.assertEqual(self.check_raw(text), [])
        round_index = text.index("<!-- round-index -->")
        practice_index = text.index("<!-- practice-index -->")
        self.assertLess(text.index("**错误机制**"), round_index)
        self.assertLess(text.index("**讲解要点**"), practice_index)
        self.assertLess(round_index, text.index("## 练习「out west」的关键语法结构"))
        self.assertLess(text.rindex(INDEX_TITLE), practice_index)
        self.assertEqual(text.count(INDEX_TITLE), 2)

    def test_index_title_is_required(self) -> None:
        """索引块前一行必须是 `复习历史：`，漏掉会被拦下。"""
        text = apply_practice_index(note_with_explanation())
        text = text.replace(f"{INDEX_TITLE}\n", "", 1)
        issues = self.check_raw(text)
        self.assertTrue(any(INDEX_TITLE in issue["message"] for issue in issues))

    def test_content_after_index_block_is_rejected(self) -> None:
        """索引块之后不能再写讲解正文：索引固定在小节末尾。"""
        text = apply_practice_index(
            with_file_level_section(
                note_with_explanation() + menu_practice(),
                "## 练习「out west」的关键语法结构\n\n"
                "**讲解要点**：\n\n- 方向副词短语\n"
                "  - `She headed out west.`（她往西边出发。）\n",
            )
        )
        text = text.replace(
            "<!-- /practice-index -->\n",
            "<!-- /practice-index -->\n\n**补充**：后写的讲解。\n",
            1,
        )
        issues = self.check_raw(text)
        self.assertTrue(any("讲解内容之后（小节末尾）" in issue["message"] for issue in issues))

    def test_round_index_lists_every_round_quiz(self) -> None:
        """`## 讲解` 下按时间倒序列出每个日期区块的 `## 本轮习题`，锚点挂在标题行右侧。"""
        text = apply_practice_index(
            with_second_round(note_with_explanation(), "2026-11-07 21:00")
        )
        self.assertEqual(self.check_raw(text), [])
        self.assertIn("<!-- round-index -->", text)
        entries = [
            line
            for line in text.split("\n")
            if line.startswith("- [2026-11-07") and "#round-" in line
        ]
        self.assertEqual(len(entries), 2)
        self.assertIn("#round-2026-11-07-2100", entries[0])
        self.assertIn("#round-2026-11-07-1200", entries[1])
        self.assertIn('## 本轮习题 <a id="round-2026-11-07-2100"></a>', text)
        self.assertIn('## 本轮习题 <a id="round-2026-11-07-1200"></a>', text)

    def test_missing_round_anchor_is_rejected(self) -> None:
        text = apply_practice_index(note_with_explanation())
        text = text.replace(' <a id="round-2026-11-07-1200"></a>', "", 1)
        issues = self.check_raw(text)
        self.assertTrue(
            any(
                "本轮习题" in issue["message"] and "隐藏锚点" in issue["message"]
                for issue in issues
            )
        )

    def test_round_index_mismatch_is_rejected(self) -> None:
        text = apply_practice_index(
            with_second_round(note_with_explanation(), "2026-11-07 21:00")
        )
        text = text.replace(
            "- [2026-11-07 12:00 · 复习 - 01](#round-",
            "- [2026-11-07 12:00 · 复习 - 09](#round-",
            1,
        )
        issues = self.check_raw(text)
        self.assertTrue(
            any("复习目录与真实日期区块不一致" in issue["message"] for issue in issues)
        )

    def test_missing_practice_anchor_is_rejected(self) -> None:
        text = apply_practice_index(
            with_file_level_section(
                note_text() + menu_practice(),
                "## 练习「out west」的关键语法结构\n\n"
                "**讲解要点**：\n\n- 方向副词短语\n"
                "  - `She headed out west.`（她往西边出发。）\n",
            )
        )
        text = re.sub(r'\s*<a id="[^"]+"></a>', "", text, count=1)
        issues = self.check_raw(text)
        self.assertTrue(any("隐藏锚点" in issue["message"] for issue in issues))

    def test_anchor_from_another_round_is_rejected(self) -> None:
        text = apply_practice_index(
            with_file_level_section(
                note_text() + menu_practice(),
                "## 练习「out west」的关键语法结构\n\n"
                "**讲解要点**：\n\n- 方向副词短语\n"
                "  - `She headed out west.`（她往西边出发。）\n",
            )
        )
        text = text.replace(
            '<a id="practice-2026-11-07-1200-', '<a id="practice-2026-11-07-2100-', 1
        )
        issues = self.check_raw(text)
        self.assertTrue(
            any("锚点与所在区块 / 小节标题不匹配" in issue["message"] for issue in issues)
        )

    def test_index_entry_mismatch_is_rejected(self) -> None:
        text = apply_practice_index(
            with_file_level_section(
                note_text() + menu_practice(),
                "## 练习「out west」的关键语法结构\n\n"
                "**讲解要点**：\n\n- 方向副词短语\n"
                "  - `She headed out west.`（她往西边出发。）\n",
            )
        )
        text = text.replace(
            "- [2026-11-07 12:00 · 复习](#practice-2026-11-07-1200-",
            "- [2026-11-07 12:00 · 练习](#practice-2026-11-07-1200-",
            1,
        )
        issues = self.check_raw(text)
        self.assertTrue(any("索引与真实习题小节不一致" in issue["message"] for issue in issues))

    def test_stale_index_block_without_exercises_is_rejected(self) -> None:
        text = with_file_level_section(
            note_text(),
            "## 练习「out west」的关键语法结构\n\n"
            "**讲解要点**：\n\n- 方向副词短语\n"
            "  - `She headed out west.`（她往西边出发。）\n"
            "\n<!-- practice-index -->\n"
            "- [2026-11-07 12:00 · 复习](#practice-2026-11-07-1200-00000000)\n"
            "<!-- /practice-index -->\n",
        )
        issues = self.check_raw(text)
        self.assertTrue(any("不要保留索引块" in issue["message"] for issue in issues))

    def test_sequence_suffix_on_a_single_section_is_rejected(self) -> None:
        """当天只有一份时不要加序号后缀。"""
        text = note_text() + menu_practice("## 练习「out west」的关键语法结构 - 01")
        self.assert_caught(text, "不要加序号后缀")

    def test_baseline_note_is_valid(self) -> None:
        self.assertEqual(self.check(note_text()), [])

    def test_empty_question_is_rejected(self) -> None:
        self.assert_caught(note_text(question=""), "`**题目**：` 必须写出完整题干")

    def test_empty_answer_is_rejected(self) -> None:
        self.assert_caught(note_text(answer=""), "`**我的答案**：` 必须写出用户实际答案")

    def test_answer_number_prefix_is_rejected(self) -> None:
        self.assert_caught(note_text(answer="1. B"), "去掉题号前缀")

    def test_answer_leaked_into_stem_is_rejected(self) -> None:
        """带圈序号的答案句写进题干区属于答案混入题目，必须被拦下。"""
        stem = "描述办公室里让你受不了的三件事。用 can't stand 写 3 句话。\n① I can't stand the smoke."
        answer = "**我的答案**：\n- ① I can't stand the smoke."
        self.assert_caught(
            sentence_making_note(stem=stem, answer_block=answer),
            "题干区不得混入用户答案",
        )

    def test_multi_item_answer_must_be_list_items(self) -> None:
        """多句答案裸换行拼接会被 Markdown 并成一段，必须逐条写成列表项。"""
        answer = (
            "**我的答案**：① I can't stand the smoke.\n"
            "② Can you stand the noise?\n"
            "③ I can't stand it when he shouts."
        )
        self.assert_caught(
            sentence_making_note(stem="写 3 句话。", answer_block=answer),
            "逐条写成列表项",
        )

    def test_multi_item_answer_as_list_passes(self) -> None:
        """多句答案逐条写成列表项、题干不含答案句时校验通过。"""
        answer = (
            "**我的答案**：\n"
            "- ① I can't stand the smoke.\n"
            "- ② Can you stand the noise?\n"
            "- ③ I can't stand it when he shouts."
        )
        self.assertEqual(
            self.check(sentence_making_note(stem="写 3 句话。", answer_block=answer)),
            [],
        )

    def test_chained_examples_in_detail_block_are_rejected(self) -> None:
        """折叠块例句步骤用 ／、/ 或 ；可迁移 同行串接多条例句时必须被拦下。"""
        chained = (
            "- **可迁移表达**：I can't stand the smoke.（受不了烟味。）"
            "／I can't stand the noise.（受不了噪音。）"
        )
        self.assert_caught(note_text().replace("- **可迁移表达**：head out west", chained), "逐条写成缩进子项")
        chained_error = (
            "- **正确表达**：The guests love the terrace.（客人们喜欢露台。）"
            "；可迁移：They served coffee there.（他们在那儿供应咖啡。）"
        )
        text = note_text().replace(
            "<summary>知识点讲解</summary>", "<summary>错题讲解</summary>"
        ).replace("- **可迁移表达**：head out west", chained_error)
        self.assert_caught(text, "逐条写成缩进子项")

    def test_example_sub_items_in_detail_block_pass(self) -> None:
        """折叠块例句逐条写成缩进子项、标签行留空时校验通过。"""
        sub_items = (
            "- **可迁移表达**：\n"
            "  - I can't stand the smoke.（受不了烟味。）\n"
            "  - I can't stand the noise.（受不了噪音。）"
        )
        self.assertEqual(
            self.check(note_text().replace("- **可迁移表达**：head out west", sub_items)),
            [],
        )

    def test_ordered_steps_in_detail_block_are_rejected(self) -> None:
        """折叠块四步必须是无序列表；用 1. 2. 3. 4. 有序编号必须被拦下。"""
        numbered = {
            "本题知识点": "1.",
            "规则与机制": "2.",
            "英语的表达逻辑": "3.",
            "可迁移表达": "4.",
        }
        ordered = note_text()
        for label, prefix in numbered.items():
            ordered = ordered.replace(f"- **{label}**：", f"{prefix} **{label}**：")
        self.assert_caught(ordered, "四个无序列表步骤")

    def test_letter_enumerated_answer_must_be_list_items(self) -> None:
        """a./b./c. 与 (a)/(b) 编号的多句答案同样必须逐条写成列表项。"""
        answer = (
            "**我的答案**：a. I can't stand the smoke.\n"
            "b. Can you stand the noise?\n"
            "(c) I can't stand it when he shouts."
        )
        self.assert_caught(
            sentence_making_note(stem="分三点回答。", answer_block=answer),
            "逐条写成列表项",
        )

    def test_letter_enumerated_answer_as_list_passes(self) -> None:
        """字母编号答案写成列表项时校验通过；裸字母选择题答案不受影响。"""
        answer = (
            "**我的答案**：\n"
            "- a. I can't stand the smoke.\n"
            "- b. Can you stand the noise?\n"
            "- (c) I can't stand it when he shouts."
        )
        self.assertEqual(
            self.check(sentence_making_note(stem="分三点回答。", answer_block=answer)),
            [],
        )

    def test_invalid_score_is_rejected(self) -> None:
        self.assert_caught(note_text(score="abc / 999"), "`本轮得分` 只能是")

    def test_record_id_must_match_filename(self) -> None:
        self.assert_caught(
            note_text(record_id="grammar:present-perfect"),
            "记录 ID 的分类",
        )

    def test_chinese_slug_in_filename_is_rejected(self) -> None:
        """中文 slug 会让文件名出现非 ASCII 字符，应当按文件名格式错误拦下。"""
        self.assert_caught(
            note_text(record_id="errors:wait-missing-preposition-for"),
            "笔记文件名必须是 `<category>-<slug>.md`",
            name="errors-wait-后遗漏介词-for.md",
        )

    def test_chinese_record_id_is_rejected(self) -> None:
        self.assert_caught(
            note_text(record_id="errors:wait-后遗漏介词-for"),
            "`记录 ID / 试卷 ID` 必须写成 `<category>:<key>`",
            name="errors-wait-missing-preposition-for.md",
        )

    def test_counts_must_match_real_questions_and_error_blocks(self) -> None:
        self.assert_caught(note_text(counts="6 题 / 3 处错误"), "本轮实际 1 题")
        text = note_text(counts="1 题 / 1 处错误").replace(
            "**判定**：✅ 正确", "**判定**：❌ 错误"
        )
        issues = self.check(text)
        self.assertTrue(any("必须再写 `错题讲解`" in item["message"] for item in issues))

    def test_empty_detail_step_is_rejected(self) -> None:
        self.assert_caught(note_text(knowledge=""), "后面必须写出内容")

    def test_merged_choices_any_pair_are_rejected(self) -> None:
        text = note_text().replace(
            "- A. out west\n- B. outwest\n",
            "- A. out west B. outwest C. in out west\n",
        )
        self.assert_caught(text, "选项必须在同一行只放一个")

    def test_bare_choice_lines_are_rejected(self) -> None:
        text = note_text().replace(
            "- A. out west\n- B. outwest\n",
            "A. out west\nB. outwest\n",
        )
        self.assert_caught(text, "裸写 `A. …`")

    def test_dated_filename_is_rejected(self) -> None:
        self.assert_caught(
            note_text(), "文件名不得带日期", name="errors-out-west-2026-11-06.md"
        )

    def test_duplicate_section_heading_is_rejected(self) -> None:
        text = note_text() + "\n---\n\n" + note_text()
        self.assert_caught(text, "标题重复出现")

    def test_ascending_sections_are_rejected(self) -> None:
        older = note_text(stamp="2026-11-01 09:00")
        text = older + "\n---\n\n" + note_text()
        self.assert_caught(text, "按时间倒序排列")

    def test_same_minute_with_another_kind_is_not_misread_as_ascending(self) -> None:
        practice = note_text(stamp="2026-11-07 12:00").replace("· 复习", "· 练习")
        text = note_text() + "\n---\n\n" + practice
        issues = self.check(text)
        self.assertFalse(any("倒序排列" in item["message"] for item in issues))

    def test_paper_score_and_abandoned_score_forms_are_accepted(self) -> None:
        for score in ("550.5 / 710（无听力模拟折算分）", "710 / 710（无听力模拟折算分）", "—", "评分未保存（已放弃）"):
            with self.subTest(score=score):
                self.assertEqual(self.check(note_text(score=score)), [])

    def test_explanation_mentioning_option_letters_is_not_a_merged_option(self) -> None:
        text = note_text(knowledge="选项 A. 与 B. 的区别在于是否保留介词")
        self.assertEqual(self.check(text), [])

    def test_paper_note_can_merge_knowledge_per_passage(self) -> None:
        self.assertEqual(
            self.check(paper_note_text(), "paper-cet4-20261107t220000-abcdef12.md"), []
        )

    def test_paper_merge_requires_an_earlier_question_with_a_block(self) -> None:
        self.assert_caught(
            paper_note_text(second_reference="第 9 题"),
            "必须指向本节内更早",
            "paper-cet4-20261107t220000-abcdef12.md",
        )

    def test_merge_reference_is_rejected_in_a_non_paper_note(self) -> None:
        without_details = (
            note_text().split("\n<details>\n<summary>知识点讲解</summary>")[0]
            + "**知识点**：同第 1 题\n"
        )
        self.assert_caught(without_details, "每道题都必须有")

    def test_paper_question_with_own_block_must_not_also_reference(self) -> None:
        self.assert_caught(
            paper_note_text(second_details=True).replace(
                "<summary>知识点讲解</summary>\n\n- **本题知识点**：Passage 1 的主旨句在首段末句",
                "<summary>知识点讲解</summary>\n\n**知识点**：同第 1 题\n\n- **本题知识点**：Passage 1 的主旨句在首段末句",
            ),
            "不要再写",
            "paper-cet4-20261107t220000-abcdef12.md",
        )

    def test_fix_repairs_safe_issues_only(self) -> None:
        broken = note_text().replace("**我的答案**：B", "**我的答案**：1. B")
        broken = broken.replace("# 2026-11-07 12:00 · 复习", "# 2026-11-07 12:00 · 复习  ")
        fixed, fixes = check_note.apply_safe_fixes(broken)
        self.assertIn("去掉行尾空格", fixes)
        self.assertIn("去掉 `我的答案` 的题号前缀", fixes)
        self.assertEqual(self.check(fixed), [])

    def test_fix_inserts_the_missing_divider_between_blocks(self) -> None:
        first = note_text()
        second = note_text(stamp="2026-11-06 12:00")
        # 第二个区块不再带文件级基础信息头
        second = second[second.index("# 2026-11-06 12:00") :].replace(
            "# 2026-11-06 12:00 · 复习", "# 2026-11-06 12:00 · 练习"
        )
        joined = first.rstrip("\n") + "\n" + second
        fixed, fixes = check_note.apply_safe_fixes(joined)
        self.assertIn("补上区块之间缺失的 `---` 分隔", fixes)
        self.assertEqual(self.check(fixed), [])

    def test_practice_block_is_counted_in_the_note(self) -> None:
        """练习轮次的得分写进笔记：本轮信息表带分，菜单项小节各带三行表。"""
        self.assertEqual(
            self.check(
                with_file_level_section(
                    practice_note_text(), "## 练习「out west」的关键语法结构\n"
                )
            ),
            [],
        )

    def test_practice_block_needs_questions(self) -> None:
        text = practice_note_text().split("## 练习「out west」的关键语法结构")[0]
        self.assert_caught(text, "练习区块必须有题目")

    def test_review_block_needs_questions(self) -> None:
        """没有菜单标题的复习轮也不能只剩题组标题和表：本轮至少要有一道题。"""
        text = note_text().split("### 1.")[0]
        self.assert_caught(text, "区块内必须有题目")

    def test_block_without_any_group_heading_is_caught(self) -> None:
        """日期标题下既没有 `## 本轮习题`、也没有带标题的题组小节时直接报错。"""
        text = note_text().split("## 本轮习题")[0] + "### 1. 单项选择\n"
        self.assert_caught(text, "区块内缺少题组")

    def test_fix_moves_the_round_table_under_the_quiz_heading(self) -> None:
        """旧布局把表格放在日期标题后，`--fix` 只换位置，内容一字不动。"""
        text = note_text()
        head, _sep, rest = text.partition("## 本轮习题\n\n")
        table_end = rest.index("</table>") + len("</table>\n\n")
        table, remainder = rest[:table_end], rest[table_end:]
        moved = head + table + "## 本轮习题\n\n" + remainder
        self.assert_caught(moved, "日期标题后不要再直接放表格")
        fixed, fixes = check_note.apply_safe_fixes(moved)
        self.assertIn("把日期标题下的轮次信息表移到 `## 本轮习题` 之下", fixes)
        self.assertEqual(self.check(fixed), [])
        quiz_at = fixed.index("## 本轮习题")
        table_at = fixed.index('<table style="border-collapse', quiz_at)
        first_question = fixed.index("### 1.", quiz_at)
        self.assertLess(quiz_at, table_at)
        self.assertLess(table_at, first_question)
        # 只剩位置变了：去掉隐藏锚点与空行后逐行相等
        normalize = lambda source: [
            line.replace(" ", "")
            for line in __import__("re").sub(r' <a id="[^"]*"></a>', "", source).splitlines()
            if line.strip()
        ]
        self.assertEqual(sorted(normalize(fixed)), sorted(normalize(moved)))

    def test_block_sections_must_be_newest_first(self) -> None:
        """同一区块内菜单项小节按落盘时间倒序：旧的在前会被拦下，`--fix` 重排到新的在前。"""
        base_title = "## 练习「out west」的关键语法结构"
        older = menu_practice_scored(stamp="2026-11-07 12:00").replace(
            base_title, f"{base_title} - 01"
        )
        newer = menu_practice_scored(stamp="2026-11-07 21:00").replace(
            base_title, f"{base_title} - 02"
        )
        text = with_file_level_section(
            note_text() + older + newer, base_title + "\n"
        )  # 旧的在前（违规）
        text = apply_practice_index(text)
        self.assert_caught(text, "日期区块内的习题小节必须按落盘时间倒序排列")
        fixed, fixes = check_note.apply_safe_fixes(text)
        self.assertIn("把日期区块内的习题小节按落盘时间倒序重排（最新一节在最前）", fixes)
        self.assertEqual(self.check(fixed), [])
        older_at = fixed.index(f"{base_title} - 01")
        newer_at = fixed.index(f"{base_title} - 02")
        self.assertLess(newer_at, older_at)
        normalize = lambda source: [
            line.replace(" ", "")
            for line in re.sub(r' <a id="[^"]*"></a>', "", source).splitlines()
            if line.strip()
        ]
        self.assertEqual(sorted(normalize(fixed)), sorted(normalize(text)))

    def test_all_mode_walks_the_default_notes_directory(self) -> None:
        import io
        import os
        from contextlib import redirect_stdout
        from unittest import mock

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / NOTES_DIR
            notes.mkdir()
            (notes / "errors-out-west.md").write_text(
                apply_practice_index(note_text()), encoding="utf-8"
            )
            (notes / "README.md").write_text("not a note\n", encoding="utf-8")
            (notes / "errors-broken.md").write_text(note_text(answer=""), encoding="utf-8")
            buffer = io.StringIO()
            with mock.patch.dict(os.environ, {"LEARN_ENGLISH_REPO_ROOT": str(root)}):
                with redirect_stdout(buffer):
                    code = check_note.main(["check_note.py", "--all"])
            report = __import__("json").loads(buffer.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(len(report["checked"]), 2)
            self.assertNotIn("README.md", report["checked"][0])

    def test_all_mode_reports_records_without_notes(self) -> None:
        """笔记按需生成：没有笔记文件的记录只进 missing_notes，不让校验失败。"""
        import io
        import json
        import os
        from contextlib import redirect_stdout
        from unittest import mock

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "learning-records").mkdir()
            (root / "learning-records" / "errors.json").write_text(
                json.dumps(
                    {
                        "records": {
                            "errors:out-west": {"id": "errors:out-west"},
                            "errors:out-east": {"id": "errors:out-east"},
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            notes = root / NOTES_DIR / "errors"
            notes.mkdir(parents=True)
            (notes / "errors-out-west.md").write_text(
                apply_practice_index(note_text()), encoding="utf-8"
            )
            buffer = io.StringIO()
            with mock.patch.dict(os.environ, {"LEARN_ENGLISH_REPO_ROOT": str(root)}):
                with redirect_stdout(buffer):
                    code = check_note.main(["check_note.py", "--all"])
            report = json.loads(buffer.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(report["ok"])
            self.assertEqual(report["missing_notes"]["count"], 1)
            self.assertEqual(report["missing_notes"]["records"], ["errors:out-east"])
            self.assertEqual(report["missing_notes"]["by_category"], {"errors": 1})

    def test_missing_notes_sample_covers_every_category(self) -> None:
        """`errors` 记录占多数时，取样按分类轮流来，别的分类不能被字母序挤没。"""
        import io
        import json
        import os
        from contextlib import redirect_stdout
        from unittest import mock

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "learning-records").mkdir()
            records = {f"errors:out-west-{index}": {} for index in range(60)}
            records["phrases:as-long-as-it-takes"] = {}
            (root / "learning-records" / "errors.json").write_text(
                json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8"
            )
            buffer = io.StringIO()
            with mock.patch.dict(os.environ, {"LEARN_ENGLISH_REPO_ROOT": str(root)}):
                with redirect_stdout(buffer):
                    check_note.main(["check_note.py", "--all"])
            report = json.loads(buffer.getvalue())["missing_notes"]
            self.assertEqual(report["count"], 61)
            self.assertTrue(report["truncated"])
            self.assertEqual(len(report["records"]), 50)
            self.assertIn("phrases:as-long-as-it-takes", report["records"])
            self.assertEqual(report["by_category"], {"errors": 60, "phrases": 1})

    def test_all_mode_reports_missing_notes_without_any_note_file(self) -> None:
        import io
        import json
        import os
        from contextlib import redirect_stdout
        from unittest import mock

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "learning-records").mkdir()
            (root / "learning-records" / "phrases.json").write_text(
                json.dumps({"records": {"phrases:as-long-as-it-takes": {}}}, ensure_ascii=False),
                encoding="utf-8",
            )
            buffer = io.StringIO()
            with mock.patch.dict(os.environ, {"LEARN_ENGLISH_REPO_ROOT": str(root)}):
                with redirect_stdout(buffer):
                    code = check_note.main(["check_note.py", "--all"])
            report = json.loads(buffer.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(report["checked"], [])
            self.assertEqual(report["missing_notes"]["records"], ["phrases:as-long-as-it-takes"])


        text = note_text()
        target = next(
            line for line in text.splitlines() if line.startswith("<tr><td>本轮得分")
        )
        text = text.replace(target, "<tr><td>本轮得分</td><td>x</td></tr>")
        line_no = next(
            index
            for index, line in enumerate(text.splitlines(), start=1)
            if line.startswith("<tr><td>本轮得分")
        )
        issues = self.check(text)
        matched = [item for item in issues if "本轮得分" in item["message"]]
        self.assertTrue(matched)
        self.assertEqual(matched[0]["line"], line_no)

    def test_scored_menu_section_passes(self) -> None:
        text = with_file_level_section(
            with_menu_section(note_text(), menu_practice_scored()),
            "## 练习「out west」的关键语法结构\n",
        )
        self.assertEqual(self.check(text), [])

    def test_menu_section_counts_must_match_its_questions(self) -> None:
        text = with_menu_section(note_text(), menu_practice_scored(counts="2 题 / 0 处错误"))
        self.assert_caught(text, "本小节实际 1 题")

    def test_menu_section_score_must_be_zero_to_ten(self) -> None:
        text = with_menu_section(note_text(), menu_practice_scored(score="abc"))
        self.assert_caught(text, "`本轮得分` 只能是")

    def test_round_table_must_sit_under_quiz_heading(self) -> None:
        """表格挂在日期标题后、`## 本轮习题` 之前要报错：它必须写在标题之下。"""
        text = note_text()
        head, _sep, rest = text.partition("## 本轮习题\n\n")
        table_end = rest.index("</table>") + len("</table>\n\n")
        table, remainder = rest[:table_end], rest[table_end:]
        moved = head + table + "## 本轮习题\n\n" + remainder
        self.assert_caught(moved, "日期标题后不要再直接放表格")

    def test_round_table_without_a_status_change_row_passes(self) -> None:
        """状态没有变化的轮次整行不写 `分类 · 状态变化`，表格照旧合规。"""
        text = note_text().replace(
            '<tr><td>分类 · 状态变化</td><td>errors · learning → familiar</td></tr>\n', ""
        )
        self.assertEqual(self.check(text), [])

    def test_same_status_on_both_sides_is_caught(self) -> None:
        """`familiar → familiar` 说明状态没动：这一行不该出现。"""
        text = note_text().replace("errors · learning → familiar", "errors · familiar → familiar")
        self.assert_caught(text, "两端不能相同")

    def test_non_transition_markers_are_caught(self) -> None:
        """`未入库` / `未评分` 不是状态变化，这一行只写真实迁移。"""
        text = note_text().replace("errors · learning → familiar", "errors · 未入库")
        self.assert_caught(text, "只写真实迁移")

    def test_menu_section_may_not_carry_a_status_change_row(self) -> None:
        """菜单项小节只记这一节自己的得分与题量，状态变化已在轮次表写过一次。"""
        text = with_menu_section(
            note_text(),
            menu_practice_scored().replace(
                "<tr><td>本轮得分</td>",
                "<tr><td>分类 · 状态变化</td><td>errors · learning → familiar</td></tr>\n"
                "<tr><td>本轮得分</td>",
                1,
            ),
        )
        self.assert_caught(text, "只属于本轮表")

    def test_error_pair_line_with_two_fixes_is_rejected(self) -> None:
        """一条 ❌ → ✅ 塞两个正确写法会让错因归属不清，必须被拦下。"""
        pair = (
            "- ❌ I can't stand it no longer. → ✅ I can't stand it any longer.（我再也受不了了。）"
            "／✅ I can no longer stand it.（我再也无法忍受了。）can't 与 no longer 叠成双重否定。\n"
        )
        text = note_with_explanation().replace("- 一条机制\n", "- 一条机制\n" + pair, 1)
        issues = self.check(text)
        self.assertTrue(
            any("一行 `❌ → ✅` 只能给一个改法" in item["message"] for item in issues),
            issues,
        )

    def test_inline_stacked_demos_in_explanation_are_rejected(self) -> None:
        """讲解要点行内嵌两条例句 / 译法必须被拦下：例句下沉为缩进子项，一句一行。"""
        stacked = (
            "- 常可省 for 的动词：wait / sleep。"
            "I waited twenty minutes.（我等了二十分钟）"
            "She slept eight hours.（她睡了八小时）\n"
        )
        text = note_with_explanation().replace("- 一条机制\n", stacked, 1)
        self.assert_caught(text, "内嵌了多条例句")

    def test_inline_stacked_demos_in_menu_section_are_rejected(self) -> None:
        """文件级菜单小节的讲解要点同样不允许把多条例句串在一行。"""
        section = (
            "## 对比 out west 和 in the west\n\n"
            "**讲解要点**：\n"
            "- 两条规则：Let's get takeout.（我们点外卖吧）"
            "He leaves the boxes by the door.（他把盒子留在门边。）\n"
        )
        self.assert_caught(with_file_level_section(note_text(), section), "内嵌了多条例句")

    def test_demos_as_indented_sub_bullets_pass(self) -> None:
        """例句逐条写成缩进子项、一句一行时校验通过。"""
        section = (
            "## 对比 out west 和 in the west\n\n"
            "**讲解要点**：\n"
            "- 常可省 for 的动词：wait / sleep\n"
            "  - I waited twenty minutes.（我等了二十分钟）\n"
            "  - She slept eight hours.（她睡了八小时）\n"
        )
        self.assertEqual(self.check(with_file_level_section(note_text(), section)), [])

    def test_error_pair_lines_split_one_fix_each_pass(self) -> None:
        """同一错点的两个正确写法各起一行，且错因归到 ❌ 一侧时通过。"""
        pair = (
            "- 一个否定意义只由一个词承担，can't 与 no longer 同时出现就是双重否定。\n"
            "  - ❌ I can't stand it no longer.\n"
            "  - ✅ I can't stand it any longer.（我再也受不了了。）\n"
            "  - ✅ I can no longer stand it.（我再也无法忍受了。）\n"
        )
        text = note_with_explanation().replace("- 一条机制\n", pair, 1)
        issues = self.check(text)
        self.assertFalse(
            any("一行 `❌ → ✅` 只能给一个改法" in item["message"] for item in issues),
            issues,
        )


class NoteEntryPointTest(unittest.TestCase):
    """`note.py` 是本 skill 的唯一入口：校验与写入都在本 skill 内完成。"""

    WRAPPER = REPO_ROOT / "skills" / "take-english-study-notes" / "scripts" / "note.py"

    def run_wrapper(
        self, args: list[str], root: Path, cli: str | None = None, stdin_text: str = ""
    ):
        import os
        import subprocess

        environment = dict(os.environ, LEARN_ENGLISH_REPO_ROOT=str(root))
        if cli is not None:
            environment["LEARN_ENGLISH_CLI"] = cli
        return subprocess.run(
            [sys.executable, str(self.WRAPPER), *args],
            capture_output=True,
            text=True,
            env=environment,
            input=stdin_text,
            check=False,
        )

    def test_check_runs_its_own_validator_without_any_other_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / NOTES_DIR
            (notes / "errors").mkdir(parents=True)
            (notes / "errors" / "errors-out-west.md").write_text(
                apply_practice_index(note_text()), encoding="utf-8"
            )
            completed = self.run_wrapper(["check", "--all"], root, cli=str(root / "missing.py"))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(__import__("json").loads(completed.stdout)["ok"])

    def test_tracking_compare_is_skipped_when_the_record_store_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / NOTES_DIR
            notes.mkdir()
            block = (
                "## 基础信息\n\n"
                + basic_block({})
                + "\n\n# 2026-11-09 20:10 · 练习\n\n"
                "## 本轮习题\n\n1. 造句\n\n"
                "**题目**：造句\n\n"
                "**我的答案**：test\n\n"
                "**判定**：正确\n"
            )
            completed = self.run_wrapper(
                [
                    "append",
                    "--file",
                    "learning-record-notes/errors/errors-out-west.md",
                    "--content-file",
                    "-",
                    "--check",
                ],
                root,
                cli=str(root / "missing.py"),
                stdin_text=block,
            )
            payload = __import__("json").loads(completed.stdout)
            self.assertTrue(payload["ok"])
            self.assertIn("tracking_skipped", payload)


class RealNotesTest(unittest.TestCase):
    """仓库里真实笔记必须持续通过校验，模板改版时这里会先响。"""

    def test_every_note_in_the_repository_is_valid(self) -> None:
        notes = check_note.all_note_paths()
        if not notes:
            self.skipTest("仓库里当前没有笔记，跳过整体校验")
        for path in notes:
            with self.subTest(note=path.name):
                self.assertEqual(check_note.check(path), [])


if __name__ == "__main__":
    unittest.main()
