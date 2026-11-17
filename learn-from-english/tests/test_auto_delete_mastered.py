"""已掌握记录连续三次 10 分自动删除记录与笔记。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from learning_records_tool.models import empty_database  # noqa: E402
from learning_records_tool.round_flow import finish_round  # noqa: E402
from learning_records_tool.service import RecordService  # noqa: E402
from learning_records_tool.store import RecordStore  # noqa: E402


def payload(category: str, key: str) -> dict[str, object]:
    return {
        "category": category,
        "key": key,
        "title": f"{category} {key}",
        "explanation": f"Explanation for {key}",
        "source": f"Source for {key}",
        "example": f"Example for {key}",
        "tags": ["core"],
    }


class MasteredAutoDeleteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.store = RecordStore(self.root)
        self.store.initialize(empty_database())
        self.records = RecordService(self.store)

    def mark_mastered(self, identifier: str) -> None:
        """累计第 3 次 10 分进入 mastered（与既有掌握口径一致）。"""
        category, key = identifier.split(":", 1)
        self.records.upsert(payload(category, key))
        for _ in range(3):
            self.records.complete_review(identifier, 10)
        self.assertEqual(self.records.records()[identifier]["status"], "mastered")

    def write_note(self, category: str, key: str) -> Path:
        path = self.root / "learning-record-notes" / category / f"{category}-{key}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("## 基础信息\n\n## 讲解\n", encoding="utf-8")
        return path

    def test_three_consecutive_tens_delete_the_record_but_keep_the_note(self) -> None:
        self.mark_mastered("usage:polite-request")
        note = self.write_note("usage", "polite-request")

        first = self.records.complete_review("usage:polite-request", 10)
        second = self.records.complete_review("usage:polite-request", 10)
        third = self.records.complete_review("usage:polite-request", 10)

        self.assertFalse(first["deleted"])
        self.assertFalse(second["deleted"])
        self.assertEqual(first["mastered_ten_streak"], 1)
        self.assertEqual(second["mastered_ten_streak"], 2)
        self.assertTrue(third["deleted"])
        self.assertEqual(
            third["deleted_record"],
            {
                "id": "usage:polite-request",
                "category": "usage",
                "key": "polite-request",
                "title": "usage polite-request",
                "ten_streak": 3,
                "file": "mastered-learning-records/usage.json",
            },
        )
        # 只删记录：笔记 md 原样保留，之后仍可按路径练习这个知识点
        self.assertTrue(note.exists())
        self.assertNotIn("note", third)
        self.assertNotIn("note_error", third)
        self.assertNotIn("usage:polite-request", self.records.records())
        self.assertEqual(self.records.summary()["totals"]["mastered"], 0)

    def test_a_lower_score_resets_the_streak(self) -> None:
        self.mark_mastered("usage:polite-request")

        self.records.complete_review("usage:polite-request", 10)
        self.records.complete_review("usage:polite-request", 10)
        reset = self.records.complete_review("usage:polite-request", 9)
        self.assertEqual(reset["mastered_ten_streak"], 0)
        self.assertEqual(reset["status"], "familiar")
        # 掉出 mastered 后计数不再携带，重新掌握要重新连击
        self.assertNotIn("mastered_ten_streak", self.records.records()["usage:polite-request"])

        self.records.complete_review("usage:polite-request", 10)
        self.records.complete_review("usage:polite-request", 10)
        self.assertIn("usage:polite-request", self.records.records())

    def test_the_streak_survives_the_slim_rewrite(self) -> None:
        self.mark_mastered("usage:polite-request")
        self.records.complete_review("usage:polite-request", 10)
        # 另一次写入会把 mastered 文件整份重写成精简形态，计数必须还在
        self.records.upsert(payload("grammar", "another-point"))

        self.assertEqual(
            self.records.records()["usage:polite-request"]["mastered_ten_streak"], 1
        )
        self.records.complete_review("usage:polite-request", 10)
        final = self.records.complete_review("usage:polite-request", 10)
        self.assertTrue(final["deleted"])

    def test_the_entry_score_is_not_counted_as_the_first_streak(self) -> None:
        self.mark_mastered("usage:polite-request")

        result = self.records.complete_review("usage:polite-request", 10)
        self.assertEqual(result["mastered_ten_streak"], 1)
        self.assertFalse(result["deleted"])

    def test_the_note_is_left_untouched_whether_it_exists_or_not(self) -> None:
        """删记录不看笔记：没有笔记就什么都不动，有笔记也不动它。"""
        self.mark_mastered("usage:polite-request")

        existing = self.write_note("usage", "polite-request")
        before = existing.read_text(encoding="utf-8")
        for _ in range(3):
            result = self.records.complete_review("usage:polite-request", 10)

        self.assertTrue(result["deleted"])
        self.assertEqual(existing.read_text(encoding="utf-8"), before)
        self.assertNotIn("note", result)

    def test_a_learning_record_is_never_auto_deleted(self) -> None:
        self.records.upsert(payload("usage", "fresh"))
        first = self.records.complete_review("usage:fresh", 10)
        self.assertEqual(first["status"], "familiar")
        self.assertEqual(first["mastered_ten_streak"], 0)
        self.assertFalse(first["deleted"])

    def test_review_round_keeps_the_note_file_when_the_record_was_deleted(self) -> None:
        self.mark_mastered("usage:polite-request")
        note = self.write_note("usage", "polite-request")
        self.records.complete_review("usage:polite-request", 10)
        self.records.complete_review("usage:polite-request", 10)

        result = finish_round(
            {
                "review": {"id": "usage:polite-request", "score": 10},
                "note": {
                    "file": "learning-record-notes/usage/usage-polite-request.md",
                    "date": "2026-11-17",
                    "time": "21:30",
                    "kind": "复习",
                    "body": "## 本轮习题\n\n<table></table>",
                    "explain": {"content": "## 讲解\n\n内容"},
                },
            },
            self.records,
            self.root,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["review"]["deleted"])
        self.assertEqual(result["note_skipped"]["reason"], "record-auto-deleted")
        self.assertNotIn("note", result)
        # 笔记 md 保留在原处：记录没了，这篇仍可按路径当练习素材用
        self.assertTrue(note.exists())


if __name__ == "__main__":
    unittest.main()
