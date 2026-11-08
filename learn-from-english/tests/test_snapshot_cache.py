from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from learning_records_tool import cache  # noqa: E402
from learning_records_tool.menu import annotate_writes  # noqa: E402
from learning_records_tool.notes import NoteStore  # noqa: E402


NOTE_TEXT = (
    "## 基础信息\n\n"
    '<table style="border-collapse:collapse;width:auto">\n'
    '<colgroup><col width="150"><col></colgroup>\n'
    "<tr><td>记录 ID / 试卷 ID</td><td>usage:after-不宜直接当-later-连接后续动作</td></tr>\n"
    "</table>\n\n"
    "# 2026-11-08 15:54 · 复习\n\n"
    "## 本轮习题\n\n1. 例句\n\n"
    "## 扩展「after」相关词汇和搭配\n\n1. 要点\n"
)


def make_repo(root: Path) -> Path:
    notes = root / cache.NOTES_DIR_NAME
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "usage-after.md").write_text(NOTE_TEXT, encoding="utf-8")
    (notes / "README.md").write_text("index\n", encoding="utf-8")
    return root


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_index_maps_chinese_record_id_and_sections(self) -> None:
        snapshot = cache.build_snapshot(self.root)
        entry = snapshot["notes"][f"{cache.NOTES_DIR_NAME}/usage-after.md"]
        self.assertEqual(
            entry["record_id"], "usage:after-不宜直接当-later-连接后续动作"
        )
        self.assertEqual(
            snapshot["record_files"]["usage:after-不宜直接当-later-连接后续动作"],
            f"{cache.NOTES_DIR_NAME}/usage-after.md",
        )
        self.assertEqual([block["heading"] for block in entry["blocks"]], ["# 2026-11-08 15:54 · 复习"])
        self.assertEqual(
            entry["blocks"][0]["sections"],
            ["## 本轮习题", "## 扩展「after」相关词汇和搭配"],
        )
        self.assertEqual(snapshot["counts"], {"files": 1, "blocks": 1})

    def test_cache_is_reused_then_rebuilt_by_age_or_refresh(self) -> None:
        first = cache.get_snapshot(self.root)
        self.assertEqual(first["source"], "rebuild")
        second = cache.get_snapshot(self.root)
        self.assertEqual(second["source"], "cache")
        forced = cache.get_snapshot(self.root, max_age=0)
        self.assertEqual(forced["source"], "rebuild")
        refreshed = cache.get_snapshot(self.root, refresh=True)
        self.assertEqual(refreshed["source"], "rebuild")

    def test_entry_is_distrusted_once_the_file_changes(self) -> None:
        snapshot = cache.get_snapshot(self.root)
        note = self.root / cache.NOTES_DIR_NAME / "usage-after.md"
        note.write_text(NOTE_TEXT + "\n# 2026-11-08 20:20 · 复习\n", encoding="utf-8")
        self.assertIsNone(
            cache.note_entry_current(self.root, snapshot, f"{cache.NOTES_DIR_NAME}/usage-after.md")
        )

    def test_invalidate_drops_the_file(self) -> None:
        cache.get_snapshot(self.root)
        self.assertTrue(cache.cache_path(self.root).is_file())
        cache.invalidate(self.root)
        self.assertFalse(cache.cache_path(self.root).exists())

    def test_note_write_refreshes_the_snapshot(self) -> None:
        cache.get_snapshot(self.root)
        store = NoteStore(self.root)
        block = "# 2026-11-08 20:20 · 练习\n\n## 本轮习题\n\n1. 新题\n"
        store.append(f"{cache.NOTES_DIR_NAME}/usage-after.md", block)
        entry = cache.load_snapshot(self.root)["notes"][
            f"{cache.NOTES_DIR_NAME}/usage-after.md"
        ]
        self.assertEqual(
            [item["heading"] for item in entry["blocks"]],
            ["# 2026-11-08 15:54 · 复习", "# 2026-11-08 20:20 · 练习"],
        )
        self.assertTrue(cache.note_entry_current(self.root, cache.load_snapshot(self.root), entry["file"]))

    def test_list_notes_reads_the_index_without_reparsing(self) -> None:
        store = NoteStore(self.root)
        cache.get_snapshot(self.root)
        entries = store.list_notes("usage:after-不宜直接当-later-连接后续动作")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["heading"], "# 2026-11-08 15:54 · 复习")


class WritesFlagTests(unittest.TestCase):
    def test_read_only_kinds_are_marked(self) -> None:
        options = annotate_writes(
            [
                {"id": "scenario-dialogue", "kind": "scenario-dialogue"},
                {"id": "status", "kind": "status"},
                {
                    "id": "review",
                    "kind": "review-path",
                    "children": [{"id": "review:usage", "kind": "review-path"}],
                },
                {"id": "no-kind"},
            ]
        )
        self.assertFalse(options[0]["writes"])
        self.assertFalse(options[1]["writes"])
        self.assertTrue(options[2]["writes"])
        self.assertTrue(options[2]["children"][0]["writes"])
        self.assertNotIn("writes", options[3])


if __name__ == "__main__":
    unittest.main()
