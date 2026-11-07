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
    rows = {
        "记录 ID / 试卷 ID": record_id,
        "分类 · 状态变化": "errors · learning → familiar",
        "本轮得分": score,
        "题量与错题数": counts,
        "目标知识点": "out west 不是 outwest",
        "累计复习次数": "2",
        "下次复习": "2026-11-20 12:00",
        "主观题得分": "—",
        "笔记生成时间": "2026-11-07 12:05",
    }
    table = "\n".join(
        f"<tr><td>{row}</td><td>{rows[row]}</td></tr>"
        for row in check_note.TRACKING_ROWS
    )
    return (
        f"# {stamp} · 复习\n"
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
