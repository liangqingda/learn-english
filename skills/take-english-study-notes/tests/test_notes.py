from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from note_store import NoteError  # noqa: E402
from note_store import NoteStore, _normalize_block, apply_practice_index  # noqa: E402



SCRIPT = SCRIPT_DIR / "note.py"


def round_block(stamp: str = "2026-11-07 21:00", kind: str = "复习", body: str = "第 1 轮") -> str:
    return (
        "## 基础信息\n\n"
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        "<tr><td>记录 ID / 试卷 ID</td><td>errors:out-west</td></tr>\n"
        "<tr><td>目标知识点</td><td>out west 不是 outwest</td></tr>\n"
        "<tr><td>累计复习次数</td><td>2</td></tr>\n"
        "<tr><td>下次复习</td><td>2026-11-23 09:00</td></tr>\n"
        "<tr><td>笔记生成时间</td><td>2026-11-07 21:05</td></tr>\n"
        "<tr><td>笔记更新时间</td><td>2026-11-07 21:05</td></tr>\n"
        "</table>\n\n"
        f"# {stamp} · {kind}\n\n"
        '<table style="border-collapse:collapse;width:auto">\n'
        "<colgroup><col width=\"150\"><col></colgroup>\n"
        f"<tr><td>目标知识点</td><td>{body}</td></tr>\n"
        "</table>\n"
    )


def extra_section(
    title: str = "## 扩展练习",
    marker: str = "别的会话追加的小节",
) -> str:
    """日期区块里合法的菜单项小节：只放习题，不写讲解要点。"""
    return (
        f"\n\n{title}\n\n"
        "### 1. 翻译\n\n"
        f"**题目**：{marker}\n\n"
        "**我的答案**：She headed out west.\n\n"
        "**判定**：✅ 正确\n\n"
        "<details>\n<summary>知识点讲解</summary>\n\n"
        "1. **本题知识点**：out west 是方位短语\n"
        "2. **规则与机制**：out 与 west 分写\n"
        "3. **英语的表达逻辑**：副词短语表方向\n"
        "4. **可迁移表达**：head out west\n\n"
        "</details>\n"
    )


class NoteAppendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.directory.name)
        self.store = NoteStore(self.repo)
        self.note = self.repo / "learning-record-notes" / "errors" / "errors-out-west.md"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_append_part_adds_to_an_existing_section_only(self) -> None:
        self.store.write_explanation(
            self.note,
            "## 基础信息\n\n<table>\n</table>\n\n## 讲解\n\n**错误机制**：\n\n- 讲解\n",
        )
        self.store.append(self.note, round_block())
        self.store.append_section(
            self.note,
            "# 2026-11-07 21:00 · 复习",
            extra_section().strip("\n"),
        )
        result = self.store.append_part(
            self.note,
            "# 2026-11-07 21:00 · 复习",
            "## 扩展练习",
            "### 2. 翻译\n\n**题目**：中译英：她往西边出发了。\n\n"
            "**我的答案**：She headed out west.\n\n"
            "**判定**：✅ 正确\n\n"
            "<details>\n<summary>知识点讲解</summary>\n\n"
            "1. **本题知识点**：out west 作方向状语\n"
            "2. **规则与机制**：out 与 west 分写\n"
            "3. **英语的表达逻辑**：方向副词短语\n"
            "4. **可迁移表达**：head out west\n\n"
            "</details>\n",
        )
        self.assertTrue(result["appended_part"])
        text = self.note.read_text(encoding="utf-8")
        # 一处讲解区骨架小节 + 一处日期区块习题小节
        self.assertEqual(text.count("## 扩展练习"), 2)
        self.assertIn("### 2. 翻译", text)
        self.assertLess(text.index("### 1. 翻译"), text.index("### 2. 翻译"))

    def test_append_section_overwrites_caller_supplied_generated_time(self) -> None:
        """首次落盘时调用方手写的 `生成时间` 被落盘时刻覆盖，不保留手写值。"""
        self.store.append(self.note, round_block())
        section = (
            "## 扩展练习\n\n"
            '<table style="border-collapse:collapse;width:auto">\n'
            '<colgroup><col width="150"></colgroup>\n'
            "<tr><td>生成时间</td><td>2026-11-07 08:10</td></tr>\n"
            "<tr><td>本轮得分</td><td>3 / 10</td></tr>\n"
            "<tr><td>题量与错题数</td><td>1 题 / 1 处错误</td></tr>\n"
            "</table>\n\n"
            "### 1. 翻译\n\n**题目**：她往西边出发了。\n\n"
            "**我的答案**：She headed out west.\n\n**判定**：✅ 正确\n\n"
            "<details>\n<summary>知识点讲解</summary>\n\n"
            "1. **本题知识点**：out west\n2. **规则与机制**：分写\n"
            "3. **英语的表达逻辑**：方向副词\n4. **可迁移表达**：head out west\n\n"
            "</details>\n"
        )
        self.store.append_section(
            self.note, "# 2026-11-07 21:00 · 复习", section
        )
        text = self.note.read_text(encoding="utf-8")
        self.assertNotIn("2026-11-07 08:10", text)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.assertIn(f"<tr><td>生成时间</td><td>{now}</td></tr>", text)

    def test_replace_keeps_existing_generated_time(self) -> None:
        """重写既有小节时保留原有首次落盘时间，不被新时刻覆盖。"""
        self.store.append(self.note, round_block())
        section = (
            "## 扩展练习\n\n"
            '<table style="border-collapse:collapse;width:auto">\n'
            "<tr><td>本轮得分</td><td>6 / 10</td></tr>\n"
            "<tr><td>题量与错题数</td><td>1 题 / 0 处错误</td></tr>\n"
            "</table>\n\n"
            "### 1. 翻译\n\n**题目**：她往西边出发了。\n\n"
            "**我的答案**：She headed out west.\n\n**判定**：✅ 正确\n\n"
            "<details>\n<summary>知识点讲解</summary>\n\n"
            "1. **本题知识点**：out west\n2. **规则与机制**：分写\n"
            "3. **英语的表达逻辑**：方向副词\n4. **可迁移表达**：head out west\n\n"
            "</details>\n"
        )
        self.store.append_section(
            self.note, "# 2026-11-07 21:00 · 复习", section
        )
        before = self.note.read_text(encoding="utf-8")
        match = re.search(r"<tr><td>生成时间</td><td>([^<]+)</td></tr>", before)
        self.assertIsNotNone(match)
        original_stamp = match.group(1)
        self.store.replace_block(
            self.note,
            "# 2026-11-07 21:00 · 复习",
            "# 2026-11-07 21:00 · 复习\n\n"
            "## 扩展练习\n\n"
            '<table style="border-collapse:collapse;width:auto">\n'
            "<tr><td>本轮得分</td><td>7 / 10</td></tr>\n"
            "<tr><td>题量与错题数</td><td>1 题 / 0 处错误</td></tr>\n"
            "</table>\n\n"
            "### 1. 翻译\n\n**题目**：她往西边出发了。\n\n"
            "**我的答案**：She headed out west.\n\n**判定**：✅ 正确\n\n"
            "<details>\n<summary>知识点讲解</summary>\n\n"
            "1. **本题知识点**：out west\n2. **规则与机制**：分写\n"
            "3. **英语的表达逻辑**：方向副词\n4. **可迁移表达**：head out west\n\n"
            "</details>\n",
        )
        text = self.note.read_text(encoding="utf-8")
        self.assertIn(
            f"<tr><td>生成时间</td><td>{original_stamp}</td></tr>", text
        )

    def test_same_day_second_section_gets_a_sequence_suffix(self) -> None:
        """同一天再练同一菜单项：旧份补 ` - 01`，新份是 ` - 02`。"""
        self.store.append(self.note, round_block("2026-11-07 09:00", body="第 1 轮"))
        self.store.append(self.note, round_block("2026-11-07 21:00", body="第 2 轮"))
        self.store.append_section(
            self.note, "# 2026-11-07 09:00 · 复习", extra_section().strip("\n")
        )
        result = self.store.append_section(
            self.note, "# 2026-11-07 21:00 · 复习", extra_section().strip("\n")
        )
        self.assertEqual(result["section"], "## 扩展练习 - 02")
        self.assertEqual(len(result["section_renamed"]), 2)
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("## 扩展练习 - 01", text)
        self.assertIn("## 扩展练习 - 02", text)
        self.assertNotIn("\n## 扩展练习\n", text)

    def test_append_section_inserts_newest_section_before_existing_menu_sections(self) -> None:
        """新小节插在区块前言之后、既有菜单项小节之前（区块内新的在前）。"""
        self.store.append(self.note, round_block("2026-11-07 21:00", body="第 1 轮"))
        self.store.append_section(
            self.note,
            "# 2026-11-07 21:00 · 复习",
            extra_section("## 旧小节", "旧内容").strip("\n"),
        )
        self.store.append_section(
            self.note,
            "# 2026-11-07 21:00 · 复习",
            extra_section("## 新小节", "新内容").strip("\n"),
        )
        text = self.note.read_text(encoding="utf-8")
        self.assertLess(text.index("# 2026-11-07 21:00"), text.index("新内容"))
        self.assertLess(text.index("新内容"), text.index("旧内容"))

    def test_repeated_menu_section_lands_above_the_older_copy(self) -> None:
        """同一菜单项的新一份（` - 02`）排在旧一份（` - 01`）之上。"""
        self.store.append(self.note, round_block("2026-11-07 09:00", body="第 1 轮"))
        self.store.append_section(
            self.note, "# 2026-11-07 09:00 · 复习", extra_section().strip("\n")
        )
        result = self.store.append_section(
            self.note,
            "# 2026-11-07 09:00 · 复习",
            extra_section("## 扩展练习", "新内容").strip("\n"),
        )
        self.assertEqual(result["section"], "## 扩展练习 - 02")
        text = self.note.read_text(encoding="utf-8")
        self.assertLess(text.index("## 扩展练习 - 02"), text.index("## 扩展练习 - 01"))

    def test_append_numbers_sections_of_a_repeated_menu_item(self) -> None:
        """整块 append 里同名菜单小节也按当天顺序编号。"""
        self.store.append(
            self.note,
            (round_block("2026-11-07 09:00", body="第 1 轮") + extra_section()).rstrip("\n"),
        )
        result = self.store.append(
            self.note,
            (round_block("2026-11-07 21:00", body="第 2 轮") + extra_section()).rstrip("\n"),
        )
        self.assertEqual(
            sorted(item["to"] for item in result["section_renamed"]),
            ["## 扩展练习 - 01", "## 扩展练习 - 02"],
        )
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("## 扩展练习 - 01", text)
        self.assertIn("## 扩展练习 - 02", text)

    def test_same_menu_item_on_another_day_stays_unnumbered(self) -> None:
        """跨天各自从「不带后缀」起算。"""
        self.store.append(self.note, round_block("2026-11-07 09:00", body="第 1 轮"))
        self.store.append(self.note, round_block("2026-11-08 09:00", body="第 2 轮"))
        for heading in ("# 2026-11-07 09:00 · 复习", "# 2026-11-08 09:00 · 复习"):
            result = self.store.append_section(
                self.note, heading, extra_section().strip("\n")
            )
            self.assertEqual(result["section"], "## 扩展练习")
            self.assertEqual(result["section_renamed"], [])
        text = self.note.read_text(encoding="utf-8")
        self.assertEqual(
            len([line for line in text.split("\n") if line.startswith("## 扩展练习")]), 2
        )

    def test_append_part_refuses_a_story_block_in_a_round_section(self) -> None:
        """故事原文再选一次要走 append-explain-part，不能追加进日期区块的小节。"""
        self.store.append(self.note, round_block())
        self.store.append_section(
            self.note, "# 2026-11-07 21:00 · 复习", extra_section().strip("\n")
        )
        with self.assertRaises(NoteError) as caught:
            self.store.append_part(
                self.note,
                "# 2026-11-07 21:00 · 复习",
                "## 扩展练习",
                "<details><summary>故事原文 2 · 第二版</summary>\n\nOne line.\n\n</details>\n",
            )
        self.assertIn("日期区块只放习题", str(caught.exception))

    def test_append_section_refuses_explanation_content_in_a_round_block(self) -> None:
        """讲解要点属于文件级讲解区：写进日期区块必须被写入命令拒绝。"""
        self.store.append(self.note, round_block())
        with self.assertRaises(NoteError) as caught:
            self.store.append_section(
                self.note,
                "# 2026-11-07 21:00 · 复习",
                "## 对比 out west 和 in the west\n\n**讲解要点**：\n- 一条要点\n"
                "  - `She headed out west.`（她往西边出发。）\n",
            )
        self.assertIn("日期区块只放习题", str(caught.exception))

    def test_append_refuses_a_story_block_inside_the_round(self) -> None:
        block = round_block() + (
            "\n## 读一个围绕 out west 的小故事\n\n"
            "**讲解要点**：\n- out west 表示往西\n\n"
            "<details><summary>故事原文 · 往西的那条路</summary>\n\nOne line.\n\n</details>\n"
        )
        with self.assertRaises(NoteError) as caught:
            self.store.append(self.note, block)
        self.assertIn("日期区块只放习题", str(caught.exception))

    def _note_with_explanation(self) -> None:
        self.store.write_explanation(
            self.note,
            "## 基础信息\n\n<table>\n</table>\n\n## 讲解\n\n**错误机制**：\n\n- 讲解\n",
        )

    def test_append_explain_section_lands_after_explanation_and_before_rounds(self) -> None:
        """讲解型菜单项进文件级讲解区：在 `## 讲解` 之后、所有日期区块之前。"""
        self._note_with_explanation()
        self.store.append(self.note, round_block())
        result = self.store.append_explain_section(
            self.note,
            "## 对比 out west 和 in the west\n\n**讲解要点**：\n- 一条要点\n  - `She went out west.`（她往西边去了。）\n",
        )
        self.assertTrue(result["appended_section"])
        text = self.note.read_text(encoding="utf-8")
        self.assertLess(text.index("## 讲解"), text.index("## 对比 out west 和 in the west"))
        self.assertLess(
            text.index("## 对比 out west 和 in the west"),
            text.index("# 2026-11-07 21:00 · 复习"),
        )

    def test_append_explain_section_reports_duplicates(self) -> None:
        """同一菜单项重复选中不再记录：第二次写入返回 duplicate，文件不变。"""
        self._note_with_explanation()
        section = "## 对比 out west 和 in the west\n\n**讲解要点**：\n- 一条要点\n"
        self.store.append_explain_section(self.note, section)
        before = self.note.read_bytes()
        result = self.store.append_explain_section(self.note, section)
        self.assertFalse(result["appended_section"])
        self.assertTrue(result["duplicate"])
        self.assertEqual(self.note.read_bytes(), before)

    def test_append_explain_part_renumbers_the_first_block(self) -> None:
        """出现第二段原文时，第一段自动从 `故事原文` 改成 `故事原文 1`。"""
        self._note_with_explanation()
        self.store.append_explain_section(
            self.note,
            "## 读一个围绕 out west 的小故事\n\n**讲解要点**：\n- 一条要点\n\n"
            "<details>\n<summary>故事原文 · 第一版</summary>\n\nFirst version.\n\n</details>\n",
        )
        result = self.store.append_explain_part(
            self.note,
            "## 读一个围绕 out west 的小故事",
            "<details>\n<summary>故事原文 2 · 第二版</summary>\n\nSecond version.\n\n</details>\n",
        )
        self.assertTrue(result["appended_part"])
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("<summary>故事原文 1 · 第一版</summary>", text)
        self.assertIn("<summary>故事原文 2 · 第二版</summary>", text)

    def test_explain_section_refuses_a_story_block_without_title(self) -> None:
        """写入路径就拦住没有标题的原文折叠块，不等到校验器才发现。"""
        self._note_with_explanation()
        with self.assertRaises(NoteError) as caught:
            self.store.append_explain_section(
                self.note,
                "## 读一个围绕 out west 的小故事\n\n**讲解要点**：\n- 一条要点\n  - 示例\n\n"
                "<details><summary>故事原文</summary>\n\nOne line.\n\n</details>\n",
            )
        self.assertIn("必须带上标题", str(caught.exception))
        self.assertFalse(
            "读一个围绕 out west 的小故事" in self.note.read_text(encoding="utf-8")
        )

    def test_explain_part_matches_a_plain_section_with_an_emoji_title(self) -> None:
        """旧笔记的小节标题没图标：同一菜单项带 emoji 的写法仍追加到那一节，不新建小节。"""
        self._note_with_explanation()
        self.store.append_explain_section(
            self.note,
            "## 读一个围绕 out west 的小故事\n\n**讲解要点**：\n- 一条要点\n\n"
            "<details>\n<summary>故事原文 · 第一版</summary>\n\nFirst version.\n\n</details>\n",
        )
        result = self.store.append_explain_part(
            self.note,
            "## 📖 读一个围绕 out west 的小故事",
            "<details>\n<summary>故事原文 2 · 第二版</summary>\n\nSecond version.\n\n</details>\n",
        )
        self.assertTrue(result["appended_part"])
        text = self.note.read_text(encoding="utf-8")
        headings = [
            line for line in text.split("\n")
            if line.startswith("## ") and "读一个围绕 out west 的小故事" in line
        ]
        self.assertEqual(len(headings), 1)
        self.assertIn("<summary>故事原文 1 · 第一版</summary>", text)
        self.assertIn("<summary>故事原文 2 · 第二版</summary>", text)

    def test_explain_section_duplicate_is_detected_across_emoji(self) -> None:
        """带不带行首 emoji 是同一个菜单项：第二次写入必须返回 duplicate。"""
        self._note_with_explanation()
        self.store.append_explain_section(
            self.note, "## 对比 out west 和 in the west\n\n**讲解要点**：\n- 一条要点\n"
        )
        before = self.note.read_bytes()
        result = self.store.append_explain_section(
            self.note, "## 🔄 对比 out west 和 in the west\n\n**讲解要点**：\n- 一条要点\n"
        )
        self.assertTrue(result["duplicate"])
        self.assertEqual(self.note.read_bytes(), before)

    def test_same_day_sections_number_across_emoji_variants(self) -> None:
        """标题只差行首图标时仍算同一个菜单项：同一天第二份照样补 ` - 02`。"""
        self.store.append(self.note, round_block("2026-11-07 09:00", body="第 1 轮"))
        self.store.append_section(
            self.note, "# 2026-11-07 09:00 · 复习", extra_section().strip("\n")
        )
        result = self.store.append_section(
            self.note,
            "# 2026-11-07 09:00 · 复习",
            extra_section("## 🧩 扩展练习").strip("\n"),
        )
        self.assertTrue(result["section"].endswith("扩展练习 - 02"))
        text = self.note.read_text(encoding="utf-8")
        # 旧份补号时沿用自己原来的标题写法，不被新份的图标改写
        self.assertIn("## 扩展练习 - 01", text)
        self.assertIn("## 🧩 扩展练习 - 02", text)

    def test_append_explain_section_rewrite_replaces_only_that_section(self) -> None:
        """`--rewrite` 用来修正首轮写错的讲解小节，其它小节与日期区块不能动。"""
        self._note_with_explanation()
        self.store.append_explain_section(
            self.note, "## 对比 A 和 B\n\n**讲解要点**：\n- 旧的一条\n"
        )
        before = self.note.read_text(encoding="utf-8")
        result = self.store.append_explain_section(
            self.note,
            "## 对比 A 和 B\n\n**讲解要点**：\n- 新的一条\n",
            rewrite=True,
        )
        self.assertTrue(result["rewritten"])
        after = self.note.read_text(encoding="utf-8")
        self.assertIn("新的一条", after)
        self.assertNotIn("旧的一条", after)
        self.assertEqual(after.count("## 对比 A 和 B"), 1)
        # 其余内容保持原样（只多了一次「笔记更新时间」的时间戳变化）
        self.assertEqual(
            [line for line in before.split("\n") if line.startswith("# ")],
            [line for line in after.split("\n") if line.startswith("# ")],
        )

    def test_rewrite_refuses_to_drop_the_story_block(self) -> None:
        """`--rewrite` 是整节替换：新内容漏掉已有原文时必须拒绝，避免静默丢内容。"""
        self._note_with_explanation()
        story_heading = "## 读一个围绕 a price to pay 的小故事"
        self.store.append_explain_section(
            self.note,
            story_heading
            + "\n\n**讲解要点**：\n- 旧的一条\n"
            "  - `There is a price to pay.`（总要付出代价。）\n\n"
            "<details>\n<summary>故事原文 · 那条小路</summary>\n\nLine one. Line two.\n\n"
            "| 故事里的位置 | 当时想表达什么 | 为什么不换别的表达 |\n"
            "|---|---|---|\n| 第 1 段 | 代价 | 固定搭配 |\n\n</details>\n\n",
        )
        with self.assertRaises(NoteError) as caught:
            self.store.append_explain_section(
                self.note,
                story_heading + "\n\n**讲解要点**：\n- 新的一条\n",
                rewrite=True,
            )
        self.assertIn("折叠块", str(caught.exception))
        self.assertIn("Line one. Line two.", self.note.read_text(encoding="utf-8"))

    def test_rewrite_refuses_to_reduce_the_story_blocks(self) -> None:
        """整节重写不能把已有的两段原文缩成一段。"""
        self._note_with_explanation()
        heading = "## 读一个围绕 a price to pay 的小故事"
        table = (
            "\n| 故事里的位置 | 当时想表达什么 | 为什么不换别的表达 |\n"
            "|---|---|---|\n| 第 1 段 | 代价 | 固定搭配 |\n\n"
        )
        self.store.append_explain_section(
            self.note,
            heading
            + "\n\n**讲解要点**：\n- 一条要点\n  - `There is a price to pay.`（总要付出代价。）\n\n"
            "<details>\n<summary>故事原文 · 第一版</summary>\n\nFirst story.\n"
            + table
            + "</details>\n",
        )
        self.store.append_explain_part(
            self.note,
            heading,
            "<details>\n<summary>故事原文 2 · 第二版</summary>\n\nSecond story.\n"
            + table
            + "</details>\n",
        )
        with self.assertRaises(NoteError) as caught:
            self.store.append_explain_section(
                self.note,
                heading
                + "\n\n**讲解要点**：\n- 一条要点\n  - `There is a price to pay.`（总要付出代价。）\n\n"
                "<details>\n<summary>故事原文 · 第一版</summary>\n\nFirst story.\n\n</details>\n"
                + table,
                rewrite=True,
            )
        self.assertIn("2 段 → 1 段", str(caught.exception))
        self.assertIn("Second story.", self.note.read_text(encoding="utf-8"))

    def test_rewrite_may_extend_explanation_when_the_block_is_kept(self) -> None:
        """讲解要点可以在后续按需补充：带上原文整节重写，原文与编号保持不变。"""
        self._note_with_explanation()
        story_heading = "## 读一个围绕 a price to pay 的小故事"
        story_source = (
            "<details>\n<summary>故事原文 · 那条小路</summary>\n\nLine one. Line two.\n\n"
            "| 故事里的位置 | 当时想表达什么 | 为什么不换别的表达 |\n"
            "|---|---|---|\n| 第 1 段 | 代价 | 固定搭配 |\n\n</details>\n\n"
        )
        self.store.append_explain_section(
            self.note,
            story_heading
            + "\n\n**讲解要点**：\n- 旧的一条\n"
            "  - `There is a price to pay.`（总要付出代价。）\n\n"
            + story_source,
        )
        result = self.store.append_explain_section(
            self.note,
            story_heading
            + "\n\n**讲解要点**：\n- 旧的一条\n"
            "  - `There is a price to pay.`（总要付出代价。）\n"
            "- 补充的一条\n  - `You pay the price for it.`（你为此付出代价。）\n\n"
            + story_source,
            rewrite=True,
        )
        self.assertTrue(result["rewritten"])
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("补充的一条", text)
        self.assertEqual(text.count(story_heading), 1)
        self.assertIn("<summary>故事原文 · 那条小路</summary>", text)

    def test_sections_lists_file_level_explanation_sections(self) -> None:
        """`sections` 要能看到文件级讲解区，调用方才能在写入前判断是否已记录过。"""
        self._note_with_explanation()
        self.store.append_explain_section(
            self.note, "## 对比 A 和 B\n\n**讲解要点**：\n- 一条\n"
        )
        whole = self.store.sections(self.note)
        self.assertEqual(whole["explain_sections"], ["## 讲解", "## 对比 A 和 B"])
        self.assertNotIn("## 基础信息", whole["explain_sections"])

    def test_append_part_refuses_a_missing_section(self) -> None:
        self.store.append(self.note, round_block())
        with self.assertRaises(NoteError):
            self.store.append_part(
                self.note,
                "# 2026-11-07 21:00 · 复习",
                "## 不存在的小节",
                "正文",
            )

    def test_first_append_creates_the_file_level_basic_info_block(self) -> None:
        result = self.store.append(self.note, round_block())
        self.assertTrue(result["appended"])
        self.assertEqual(result["blocks"], 1)
        text = self.note.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("## 基础信息\n"))
        self.assertIn("# 2026-11-07 21:00 · 复习\n", text)
        self.assertEqual(text.count("\n---\n"), 0)

    def test_second_append_adds_single_divider_between_blocks(self) -> None:
        self.store.append(self.note, round_block("2026-11-07 21:00"))
        self.store.append(self.note, round_block("2026-11-08 09:30"))
        text = self.note.read_text(encoding="utf-8")
        self.assertEqual(text.count("\n---\n"), 1)
        self.assertEqual(
            result_order(text), ["2026-11-08 09:30", "2026-11-07 21:00"]
        )

    def test_update_inserts_explanation_into_a_note_that_has_none(self) -> None:
        """历史笔记只有复习区块时，explain --update 要把 `## 讲解` 插到基础信息表之后。"""
        self.store.append(self.note, round_block("2026-11-07 21:00"))
        self.store.append(self.note, round_block("2026-11-08 09:30"))
        self.assertNotIn("## 讲解", self.note.read_text(encoding="utf-8"))

        result = self.store.write_explanation(
            self.note,
            "## 讲解\n\n**错误机制**：\n\n- 占位：本条为历史知识点补建笔记。\n",
            update=True,
        )

        self.assertTrue(result["inserted"])
        self.assertFalse(result["updated"])
        text = self.note.read_text(encoding="utf-8")
        self.assertEqual(text.count("## 讲解"), 1)
        # 讲解必须紧跟基础信息表、在所有日期区块之前
        self.assertLess(text.index("</table>"), text.index("## 讲解"))
        self.assertLess(text.index("## 讲解"), text.index("# 2026-11-07 21:00 · 复习"))
        # 两个已有区块一字不动
        self.assertEqual(
            result_order(text), ["2026-11-08 09:30", "2026-11-07 21:00"]
        )
        self.assertEqual(text.count("\n---\n"), 1)

    def test_update_still_replaces_an_existing_explanation(self) -> None:
        self.store.write_explanation(
            self.note,
            "## 基础信息\n\n<table>\n</table>\n\n## 讲解\n\n- 旧讲解\n",
        )
        result = self.store.write_explanation(
            self.note,
            "## 讲解\n\n**错误机制**：\n\n- 新讲解\n",
            update=True,
        )
        self.assertFalse(result.get("inserted", False))
        self.assertTrue(result["updated"])
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("新讲解", text)
        self.assertNotIn("旧讲解", text)

    def test_insert_explanation_stops_at_the_first_date_block(self) -> None:
        """基础信息没有表格时，讲解也不能落到某一轮区块的表格之后。"""
        self.note.parent.mkdir(parents=True, exist_ok=True)
        self.note.write_text(
            "## 基础信息\n\n# 2026-11-07 21:00 · 复习\n\n<table>\n</table>\n",
            encoding="utf-8",
        )
        result = self.store.write_explanation(
            self.note, "## 讲解\n\n**错误机制**：\n\n- 讲解\n", update=True
        )
        self.assertTrue(result["inserted"])
        text = self.note.read_text(encoding="utf-8")
        self.assertLess(text.index("## 讲解"), text.index("# 2026-11-07 21:00 · 复习"))

    def test_insert_explanation_refuses_a_foreign_record(self) -> None:
        self.store.append(self.note, round_block())
        with self.assertRaises(NoteError):
            self.store.write_explanation(
                self.note,
                "## 基础信息\n\n<table>\n<tr><td>记录 ID / 试卷 ID</td><td>errors:other</td></tr>\n"
                "</table>\n\n## 讲解\n\n**错误机制**：\n\n- 讲解\n",
                update=True,
            )

    def test_duplicate_heading_is_idempotent(self) -> None:
        self.store.append(self.note, round_block())
        before = self.note.read_bytes()
        result = self.store.append(self.note, round_block())
        self.assertFalse(result["appended"])
        self.assertTrue(result["duplicate"])
        self.assertEqual(self.note.read_bytes(), before)

    def test_duplicate_heading_with_changed_body_keeps_both_rounds(self) -> None:
        self.store.append(self.note, round_block())
        result = self.store.append(self.note, round_block(body="改过的内容"))
        self.assertTrue(result["appended"])
        self.assertTrue(result["heading_adjusted"])
        self.assertEqual(result["requested_heading"], "# 2026-11-07 21:00 · 复习")
        self.assertNotEqual(result["heading"], result["requested_heading"])
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("改过的内容", text)
        self.assertIn("第 1 轮", text)
        self.assertEqual(result["blocks"], 2)
        # 最新一轮排在最前：顺延到更晚分钟的那块在旧区块之上
        self.assertLess(
            text.index(result["heading"]),
            text.index("# 2026-11-07 21:00 · 复习"),
        )

    def test_identical_content_with_same_heading_is_a_duplicate(self) -> None:
        self.store.append(self.note, round_block())
        result = self.store.append(self.note, round_block())
        self.assertFalse(result["appended"])
        self.assertTrue(result["duplicate"])
        self.assertEqual(result["blocks"], 1)

    def test_retry_inside_a_multi_block_file_is_still_a_duplicate(self) -> None:
        # 文件里已有两个区块时，第一块后面会带 `---` 分隔符；重试同一轮不能被判成新内容
        self.store.append(self.note, round_block("2026-11-07 21:00"))
        self.store.append(self.note, round_block("2026-11-07 21:05", body="第 2 轮"))
        before = self.note.read_text(encoding="utf-8")
        result = self.store.append(self.note, round_block("2026-11-07 21:00"))
        self.assertTrue(result["duplicate"])
        self.assertFalse(result["appended"])
        self.assertEqual(self.note.read_text(encoding="utf-8"), before)

    def test_relative_and_bare_paths_resolve_to_notes_dir(self) -> None:
        result = self.store.append("errors-out-west.md", round_block())
        self.assertEqual(result["file"], "learning-record-notes/errors/errors-out-west.md")
        self.assertTrue(self.note.exists())

    def test_flat_path_is_moved_into_its_category_directory(self) -> None:
        """迁移前的平铺路径仍可用：第一次被引用时文件落进分类目录。"""
        legacy = self.repo / "learning-record-notes" / "errors-out-west.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("old\n", encoding="utf-8")
        resolved = self.store.resolve("learning-record-notes/errors-out-west.md")
        self.assertEqual(
            resolved,
            (self.repo / "learning-record-notes" / "errors" / "errors-out-west.md").resolve(),
        )
        self.assertTrue(resolved.is_file())
        self.assertFalse(legacy.exists())
        self.assertEqual(
            self.store.relative(resolved), "learning-record-notes/errors/errors-out-west.md"
        )

    def test_category_directory_must_match_the_filename_prefix(self) -> None:
        with self.assertRaises(NoteError):
            self.store.append(
                "learning-record-notes/phrases/errors-out-west.md", round_block()
            )
        with self.assertRaises(NoteError):
            self.store.append(
                "learning-record-notes/errors/phrases-out-west.md", round_block()
            )


        legacy = round_block("2026-11-04 10:00") + round_block("2026-11-05 10:00")
        self.note.parent.mkdir(parents=True, exist_ok=True)
        self.note.write_text(legacy, encoding="utf-8")
        self.store.append(self.note, round_block("2026-11-06 10:00"))
        text = self.note.read_text(encoding="utf-8")
        # 历史区块一个字都不改，整段原样留在最新一轮之后
        self.assertTrue(text.startswith("## 基础信息\n"))
        self.assertTrue(text.rstrip("\n").endswith(legacy.rstrip("\n").split("\n")[-1]))
        self.assertLess(text.index("# 2026-11-06 10:00 · 复习"), text.index("# 2026-11-04 10:00 · 复习"))
        # 写入器只把新轮次插到最前，历史区块的相对顺序原样保留（历史乱序由一次性迁移处理）
        self.assertEqual(result_order(text), ["2026-11-06 10:00", "2026-11-04 10:00", "2026-11-05 10:00"])
        self.assertEqual(text.count("\n---\n"), 1)

    def test_block_must_start_with_a_round_heading(self) -> None:
        for content in ("", "no heading here\n", "## 本轮习题\n", "\n\n"):
            with self.assertRaises(NoteError):
                _normalize_block(content)

    def test_append_rejects_two_rounds_in_one_block(self) -> None:
        with self.assertRaises(NoteError):
            _normalize_block(round_block() + "\n" + round_block("2026-11-08 10:00"))

    def test_path_must_stay_inside_notes_dir(self) -> None:
        outside = self.repo / "learning-record-notes" / "nested" / "x.md"
        with self.assertRaises(NoteError):
            self.store.append(str(outside), round_block())
        with self.assertRaises(NoteError):
            self.store.append("../escape.md", round_block())

    def test_file_name_must_match_slug_convention(self) -> None:
        for name in (
            "Errors-Out.md",
            "errors out.md",
            "errors.md.bak",
            "notes.txt",
            "errors-后遗漏介词-for.md",
        ):
            with self.assertRaises(NoteError):
                self.store.append(name, round_block())

    def test_symlink_target_is_rejected(self) -> None:
        self.repo.joinpath("learning-record-notes").mkdir(parents=True)
        target = self.repo / "victim.md"
        target.write_text("# 2026-11-07 21:00 · 复习\n", encoding="utf-8")
        link = self.repo / "learning-record-notes" / "errors-victim.md"
        os.symlink(target, link)
        with self.assertRaises(NoteError):
            self.store.append(str(link), round_block())

    def test_lock_file_exists_after_first_write(self) -> None:
        self.store.append(self.note, round_block())
        self.assertTrue((self.repo / "learning-record-notes" / ".notes.lock").exists())

    def test_append_bumps_the_file_level_updated_at(self) -> None:
        self.store.append(self.note, round_block("2026-11-07 21:00"))
        self.assertNotEqual(updated_at_value(self.note), "2026-11-07 21:05")

    def test_replace_block_bumps_the_file_level_updated_at(self) -> None:
        self.store.append(self.note, round_block("2026-11-07 21:00"))
        self.store.replace_block(
            self.note,
            "# 2026-11-07 21:00 · 复习",
            round_block("2026-11-07 21:00", body="修正后"),
        )
        self.assertNotEqual(updated_at_value(self.note), "2026-11-07 21:05")

    def test_updated_at_never_precedes_the_newest_round(self) -> None:
        self.store.append(self.note, round_block("2030-01-01 08:00"))
        self.assertEqual(updated_at_value(self.note), "2030-01-01 08:00")

    def test_sync_basic_info_updates_only_the_record_rows(self) -> None:
        """记录级两行（累计复习次数 / 下次复习）由记录同步，其余内容原样保留。"""
        self.store.append(self.note, round_block("2026-11-07 21:00", body="第 1 轮"))
        before = self.note.read_text(encoding="utf-8")
        result = self.store.sync_basic_info(
            self.note, {"累计复习次数": "5", "下次复习": "2026-12-01 09:00"}
        )
        self.assertEqual(result["synced"], ["累计复习次数", "下次复习"])
        after = self.note.read_text(encoding="utf-8")
        self.assertIn("<tr><td>累计复习次数</td><td>5</td></tr>", after)
        self.assertIn("<tr><td>下次复习</td><td>2026-12-01 09:00</td></tr>", after)
        self.assertIn("<tr><td>笔记生成时间</td><td>2026-11-07 21:05</td></tr>", after)
        self.assertIn("第 1 轮", after)
        self.assertEqual(after.count("\n---\n"), before.count("\n---\n"))
        self.assertNotEqual(updated_at_value(self.note), "2026-11-07 21:05")

    def test_sync_basic_info_is_a_noop_when_rows_already_match(self) -> None:
        self.store.append(self.note, round_block("2026-11-07 21:00"))
        stamp_after_append = updated_at_value(self.note)
        result = self.store.sync_basic_info(
            self.note, {"累计复习次数": "2", "下次复习": "2026-11-23 09:00"}
        )
        self.assertEqual(result["synced"], [])
        self.assertEqual(updated_at_value(self.note), stamp_after_append)

    def test_sync_basic_info_ignores_rows_inside_a_round_block(self) -> None:
        """轮次区块里的同名行不属于记录级字段，同步时一个字都不能动。"""
        self.store.append(self.note, round_block("2026-11-07 21:00", body="累计复习次数</td><td>9"))
        result = self.store.sync_basic_info(self.note, {"累计复习次数": "4"})
        self.assertEqual(result["synced"], ["累计复习次数"])
        text = self.note.read_text(encoding="utf-8")
        self.assertEqual(text.count("<tr><td>累计复习次数</td>"), 1)
        self.assertIn("<tr><td>累计复习次数</td><td>4</td></tr>", text)

    def test_sync_basic_info_requires_an_existing_note(self) -> None:
        with self.assertRaises(NoteError):
            self.store.sync_basic_info(
                self.repo / "learning-record-notes" / "errors" / "errors-out-west.md",
                {"累计复习次数": "1"},
            )

    def test_replace_block_keeps_other_rounds_intact(self) -> None:
        self.store.append(self.note, round_block("2026-11-07 21:00", body="第 1 轮"))
        self.store.append(self.note, round_block("2026-11-08 09:30", body="第 2 轮"))
        self.store.append(self.note, round_block("2026-11-09 09:30", body="第 3 轮"))
        result = self.store.replace_block(
            self.note, "# 2026-11-08 09:30 · 复习", round_block("2026-11-08 09:30", body="修正后")
        )
        self.assertTrue(result["replaced"])
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("修正后", text)
        self.assertNotIn("第 2 轮", text)
        self.assertIn("第 1 轮", text)
        self.assertIn("第 3 轮", text)
        self.assertEqual(
            result_order(text),
            ["2026-11-09 09:30", "2026-11-08 09:30", "2026-11-07 21:00"],
        )

    def test_replace_block_rejects_unknown_or_changed_heading(self) -> None:
        self.store.append(self.note, round_block())
        with self.assertRaises(NoteError):
            self.store.replace_block(self.note, "# 2026-11-10 10:00 · 复习", round_block())
        with self.assertRaises(NoteError):
            self.store.replace_block(
                self.note, "# 2026-11-07 21:00 · 复习", round_block("2026-11-07 22:00")
            )

    def test_replace_block_refuses_ambiguous_heading(self) -> None:
        self.store.append(self.note, round_block())
        self.note.write_text(
            self.note.read_text(encoding="utf-8") + "\n" + round_block(), encoding="utf-8"
        )
        with self.assertRaises(NoteError):
            self.store.replace_block(
                self.note, "# 2026-11-07 21:00 · 复习", round_block()
            )

    def test_check_reports_validator_issues(self) -> None:
        self.store.append(self.note, round_block())
        self.store.append(self.note, "# 2026-11-08 09:00 · 复习\n")
        report = self.store.check(self.note)
        self.assertFalse(report["ok"])
        self.assertTrue(report["issues"])

    def test_concurrent_appends_all_survive(self) -> None:
        total = 16
        contents = []
        for index in range(total):
            path = self.repo / f"block-{index}.md"
            # 每轮内容是独立的，避免把不同轮次误判成同一次重试
            path.write_text(
                round_block(f"2026-11-07 21:{index:02d}", body=f"第 {index} 轮"),
                encoding="utf-8",
            )
            contents.append(path)
        environment = dict(os.environ, LEARN_ENGLISH_REPO_ROOT=str(self.repo))
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "append",
                    "--file",
                    "learning-record-notes/errors/errors-out-west.md",
                    "--content-file",
                    str(path),
                ],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for path in contents
        ]
        failures = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=90)
            if process.returncode != 0:
                failures.append(stderr.strip() or stdout.strip())
        self.assertEqual(failures, [])
        text = self.note.read_text(encoding="utf-8")
        stamps = result_order(text)
        self.assertEqual(len(stamps), total)
        self.assertEqual(len(set(stamps)), total)
        self.assertEqual(text.count("\n---\n"), total - 1)
        self.assertFalse(text.startswith("\n"))
        for part in text.split("\n---\n"):
            # 第一段前面还有文件级「基础信息」折叠块
            self.assertRegex(part.lstrip("\n"), r"^(## 基础信息|# 2026-11-07)")
            self.assertIn("# 2026-11-07", part)


NOTE_HEAD = """## 基础信息

<table style="border-collapse:collapse;width:auto">
<colgroup><col width="150"><col></colgroup>
<tr><td>记录 ID / 试卷 ID</td><td>errors:out-west</td></tr>
<tr><td>目标知识点</td><td>out west 不是 outwest</td></tr>
<tr><td>累计复习次数</td><td>2</td></tr>
<tr><td>下次复习</td><td>2026-11-23 09:00</td></tr>
<tr><td>笔记生成时间</td><td>2026-11-09 09:05</td></tr>
<tr><td>笔记更新时间</td><td>2026-11-09 09:05</td></tr>
</table>

"""

VALID_BLOCK = """# {heading}

## 本轮习题

<table style="border-collapse:collapse;width:auto">
<colgroup><col width="150"><col></colgroup>
<tr><td>生成时间</td><td>{stamp}</td></tr>
<tr><td>分类 · 状态变化</td><td>errors · learning → familiar</td></tr>
<tr><td>本轮得分</td><td>10 / 10</td></tr>
<tr><td>题量与错题数</td><td>1 题 / 0 处错误</td></tr>
</table>

### 1. 填空

**题目**：He drove out ___.

**我的答案**：{answer}

**判定**：✅ 正确

<details>
<summary>知识点讲解</summary>

1. **本题知识点**：out west 是固定搭配
2. **规则与机制**：方位副词连用，不合并成一个词
3. **英语的表达逻辑**：英语用两个独立方位词表示方向
4. **可迁移表达**：They headed out east.
</details>
"""


def block_text(heading: str, answer: str) -> str:
    """带文件级基础信息头的完整区块；重复追加时写入命令会忽略多出来的头。"""
    return NOTE_HEAD + VALID_BLOCK.format(heading=heading, stamp=heading.split(" · ")[0], answer=answer)


EXPLAIN_BLOCK = (
    "## 讲解\n\n"
    "**错误机制**：\n\n- 方位短语分写\n"
    "  - `She headed out west.`（她往西边出发了。）\n\n"
    "**使用场景**：\n\n- 招呼客人自取食物\n"
)


def block_text_with_explanation(heading: str, answer: str) -> str:
    """在基础信息头之后再带一份合规的 `## 讲解`，用于后续 append-section 补文件级骨架小节。"""
    return (
        NOTE_HEAD
        + EXPLAIN_BLOCK
        + VALID_BLOCK.format(heading=heading, stamp=heading.split(" · ")[0], answer=answer)
    )


class NoteWriteEntireTest(unittest.TestCase):
    """整篇写入：校验通过才落盘，不过就回滚。"""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)
        self.store = NoteStore(self.repo)
        self.note = self.repo / "learning-record-notes" / "errors" / "errors-out-west.md"
        self.note.parent.mkdir(parents=True, exist_ok=True)
        self.note.write_text(
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"), encoding="utf-8"
        )
        self.baseline = self.note.read_text(encoding="utf-8")

    def test_accepts_a_valid_full_note(self) -> None:
        result = self.store.write_entire(
            "learning-record-notes/errors/errors-out-west.md", self.baseline
        )

        self.assertTrue(result["written"])
        self.assertTrue(result["check"]["ok"])
        self.assertEqual(result["note_status"], "valid")
        # 写入会重建习题 / 复习索引块，其余正文原样落地
        self.assertEqual(
            self.note.read_text(encoding="utf-8"),
            apply_practice_index(self.baseline),
        )

    def test_rolls_back_when_the_validator_rejects_the_text(self) -> None:
        broken = self.baseline.replace("</details>", "")

        result = self.store.write_entire(
            "learning-record-notes/errors/errors-out-west.md", broken
        )

        self.assertFalse(result["ok"])
        self.assertFalse(result["written"])
        self.assertFalse(result["check"]["ok"])
        self.assertEqual(result["note_status"], "invalid")
        self.assertTrue(result["check"]["issues"])
        # 被拒的版本不留在仓库里
        self.assertEqual(self.note.read_text(encoding="utf-8"), self.baseline)

    def test_rejection_of_a_new_file_leaves_no_file_behind(self) -> None:
        target = "learning-record-notes/grammar/grammar-present-perfect.md"

        result = self.store.write_entire(target, "## 讲解\n\n没有基础信息表\n")

        self.assertFalse(result["written"])
        self.assertFalse((self.repo / target).exists())


class NoteCliTest(unittest.TestCase):
    """命令级用例：校验退出码、stdin 输入、块级替换。"""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)
        self.note = self.repo / "learning-record-notes" / "errors" / "errors-out-west.md"

    def run_cli(self, args: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
        environment = dict(os.environ, LEARN_ENGLISH_REPO_ROOT=str(self.repo))
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=stdin_text,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )

    def test_cli_accepts_stdin_and_passes_check(self) -> None:
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
                "--check",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(self.note.exists())
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["appended"])
        self.assertTrue(payload["check"]["ok"])

    def test_cli_write_rejects_an_invalid_note_with_exit_code_1(self) -> None:
        """`write` 只在整篇校验通过时落盘；被拒时进程退出码为 1，文件保持原样。"""
        self.note.parent.mkdir(parents=True, exist_ok=True)
        self.note.write_text(
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"), encoding="utf-8"
        )
        baseline = self.note.read_text(encoding="utf-8")

        completed = self.run_cli(
            [
                "write",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            baseline.replace("</details>", ""),
        )

        self.assertEqual(completed.returncode, 1, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["written"])
        self.assertFalse(payload["check"]["ok"])
        self.assertEqual(self.note.read_text(encoding="utf-8"), baseline)

    def test_cli_write_publishes_a_valid_note(self) -> None:
        self.note.parent.mkdir(parents=True, exist_ok=True)
        self.note.write_text(
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"), encoding="utf-8"
        )

        completed = self.run_cli(
            [
                "write",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            self.note.read_text(encoding="utf-8"),
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["written"])
        self.assertEqual(payload["note_status"], "valid")

    def test_cli_append_section_stamps_the_generated_time(self) -> None:
        """新小节落盘时由写入器盖章 `生成时间`：调用方没写也一定有这一行。"""
        self.run_cli(
            ["append", "--file", "learning-record-notes/errors/errors-out-west.md", "--content-file", "-"],
            block_text_with_explanation(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        section = extra_section("## 扩展练习", "第一题的题干").strip("\n") + "\n"
        added = self.run_cli(
            [
                "append-section",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--content-file",
                "-",
                "--check",
            ],
            section,
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        payload = json.loads(added.stdout)
        self.assertTrue(payload["check"]["ok"], payload["check"]["issues"])
        text = self.note.read_text(encoding="utf-8")
        stamp_row = [
            line
            for line in text.split("\n")
            if line.startswith("<tr><td>生成时间</td><td>")
        ]
        self.assertTrue(stamp_row)
        self.assertIn("## 扩展练习", text)

    def test_cli_append_part_adds_a_second_exercise_and_still_validates(self) -> None:
        """append-part 只在既有小节里补写题目：小节数不变，笔记仍然通过校验。"""
        self.run_cli(
            ["append", "--file", "learning-record-notes/errors/errors-out-west.md", "--content-file", "-"],
            block_text_with_explanation(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        section = extra_section("## 扩展练习", "第一题的题干").strip("\n") + "\n"
        added = self.run_cli(
            [
                "append-section",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--content-file",
                "-",
            ],
            section,
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        part = (
            "### 2. 翻译\n\n"
            "**题目**：中译英：他往西开了。\n\n"
            "**我的答案**：He drove out west.\n\n"
            "**判定**：✅ 正确\n\n"
            "<details>\n<summary>知识点讲解</summary>\n\n"
            "1. **本题知识点**：out west 是方位短语\n"
            "2. **规则与机制**：out 与 west 分写\n"
            "3. **英语的表达逻辑**：副词短语表方向\n"
            "4. **可迁移表达**：drive out west\n\n"
            "</details>\n"
        )
        completed = self.run_cli(
            [
                "append-part",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--section",
                "## 扩展练习",
                "--content-file",
                "-",
                "--check",
            ],
            part,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["appended_part"])
        self.assertTrue(payload["check"]["ok"])
        text = self.note.read_text(encoding="utf-8")
        # 一处讲解区骨架小节 + 一处日期区块习题小节
        self.assertEqual(text.count("## 扩展练习"), 2)
        self.assertIn("### 2. 翻译", text)

    def test_cli_append_part_rejects_a_new_section_heading(self) -> None:
        self.run_cli(
            ["append", "--file", "learning-record-notes/errors/errors-out-west.md", "--content-file", "-"],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        completed = self.run_cli(
            [
                "append-part",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--section",
                "## 某小节",
                "--content-file",
                "-",
            ],
            "## 另一个小节\n\n正文\n",
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("append-section", completed.stderr)

    def test_cli_auto_fixes_safe_issues_before_reporting(self) -> None:
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
                "--check",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="1. west"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["note_status"], "valid")
        self.assertIn("去掉 `我的答案` 的题号前缀", payload["auto_fixed"][0]["fixes"])
        self.assertNotIn("1. west", self.note.read_text(encoding="utf-8"))

    def test_cli_check_failure_sets_nonzero_exit_code(self) -> None:
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
                "--check",
            ],
            NOTE_HEAD + "# 2026-11-09 09:00 · 复习\n",
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["appended"])
        self.assertEqual(payload["note_status"], "invalid")
        self.assertFalse(payload["check_ok"])
        self.assertFalse(payload["check"]["ok"])
        self.assertTrue(payload["check"]["issues"])

    def test_cli_reports_valid_note_status(self) -> None:
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
                "--check",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["note_status"], "valid")
        self.assertTrue(payload["check_ok"])

    def test_new_file_for_a_record_that_already_has_one_is_refused(self) -> None:
        self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        refused = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west-again.md",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-10 09:00 · 复习", answer="west"),
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("already has a note at learning-record-notes/errors/errors-out-west.md", refused.stderr)
        self.assertFalse((self.repo / "learning-record-notes" / "errors" / "errors-out-west-again.md").exists())

    def test_cli_replace_block_rewrites_only_that_round(self) -> None:
        for heading in ("2026-11-09 09:00 · 复习", "2026-11-10 09:00 · 复习"):
            completed = self.run_cli(
                [
                    "append",
                    "--file",
                    "learning-record-notes/errors/errors-out-west.md",
                    "--content-file",
                    "-",
                ],
                block_text(heading=heading, answer="west"),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
        completed = self.run_cli(
            [
                "replace",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="westward"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("westward", text)
        self.assertIn("2026-11-10 09:00", text)
        self.assertEqual(result_order(text), ["2026-11-10 09:00", "2026-11-09 09:00"])

    def test_cli_replace_keeps_sections_the_new_content_omits(self) -> None:
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west")
            + extra_section(),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        replaced = self.run_cli(
            [
                "replace",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="westward"),
        )
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        payload = json.loads(replaced.stdout)
        self.assertEqual(payload["preserved_sections"], ["## 扩展练习"])
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("westward", text)
        self.assertIn("## 扩展练习", text)
        self.assertIn("别的会话追加的小节", text)

    def test_cli_replace_drops_a_section_only_when_explicitly_allowed(self) -> None:
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west")
            + extra_section(marker="写错的小节"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        replaced = self.run_cli(
            [
                "replace",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--drop-section",
                "## 扩展练习",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="westward"),
        )
        self.assertEqual(replaced.returncode, 0, replaced.stderr)
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("westward", text)
        self.assertNotIn("## 扩展练习", text)

    def test_cli_append_section_keeps_the_rest_of_the_block(self) -> None:
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        before = self.note.read_text(encoding="utf-8")
        appended = self.run_cli(
            [
                "append-section",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--content-file",
                "-",
            ],
            extra_section("## 对比「out west」和相近表达", "别的会话刚写的小节").strip("\n") + "\n",
        )
        self.assertEqual(appended.returncode, 0, appended.stderr)
        payload = json.loads(appended.stdout)
        self.assertTrue(payload["appended_section"])
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("## 对比「out west」和相近表达", text)
        self.assertIn(before.strip(), text.strip())
        again = self.run_cli(
            [
                "append-section",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--content-file",
                "-",
            ],
            extra_section("## 对比「out west」和相近表达", "别的会话刚写的小节").strip("\n") + "\n",
        )
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertTrue(json.loads(again.stdout)["duplicate"])

    def test_cli_append_section_numbers_a_repeated_heading_in_one_block(self) -> None:
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west")
            + extra_section("## 对比「out west」和相近表达", "旧内容"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        again = self.run_cli(
            [
                "append-section",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--content-file",
                "-",
            ],
            extra_section("## 对比「out west」和相近表达", "新内容").strip("\n") + "\n",
        )
        self.assertEqual(again.returncode, 0, again.stderr)
        payload = json.loads(again.stdout)
        self.assertTrue(payload["appended_section"])
        self.assertEqual(payload["section"], "## 对比「out west」和相近表达 - 02")
        self.assertEqual(
            [item["to"] for item in payload["section_renamed"]],
            [
                "## 对比「out west」和相近表达 - 01",
                "## 对比「out west」和相近表达 - 02",
            ],
        )
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("旧内容", text)
        self.assertIn("新内容", text)
        self.assertIn("## 对比「out west」和相近表达 - 01 <a id=", text)

    def test_cli_replace_rewriting_two_sections_needs_declaration(self) -> None:
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west")
            + extra_section("## 小节甲", "旧甲")
            + extra_section("## 小节乙", "旧乙"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        replacement = (
            block_text(heading="2026-11-09 09:00 · 复习", answer="west")
            + extra_section("## 小节甲", "新甲")
            + extra_section("## 小节乙", "新乙")
        )
        refused = self.run_cli(
            [
                "replace",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--content-file",
                "-",
            ],
            replacement,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("一次只改一个小节", refused.stderr)
        self.assertIn("旧甲", self.note.read_text(encoding="utf-8"))

        allowed = self.run_cli(
            [
                "replace",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--rewrite-section",
                "## 小节甲",
                "--rewrite-section",
                "## 小节乙",
                "--content-file",
                "-",
            ],
            replacement,
        )
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        payload = json.loads(allowed.stdout)
        self.assertEqual(
            payload["modified_sections"], ["## 小节甲", "## 小节乙"]
        )
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("新甲", text)
        self.assertIn("新乙", text)


    def test_cli_append_syncs_stale_record_rows(self) -> None:
        """写入后顶部两行自动回填成规范记录的值，不再只报 tracking_mismatch。"""
        self.run_cli(
            ["append", "--file", "learning-record-notes/errors/errors-out-west.md", "--content-file", "-"],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        install_stub_record_store(
            self.repo,
            {
                "记录 ID / 试卷 ID": "errors:out-west",
                "目标知识点": "out west 不是 outwest",
                "累计复习次数": "3",
                "下次复习": "2026-12-01 09:00",
            },
        )
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
                "--check",
            ],
            block_text(heading="2026-11-10 09:00 · 复习", answer="out"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["basic_info_synced"], ["累计复习次数", "下次复习"])
        self.assertNotIn("tracking_mismatch", payload)
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("<tr><td>累计复习次数</td><td>3</td></tr>", text)
        self.assertIn("<tr><td>下次复习</td><td>2026-12-01 09:00</td></tr>", text)

    def test_cli_still_reports_a_row_the_record_does_not_own(self) -> None:
        """身份行（记录 ID / 目标知识点）不由同步覆盖，不一致照样报出来。"""
        self.run_cli(
            ["append", "--file", "learning-record-notes/errors/errors-out-west.md", "--content-file", "-"],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        install_stub_record_store(
            self.repo,
            {
                "记录 ID / 试卷 ID": "errors:out-west",
                "目标知识点": "out west 应写成两个词",
                "累计复习次数": "1",
                "下次复习": "2026-11-23 09:00",
            },
        )
        completed = self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
                "--check",
            ],
            block_text(heading="2026-11-10 09:00 · 复习", answer="out"),
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["basic_info_synced"], ["累计复习次数"])
        fields = [item["field"] for item in payload["tracking_mismatch"]]
        self.assertEqual(fields, ["目标知识点"])

    def test_cli_sync_repairs_a_stale_header(self) -> None:
        """已有笔记可用 sync 子命令就地修复顶部的记录级两行。"""
        self.run_cli(
            ["append", "--file", "learning-record-notes/errors/errors-out-west.md", "--content-file", "-"],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        install_stub_record_store(
            self.repo,
            {
                "记录 ID / 试卷 ID": "errors:out-west",
                "目标知识点": "out west 不是 outwest",
                "累计复习次数": "4",
                "下次复习": "2026-12-02 10:00",
            },
        )
        completed = self.run_cli(
            [
                "sync",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--check",
            ]
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["synced"], ["累计复习次数", "下次复习"])
        self.assertEqual(payload["note_status"], "valid")
        self.assertNotIn("tracking_mismatch", payload)
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("<tr><td>累计复习次数</td><td>4</td></tr>", text)
        self.assertIn("<tr><td>下次复习</td><td>2026-12-02 10:00</td></tr>", text)

    def test_cli_sync_skips_when_the_record_store_is_missing(self) -> None:
        self.run_cli(
            ["append", "--file", "learning-record-notes/errors/errors-out-west.md", "--content-file", "-"],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        completed = self.run_cli(
            ["sync", "--file", "learning-record-notes/errors/errors-out-west.md"]
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertIn("tracking_skipped", payload)

    def test_tracking_rows_are_checked_against_the_record(self) -> None:
        """追踪行与规范记录比对：记录事实由 learn-from-english 的 record-tracking 提供。"""
        import note  # noqa: PLC0415

        expected = {
            "记录 ID / 试卷 ID": "errors:out-west",
            "分类 · 状态变化": "errors · learning → familiar",
            "本轮得分": "10 / 10",
            "目标知识点": "out west 不是 outwest",
            "累计复习次数": "2",
            "下次复习": "2026-11-23 09:00",
            "笔记生成时间": "2026-11-09 09:05",
            "笔记更新时间": "2026-11-09 09:05",
        }
        self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        original = note.record_tracking
        note.record_tracking = lambda identifier: expected
        try:
            result = note.verify_tracking(
                NoteStore(self.repo),
                "learning-record-notes/errors/errors-out-west.md",
                "# 2026-11-09 09:00 · 复习",
            )
        finally:
            note.record_tracking = original
        self.assertEqual(result, {})

    def test_menu_section_score_does_not_override_the_round_score(self) -> None:
        """同一区块里追加的菜单小节各带自己的 `本轮得分`，不得覆盖轮次得分参与比对。"""
        import note  # noqa: PLC0415

        expected = {
            "记录 ID / 试卷 ID": "errors:out-west",
            "分类 · 状态变化": "errors · learning → familiar",
            "本轮得分": "10 / 10",
            "目标知识点": "out west 不是 outwest",
            "累计复习次数": "2",
            "下次复习": "2026-11-23 09:00",
            "笔记生成时间": "2026-11-09 09:05",
            "笔记更新时间": "2026-11-09 09:05",
        }
        self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        with self.note.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n## 练习「out west」的关键语法结构\n\n"
                '<table style="border-collapse:collapse;width:auto">\n'
                "<tr><td>生成时间</td><td>2026-11-09 09:07</td></tr>\n"
                "<tr><td>本轮得分</td><td>6 / 10</td></tr>\n"
                "<tr><td>题量与错题数</td><td>1 题 / 0 处错误</td></tr>\n"
                "</table>\n"
            )
        original = note.record_tracking
        note.record_tracking = lambda identifier: expected
        try:
            result = note.verify_tracking(
                NoteStore(self.repo),
                "learning-record-notes/errors/errors-out-west.md",
                "# 2026-11-09 09:00 · 复习",
            )
        finally:
            note.record_tracking = original
        self.assertEqual(result, {})


    def test_tracking_requires_absent_status_row_when_nothing_changed(self) -> None:
        """记录侧说状态没变（空值）时，笔记里多写这一行同样算不一致，少写则合规。"""
        import note  # noqa: PLC0415

        expected = {
            "记录 ID / 试卷 ID": "errors:out-west",
            "分类 · 状态变化": "",
            "本轮得分": "10 / 10",
            "目标知识点": "out west 不是 outwest",
            "累计复习次数": "2",
            "下次复习": "2026-11-23 09:00",
            "笔记生成时间": "2026-11-09 09:05",
            "笔记更新时间": "2026-11-09 09:05",
        }
        self.run_cli(
            [
                "append",
                "--file",
                "learning-record-notes/errors/errors-out-west.md",
                "--content-file",
                "-",
            ],
            block_text(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        text = self.note.read_text(encoding="utf-8").replace(
            "<tr><td>分类 · 状态变化</td><td>errors · learning → familiar</td></tr>\n", "", 1
        )
        self.note.write_text(text, encoding="utf-8")
        original = note.record_tracking
        note.record_tracking = lambda identifier: expected
        try:
            clean = note.verify_tracking(
                NoteStore(self.repo),
                "learning-record-notes/errors/errors-out-west.md",
                "# 2026-11-09 09:00 · 复习",
            )
            self.assertEqual(clean, {})
            text = self.note.read_text(encoding="utf-8").replace(
                "<tr><td>本轮得分</td>",
                "<tr><td>分类 · 状态变化</td><td>errors · familiar → familiar</td></tr>\n"
                "<tr><td>本轮得分</td>",
                1,
            )
            self.note.write_text(text, encoding="utf-8")
            dirty = note.verify_tracking(
                NoteStore(self.repo),
                "learning-record-notes/errors/errors-out-west.md",
                "# 2026-11-09 09:00 · 复习",
            )
        finally:
            note.record_tracking = original
        fields = [item["field"] for item in dirty.get("tracking_mismatch", [])]
        self.assertIn("分类 · 状态变化", fields)

def install_stub_record_store(repo: Path, tracking: dict) -> None:
    """Write a minimal learn-from-english CLI so the tracking compare runs offline."""
    script = repo / "skills" / "learn-from-english" / "scripts" / "learning_records.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(tracking, ensure_ascii=False)
    script.write_text(
        "import json\n"
        f"TRACKING = json.loads({repr(payload)})\n"
        "print(json.dumps({'tracking': TRACKING}, ensure_ascii=False))\n",
        encoding="utf-8",
    )


def result_order(text: str) -> list[str]:
    return [
        line[2:].split(" · ")[0]
        for line in text.split("\n")
        if line.startswith("# 2026-")
    ]


def updated_at_value(path: Path) -> str:
    """Read the file-level `笔记更新时间` row that every note write must refresh."""
    match = re.search(r"<tr><td>笔记更新时间</td><td>(.*?)</td></tr>", path.read_text(encoding="utf-8"))
    assert match, "note has no 笔记更新时间 row"
    return match.group(1)




if __name__ == "__main__":
    unittest.main()
