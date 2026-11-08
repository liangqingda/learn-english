"""内容层校验：这些写法以前能静默通过，现在必须被 check_note 拦下。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "practice-learning-records" / "scripts"))

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
        "\n## 本轮信息\n\n"
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        f"{table}\n"
        "</table>\n\n"
        "## 本轮习题\n\n"
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
        "\n## 本轮信息\n\n"
        '<table style="border-collapse:collapse;width:auto">\n'
        '<colgroup><col width="150"><col></colgroup>\n'
        f"{table}\n"
        "</table>\n\n"
        "## 本轮习题\n\n"
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


class NoteContentValidationTest(unittest.TestCase):
    def check(self, text: str, name: str = "errors-out-west.md") -> list[dict]:
        with tempfile.TemporaryDirectory() as directory:
            notes = Path(directory) / NOTES_DIR
            notes.mkdir()
            path = notes / name
            path.write_text(text, encoding="utf-8")
            return check_note.check(path)

    def assert_caught(self, text: str, keyword: str, name: str = "errors-out-west.md") -> None:
        issues = self.check(text, name)
        self.assertTrue(issues, "该写法应当被拦下，但校验通过")
        self.assertTrue(
            any(keyword in issue["message"] for issue in issues),
            [issue["message"] for issue in issues],
        )

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

    def test_descending_sections_are_rejected(self) -> None:
        older = note_text(stamp="2026-11-01 09:00").replace("12:05", "09:20")
        text = note_text() + "\n---\n\n" + older
        self.assert_caught(text, "按时间从早到晚排列")

    def test_same_minute_with_another_kind_is_not_misread_as_descending(self) -> None:
        practice = note_text(stamp="2026-11-07 12:00").replace("· 复习", "· 练习")
        text = note_text() + "\n---\n\n" + practice
        issues = self.check(text)
        self.assertFalse(any("从早到晚排列" in item["message"] for item in issues))

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
        second = note_text(stamp="2026-11-08 12:00")
        # 第二个区块不再带文件级基础信息头
        second = second[second.index("# 2026-11-08 12:00") :].replace(
            "# 2026-11-08 12:00 · 复习", "# 2026-11-08 12:00 · 练习"
        )
        joined = first.rstrip("\n") + "\n" + second
        fixed, fixes = check_note.apply_safe_fixes(joined)
        self.assertIn("补上区块之间缺失的 `---` 分隔", fixes)
        self.assertEqual(self.check(fixed), [])

    def test_all_mode_walks_the_default_notes_directory(self) -> None:
        import io
        import os
        from contextlib import redirect_stdout
        from unittest import mock

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / NOTES_DIR
            notes.mkdir()
            (notes / "errors-out-west.md").write_text(note_text(), encoding="utf-8")
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



class NoteEntryPointTest(unittest.TestCase):
    """`note.py` 是复习 skill 自己的入口：校验不依赖另一个 skill，写入才转发。"""

    WRAPPER = REPO_ROOT / "practice-learning-records" / "scripts" / "note.py"

    def run_wrapper(self, args: list[str], root: Path, cli: str | None = None):
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
            check=False,
        )

    def test_check_runs_its_own_validator_without_the_other_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notes = root / NOTES_DIR
            notes.mkdir()
            (notes / "errors-out-west.md").write_text(note_text(), encoding="utf-8")
            completed = self.run_wrapper(["check", "--all"], root, cli=str(root / "missing.py"))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(__import__("json").loads(completed.stdout)["ok"])

    def test_write_reports_a_missing_business_cli_instead_of_silently_failing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = self.run_wrapper(
                ["append", "--file", "learning-record-notes/errors-out-west.md", "--content-file", "-"],
                root,
                cli=str(root / "missing.py"),
            )
            self.assertEqual(completed.returncode, 2)
            payload = __import__("json").loads(completed.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("learning_records.py not found", payload["error"])


class RealNotesTest(unittest.TestCase):
    """仓库里真实笔记必须持续通过校验，模板改版时这里会先响。"""

    def test_every_note_in_the_repository_is_valid(self) -> None:
        notes = sorted((REPO_ROOT / NOTES_DIR).glob("*.md"))
        notes = [path for path in notes if path.name.lower() != "readme.md"]
        self.assertTrue(notes, "仓库里应当至少有一份笔记")
        for path in notes:
            with self.subTest(note=path.name):
                self.assertEqual(check_note.check(path), [])


if __name__ == "__main__":
    unittest.main()
