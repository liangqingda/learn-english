"""内容层校验：这些写法以前能静默通过，现在必须被 check_note 拦下。"""

from __future__ import annotations

import sys
import tempfile
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "take-english-study-notes" / "scripts"))

import check_note
from note_store import INDEX_TITLE, apply_practice_index  # noqa: E402

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
        "复习时间": stamp,
        "分类 · 状态变化": "errors · learning → familiar",
        "本轮得分": score,
        "题量与错题数": counts,
    }
    table = "\n".join(
        f"<tr><td>{row}</td><td>{rows[row]}</td></tr>"
        for row in check_note.ROUND_ROWS
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
        f"1. **本题知识点**：{knowledge}\n"
        "2. **规则与机制**：方位短语保持分写\n"
        "3. **英语的表达逻辑**：方向用副词短语表示\n"
        "4. **可迁移表达**：head out west\n\n"
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
        "复习时间": "2026-11-07 12:00",
        "分类 · 状态变化": "paper · 未评分",
        "本轮得分": "—",
        "题量与错题数": "2 题 / 0 处错误",
        "主观题得分": "写作 8/15 · 翻译 9/15",
    }
    table = "\n".join(
        f"<tr><td>{row}</td><td>{rows[row]}</td></tr>"
        for row in check_note.expected_round_rows("套题")
    )
    knowledge = (
        "<details>\n<summary>知识点讲解</summary>\n\n"
        "1. **本题知识点**：Passage 1 的主旨句在首段末句\n"
        "2. **规则与机制**：主题句常带转折连词\n"
        "3. **英语的表达逻辑**：先让步后转折\n"
        "4. **可迁移表达**：While …, the study argues …\n\n"
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


def story_block(summary: str, sentences: str = STORY_SENTENCES) -> str:
    return (
        f"<details><summary>{summary}</summary>\n\n"
        f"{sentences}\n\n"
        "她在一个寒冷的早晨往西走。\n\n"
        "</details>\n\n"
    )


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
        f"<tr><td>复习时间</td><td>{stamp}</td></tr>\n"
        "<tr><td>分类 · 状态变化</td><td>errors · learning → familiar</td></tr>\n"
        "<tr><td>本轮得分</td><td>9 / 10</td></tr>\n"
        "<tr><td>题量与错题数</td><td>1 题 / 0 处错误</td></tr>\n"
        "</table>\n\n"
        "### 1. 单项选择\n\n"
        "**题目**：Pick one.\n\n"
        "**我的答案**：B\n\n"
        "**判定**：✅ 正确\n\n"
        "<details>\n<summary>知识点讲解</summary>\n\n"
        "1. **本题知识点**：x\n"
        "2. **规则与机制**：x\n"
        "3. **英语的表达逻辑**：x\n"
        "4. **可迁移表达**：x\n\n"
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
        "1. **本题知识点**：out west 作方向状语\n"
        "2. **规则与机制**：out 与 west 分写\n"
        "3. **英语的表达逻辑**：方向副词短语\n"
        "4. **可迁移表达**：head out west\n\n"
        "</details>\n"
    )


def menu_practice_scored(
    score: str = "9 / 10", counts: str = "1 题 / 0 处错误"
) -> str:
    """带两行得分表的菜单项小节：有习题就计分，得分只落在笔记里。"""
    title = "## 练习「out west」的关键语法结构"
    table = (
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        f"<tr><td>本轮得分</td><td>{score}</td></tr>\n"
        f"<tr><td>题量与错题数</td><td>{counts}</td></tr>\n"
        "</table>\n\n"
    )
    return menu_practice(title).replace(title + "\n\n", title + "\n\n" + table, 1)


def practice_note_text(*, menu_counts: str = "1 题 / 0 处错误") -> str:
    """练习轮次：本轮得分只写笔记，`## 本轮习题` 只带信息表，题目按菜单项分节。"""
    base = note_text().replace(
        "# 2026-11-07 12:00 · 复习", "# 2026-11-07 12:00 · 练习"
    ).replace("errors · learning → familiar", "errors · 未入库")
    head, _sep, rest = base.partition("## 本轮习题\n\n")
    table_end = rest.index("</table>") + len("</table>\n\n")
    return (
        head
        + "## 本轮习题\n\n"
        + rest[:table_end]
        + "## 练习「out west」的关键语法结构\n\n"
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        "<tr><td>本轮得分</td><td>9 / 10</td></tr>\n"
        f"<tr><td>题量与错题数</td><td>{menu_counts}</td></tr>\n"
        "</table>\n\n"
        + rest[table_end:]
    )


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
                story_block("故事原文 1") + STORY_TABLE,
                story_block("故事原文 2", "Only two sentences here. And another one.") + STORY_TABLE,
            ),
        )
        self.assert_caught(text, "故事原文 2 至少要有 8 句英文叙事")

    def test_story_numbering_must_be_consecutive(self) -> None:
        text = with_menu_section(
            note_text(),
            story_section(
                story_block("故事原文 1") + STORY_TABLE,
                story_block("故事原文 3") + STORY_TABLE,
            ),
        )
        self.assert_caught(text, "第 2 段应写")

    def test_every_story_block_needs_its_own_table(self) -> None:
        text = with_menu_section(
            note_text(),
            story_section(
                story_block("故事原文 1") + STORY_TABLE,
                story_block("故事原文 2"),
            ),
        )
        self.assert_caught(text, "故事原文 2 后面必须紧跟收尾三列表")

    def test_two_complete_story_blocks_pass(self) -> None:
        text = with_file_level_section(
            note_text(),
            story_section(
                story_block("故事原文 1") + STORY_TABLE,
                story_block("故事原文 2") + STORY_TABLE,
            ),
        )
        self.assertEqual(self.check(text), [])

    def test_single_story_block_must_not_be_numbered(self) -> None:
        text = with_file_level_section(
            note_text(), story_section(story_block("故事原文 1") + STORY_TABLE)
        )
        self.assert_caught(text, "不要编号")

    def test_single_story_block_without_number_passes(self) -> None:
        text = with_file_level_section(
            note_text(), story_section(story_block("故事原文") + STORY_TABLE)
        )
        self.assertEqual(self.check(text), [])

    def test_story_section_in_a_round_block_is_rejected(self) -> None:
        """小故事属于文件级讲解区：留在日期区块里必须被拦下。"""
        text = with_menu_section(
            note_text(), story_section(story_block("故事原文") + STORY_TABLE)
        )
        self.assert_caught(text, "日期区块只放习题")

    def test_dialogue_section_in_a_round_block_is_rejected(self) -> None:
        text = with_menu_section(
            note_text(),
            "## 看一套围绕 out west 的完整场景对话\n\n"
            "**讲解要点**：\n- out west 表示往西边\n"
            "  - `She headed out west.`（她往西边出发。）\n\n"
            "<details><summary>场景对话原文</summary>\n\n"
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
        text = note_text() + (
            "\n## 用 out west 做翻译练习\n\n"
            "### 1. 翻译\n\n"
            "**题目**：中译英：她往西边出发了。\n\n"
            "**我的答案**：She headed out west.\n\n"
            "**判定**：✅ 正确\n\n"
            "<details>\n<summary>知识点讲解</summary>\n\n"
            "1. **本题知识点**：out west 作方向状语\n"
            "2. **规则与机制**：out 与 west 分写\n"
            "3. **英语的表达逻辑**：方向副词短语\n"
            "4. **可迁移表达**：head out west\n\n"
            "</details>\n"
        )
        self.assertEqual(self.check(text), [])

    def test_same_day_repeated_menu_section_needs_sequence(self) -> None:
        """同一天两份同名习题小节必须按时间升序带 ` - 01`、` - 02`。"""
        text = with_second_round(
            note_text() + menu_practice(), "2026-11-07 21:00", menu_practice()
        )
        self.assert_caught(text, "标题必须带序号")

    def test_same_day_repeated_menu_section_with_sequence_passes(self) -> None:
        text = with_second_round(
            note_text() + menu_practice("## 练习「out west」的关键语法结构 - 01"),
            "2026-11-07 21:00",
            menu_practice("## 练习「out west」的关键语法结构 - 02"),
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
                "<summary>知识点讲解</summary>\n\n1. **本题知识点**：Passage 1 的主旨句在首段末句",
                "<summary>知识点讲解</summary>\n\n**知识点**：同第 1 题\n\n1. **本题知识点**：Passage 1 的主旨句在首段末句",
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
        """练习轮次的得分写进笔记：本轮信息表带分，菜单项小节各带两行表。"""
        self.assertEqual(self.check(practice_note_text()), [])

    def test_practice_block_needs_questions(self) -> None:
        text = practice_note_text().split("## 练习「out west」的关键语法结构")[0]
        self.assert_caught(text, "练习区块必须有题目")

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

    def test_reported_line_points_at_the_offending_row(self) -> None:
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
        text = with_menu_section(note_text(), menu_practice_scored())
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

    def test_practice_score_not_persisted_uses_weiruku(self) -> None:
        """只写笔记的练习用 `未入库` 标记，说明这份得分没有进入规范记录。"""
        text = note_text().replace("errors · learning → familiar", "errors · 未入库")
        self.assertEqual(self.check(text), [])



class NoteEntryPointTest(unittest.TestCase):
    """`note.py` 是本 skill 的唯一入口：校验与写入都在本 skill 内完成。"""

    WRAPPER = REPO_ROOT / "take-english-study-notes" / "scripts" / "note.py"

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
        self.assertTrue(notes, "仓库里应当至少有一份笔记")
        for path in notes:
            with self.subTest(note=path.name):
                self.assertEqual(check_note.check(path), [])


if __name__ == "__main__":
    unittest.main()
