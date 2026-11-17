from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from learning_records_tool.models import RecordError, empty_database  # noqa: E402
from learning_records_tool.notes import NoteDeletionService  # noqa: E402
from learning_records_tool.service import RecordService  # noqa: E402
from learning_records_tool.store import RecordStore  # noqa: E402


SCRIPT = SCRIPT_DIR / "learning_records.py"


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


def note_text(record_id: str) -> str:
    return "\n".join(
        [
            "## 基础信息",
            "",
            '<table style="border-collapse:collapse;width:auto">',
            '<colgroup><col width="150"><col></colgroup>',
            f"<tr><td>记录 ID / 试卷 ID</td><td>{record_id}</td></tr>",
            "<tr><td>目标知识点</td><td>demo</td></tr>",
            "</table>",
            "",
            "## 讲解",
            "",
        ]
    )


class NoteDeletionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.store = RecordStore(self.root)
        self.store.initialize(empty_database())
        self.records = RecordService(self.store)
        self.deletions = NoteDeletionService(self.root, self.records)

    def write_note(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_delete_record_removes_it_and_bumps_the_revision(self) -> None:
        self.records.upsert(payload("errors", "first"))
        self.records.upsert(payload("errors", "second"))
        before = json.loads(self.store.category_path("errors").read_text(encoding="utf-8"))

        deleted = self.records.delete_record("errors:first")

        self.assertEqual(deleted["status"], "learning")
        self.assertEqual(deleted["category"], "errors")
        self.assertNotIn("errors:first", self.records.records())
        self.assertIn("errors:second", self.records.records())
        after = json.loads(self.store.category_path("errors").read_text(encoding="utf-8"))
        self.assertEqual(after["revision"], before["revision"] + 1)

    def test_delete_record_can_report_a_missing_record_without_error(self) -> None:
        with self.assertRaises(RecordError):
            self.records.delete_record("errors:missing")
        self.assertIsNone(self.records.delete_record("errors:missing", missing_ok=True))

    def test_delete_note_removes_the_note_and_its_record(self) -> None:
        self.records.upsert(payload("errors", "demo"))
        note = self.write_note("learning-record-notes/errors/errors-demo.md", note_text("errors:demo"))

        result = self.deletions.delete("learning-record-notes/errors/errors-demo.md")

        self.assertFalse(note.exists())
        self.assertEqual(result["note"], "learning-record-notes/errors/errors-demo.md")
        self.assertEqual(result["record_id"], "errors:demo")
        self.assertIsNone(result["record_error"])
        self.assertEqual(result["record"]["file"], "learning-records/errors.json")
        self.assertFalse(result["record"]["mastered"])
        self.assertNotIn("errors:demo", self.records.records())

    def test_delete_note_points_a_mastered_record_at_the_mastered_file(self) -> None:
        self.records.upsert(payload("grammar", "demo"))
        for _ in range(3):
            self.records.complete_review("grammar:demo", 10)
        self.write_note("learning-record-notes/grammar/grammar-demo.md", note_text("grammar:demo"))

        result = self.deletions.delete("learning-record-notes/grammar/grammar-demo.md")

        self.assertEqual(result["record"]["file"], "mastered-learning-records/grammar.json")
        self.assertTrue(result["record"]["mastered"])
        self.assertNotIn("grammar:demo", self.records.records())

    def test_delete_note_keeps_the_record_when_the_id_does_not_match_the_file(self) -> None:
        self.records.upsert(payload("errors", "other"))
        note = self.write_note("learning-record-notes/errors/errors-demo.md", note_text("errors:other"))

        result = self.deletions.delete("learning-record-notes/errors/errors-demo.md")

        self.assertFalse(note.exists())
        self.assertIsNone(result["record"])
        self.assertIn("记录 ID 与笔记文件不一致", result["record_error"])
        # 错 ID 不能顺着删掉别人的知识点
        self.assertIn("errors:other", self.records.records())

    def test_delete_note_without_a_record_id_only_removes_the_note(self) -> None:
        note = self.write_note(
            "learning-record-notes/usage/usage-demo.md",
            "## 讲解\n\nno basic table here\n",
        )

        result = self.deletions.delete("learning-record-notes/usage/usage-demo.md")

        self.assertFalse(note.exists())
        self.assertEqual(result["record_id"], "")
        self.assertIsNone(result["record"])

    def test_delete_note_skips_paper_ids(self) -> None:
        note = self.write_note(
            "learning-record-notes/paper/paper-demo.md", note_text("paper-2026-01-01-abc")
        )

        result = self.deletions.delete("learning-record-notes/paper/paper-demo.md")

        self.assertFalse(note.exists())
        self.assertIsNone(result["record"])
        self.assertIsNone(result["record_error"])
        self.assertEqual(result["record_id"], "paper-2026-01-01-abc")

    def test_delete_note_rejects_paths_outside_the_notes_directory(self) -> None:
        self.write_note("README.md", "not a note\n")

        with self.assertRaises(RecordError):
            self.deletions.delete("README.md")
        with self.assertRaises(RecordError):
            self.deletions.delete("learning-record-notes/../README.md")
        with self.assertRaises(RecordError):
            self.deletions.delete("learning-record-notes/errors/other-demo.md")

    def test_delete_note_leaves_the_record_alone_when_the_file_cannot_be_removed(
        self,
    ) -> None:
        self.records.upsert(payload("errors", "demo"))
        self.write_note(
            "learning-record-notes/errors/errors-demo.md", note_text("errors:demo")
        )

        with mock.patch.object(Path, "unlink", side_effect=OSError("read-only")):
            with self.assertRaises(RecordError) as caught:
                self.deletions.delete("learning-record-notes/errors/errors-demo.md")

        self.assertIn("cannot delete note file", str(caught.exception))
        # md 没删掉，记录也不能先被删掉
        self.assertIn("errors:demo", self.records.records())

    def test_delete_note_rejects_a_missing_note(self) -> None:
        with self.assertRaises(RecordError):
            self.deletions.delete("learning-record-notes/errors/errors-missing.md")


class DeleteCliTest(unittest.TestCase):
    """CLI surface: my-dashboard 靠 stdout 的 JSON 与退出码判断结果。"""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        store = RecordStore(self.root)
        store.initialize(empty_database())
        RecordService(store).upsert(payload("errors", "cli"))
        self.note = self.root / "learning-record-notes/errors/errors-cli.md"
        self.note.parent.mkdir(parents=True)
        self.note.write_text(note_text("errors:cli"), encoding="utf-8")

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = {**os.environ, "LEARN_ENGLISH_REPO_ROOT": str(self.root)}
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )

    def test_delete_note_prints_json_and_removes_both(self) -> None:
        completed = self.run_cli(
            "delete-note", "--note", "learning-record-notes/errors/errors-cli.md"
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["note_deleted"])
        self.assertEqual(result["record"]["file"], "learning-records/errors.json")
        self.assertFalse(self.note.exists())
        self.assertNotIn(
            "errors:cli",
            RecordService(RecordStore(self.root)).records(),
        )

    def test_delete_note_fails_loudly_on_an_unknown_note(self) -> None:
        completed = self.run_cli(
            "delete-note", "--note", "learning-record-notes/errors/errors-gone.md"
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("note does not exist", completed.stderr)

    def test_delete_record_prints_the_file_it_changed(self) -> None:
        completed = self.run_cli("delete-record", "--id", "errors:cli")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertTrue(result["deleted"])
        self.assertEqual(result["file"], "learning-records/errors.json")


if __name__ == "__main__":
    unittest.main()
