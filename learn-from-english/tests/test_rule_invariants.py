"""Cross-cutting invariants: menu rules, doc/CLI drift, note template, transactions."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "learn-from-english" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(REPO_ROOT / "practice-learning-records" / "scripts"))

import check_note  # noqa: E402

from learning_records_tool.cli import build_parser  # noqa: E402
from learning_records_tool.menu import build_menu  # noqa: E402
from learning_records_tool.models import empty_database, normalize_key  # noqa: E402
from learning_records_tool.service import RecordService  # noqa: E402
from learning_records_tool.store import RecordStore  # noqa: E402


def payload(category: str, key: str, title: str | None = None) -> dict[str, object]:
    return {
        "category": category,
        "key": key,
        "title": title or f"{category} {key}",
        "explanation": f"Explanation for {key}",
        "source": f"Source for {key}",
        "example": f"Example for {key}",
        "tags": ["core"],
    }


class MenuInvariantTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = RecordStore(Path(self.temporary_directory.name))
        self.store.initialize(empty_database())
        self.service = RecordService(self.store)
        for category in ("vocabulary", "phrases", "grammar", "usage", "errors"):
            self.service.upsert(payload(category, f"{category}-item"))

    def context_menu(self, context: str) -> dict[str, object]:
        return build_menu(
            self.service.records(),
            context,
            focus="help yourself",
        )

    def test_every_context_has_scenario_and_three_other_options(self) -> None:
        for context in ("initial", "review-complete", "learn"):
            menu = self.context_menu(context)
            options = menu["options"]
            self.assertEqual(menu["state"], "ready")
            self.assertIn("scenario-dialogue", {option["kind"] for option in options})
            self.assertGreaterEqual(
                sum(1 for option in options if option["group"] == "other"),
                3,
                f"{context} must offer at least three other options",
            )
            self.assertGreaterEqual(
                sum(1 for option in options if option["group"] == "popular"),
                1,
                f"{context} must offer at least one popular option",
            )
            for option in options:
                self.assertIn(option["group"], {"popular", "other"})
                self.assertIn("kind", option)
                self.assertTrue(option["label"].strip())

    def test_sibling_icons_are_distinct(self) -> None:
        for context in ("initial", "review-complete", "learn"):
            options = self.context_menu(context)["options"]
            for group in ("popular", "other"):
                icons = [option["icon"] for option in options if option["group"] == group]
                self.assertEqual(
                    len(icons),
                    len(set(icons)),
                    f"{context}/{group} has duplicate sibling icons: {icons}",
                )

    def test_learn_menu_puts_grammar_first_and_drops_it_when_explained(self) -> None:
        menu = build_menu(self.service.records(), "learn", focus="help yourself")
        first_other = next(
            option for option in menu["options"] if option["group"] == "other"
        )
        self.assertEqual(first_other["icon"], "🧩")

        explained = build_menu(
            self.service.records(),
            "learn",
            focus="help yourself",
            grammar_explained=True,
        )
        icons = [option["icon"] for option in explained["options"]]
        self.assertNotIn("🧩", icons)


class NoteTemplateTest(unittest.TestCase):
    def test_validator_reads_the_same_template(self) -> None:
        self.assertEqual(check_note.TEMPLATE["tracking_rows"], check_note.TRACKING_ROWS)
        self.assertEqual(
            check_note.TEMPLATE["error_labels"], check_note.DEFAULT_DETAIL_LABELS
        )
        self.assertEqual(
            check_note.TEMPLATE["knowledge_labels"], check_note.DEFAULT_KNOWLEDGE_LABELS
        )
        self.assertEqual(
            check_note.TEMPLATE["unanswered_labels"], check_note.DEFAULT_UNANSWERED_LABELS
        )
        self.assertEqual(
            check_note.TEMPLATE["summaries"],
            (check_note.DEFAULT_SUMMARY, check_note.DEFAULT_ERROR_SUMMARY),
        )
        self.assertEqual(check_note.TEMPLATE["col_width"], 150)

    def note_text(self) -> str:
        values = {
            "记录 ID / 试卷 ID": "errors:out-west",
            "分类 · 状态变化": "errors · learning → familiar",
            "本轮得分": "9 / 10",
            "题量与错题数": "1 题 / 1 处错误",
            "目标知识点": "out west 不是 outwest",
            "累计复习次数": "2",
            "下次复习": "2026-11-20 12:00",
            "笔记生成时间": "2026-11-07 12:05",
            "笔记更新时间": "2026-11-07 12:05",
        }
        rows = "\n".join(
            f"<tr><td>{row}</td><td>{values.get(row, 'x')}</td></tr>"
            for row in check_note.TEMPLATE["tracking_rows"]
        )
        return (
            "# 2026-11-07 12:00 · 复习\n"
            f"## {check_note.BASE_SECTION}\n\n<details>\n<summary>{check_note.TRACKING_SUMMARY}</summary>\n\n"
            f"{check_note.DEFAULT_TABLE_TAG}\n"
            '<colgroup><col width="150"><col></colgroup>\n'
            f"{rows}\n"
            "</table>\n</details>\n\n"
            "## 本轮习题\n\n"
            "### 1. 单项选择\n\n"
            "**题目**：Pick one.\n\n"
            "**我的答案**：B\n\n"
            "**判定**：❌ 错误\n\n"
            "<details>\n"
            f"<summary>{check_note.DEFAULT_SUMMARY}</summary>\n\n"
            "1. **本题知识点**：x\n"
            "2. **规则与机制**：x\n"
            "3. **英语的表达逻辑**：x\n"
            "4. **可迁移表达**：x\n\n"
            "</details>\n\n"
            "<details>\n"
            f"<summary>{check_note.DEFAULT_ERROR_SUMMARY}</summary>\n\n"
            "1. **考点**：x\n"
            "2. **为什么错**：x\n"
            "3. **英语的表达逻辑**：x\n"
            "4. **正确表达**：x\n\n"
            "</details>\n"
        )

    def test_valid_note_passes_and_drift_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.md"
            path.write_text(self.note_text(), encoding="utf-8")
            self.assertEqual(check_note.check(path), [])

            path.write_text(
                self.note_text().replace(
                    f"<summary>{check_note.DEFAULT_ERROR_SUMMARY}</summary>",
                    "<summary>展开错题讲解</summary>",
                ),
                encoding="utf-8",
            )
            issues = check_note.check(path)
            self.assertTrue(any("summary" in issue["message"] for issue in issues))

            path.write_text(
                self.note_text().replace(
                    f"<summary>{check_note.DEFAULT_SUMMARY}</summary>",
                    "<summary>展开讲解</summary>",
                ),
                encoding="utf-8",
            )
            issues = check_note.check(path)
            self.assertTrue(any("知识点讲解" in issue["message"] for issue in issues))


class MenuItemNoteTest(unittest.TestCase):
    """菜单项直接以三级标题追加在习题之后；错位与旧写法都必须被拦住。"""

    def check_text(self, text: str) -> list[dict]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.md"
            path.write_text(text, encoding="utf-8")
            return check_note.check(path)

    def base_note(self) -> str:
        return NoteTemplateTest().note_text()

    def item(self, label: str = "看一套围绕「a price to pay」的完整场景对话") -> str:
        return (
            f"## {label}\n\n"
            "**讲解要点**：\n\n"
            "- x\n\n"
            "**可迁移表达**：\n\n"
            "- y\n"
        )

    def practice(self, label: str = "练习「a price to pay」的关键语法结构") -> str:
        """菜单项下的练习与主习题共用同一套题目模板，题号在小节内从 1 重新开始。"""
        return (
            f"## {label}\n\n"
            "**讲解要点**：\n\n"
            "- x\n\n"
            "**可迁移表达**：\n\n"
            "- y\n\n"
            "### 1. 填空\n\n"
            "**题目**：Fill in the blank.\n\n"
            "**我的答案**：a price\n\n"
            "**判定**：✅ 正确\n\n"
            "<details>\n"
            f"<summary>{check_note.DEFAULT_SUMMARY}</summary>\n\n"
            "1. **本题知识点**：x\n"
            "2. **规则与机制**：x\n"
            "3. **英语的表达逻辑**：x\n"
            "4. **可迁移表达**：x\n\n"
            "</details>\n\n"
            "### 2. 翻译\n\n"
            "**题目**：Translate this.\n\n"
            "**我的答案**：no idea\n\n"
            "**判定**：❌ 错误\n\n"
            "<details>\n"
            f"<summary>{check_note.DEFAULT_SUMMARY}</summary>\n\n"
            "1. **本题知识点**：x\n"
            "2. **规则与机制**：x\n"
            "3. **英语的表达逻辑**：x\n"
            "4. **可迁移表达**：x\n\n"
            "</details>\n\n"
            "<details>\n"
            f"<summary>{check_note.DEFAULT_ERROR_SUMMARY}</summary>\n\n"
            "1. **考点**：x\n"
            "2. **为什么错**：x\n"
            "3. **英语的表达逻辑**：x\n"
            "4. **正确表达**：x\n\n"
            "</details>\n"
        )

    def test_paragraph_menu_item_is_rejected(self) -> None:
        text = (
            self.base_note()
            + "\n## 看一套围绕「a price to pay」的完整场景对话\n\n"
            "**讲解要点**：第一条规则；第二条规则；第三条规则全部揉在一段。\n\n"
            "**可迁移表达**：y\n"
        )
        issues = self.check_text(text)
        self.assertTrue(any("有序列表、无序列表或表格" in issue["message"] for issue in issues))

    def test_mixed_filename_prefix_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            notes = Path(directory) / "learning-record-notes"
            notes.mkdir()
            path = notes / "misc-a-price-to-pay.md"
            path.write_text(self.base_note(), encoding="utf-8")
            issues = check_note.check(path)
            self.assertTrue(any("自造前缀" in issue["message"] for issue in issues))

            path = notes / "mixed-a-price-to-pay.md"
            path.write_text(self.base_note(), encoding="utf-8")
            self.assertEqual(check_note.check(path), [])

            path = notes / "phrases-a-price-to-pay.md"
            path.write_text(
                self.base_note().replace("errors:out-west", "phrases:a-price-to-pay"),
                encoding="utf-8",
            )
            self.assertEqual(check_note.check(path), [])

    def test_menu_item_after_questions_passes(self) -> None:
        self.assertEqual(self.check_text(self.base_note() + "\n" + self.item()), [])

    def test_wrapper_heading_is_rejected(self) -> None:
        text = self.base_note() + "\n## 菜单与讲解\n\n" + self.item()
        issues = self.check_text(text)
        self.assertTrue(any("非模板二级标题" in issue["message"] for issue in issues))

    def test_legacy_prefix_is_rejected(self) -> None:
        text = self.base_note() + "\n" + self.item("1. 菜单：看一套围绕「a price to pay」的完整场景对话")
        issues = self.check_text(text)
        self.assertTrue(any("不要加编号" in issue["message"] for issue in issues))

    def test_menu_item_before_questions_is_rejected(self) -> None:
        text = self.base_note().replace("## 本轮习题\n\n", "## 本轮习题\n\n" + self.item() + "\n", 1)
        issues = self.check_text(text)
        self.assertTrue(any("没有任何 `### <n>. <题型>` 题目" in issue["message"] for issue in issues))

    def test_practice_questions_under_menu_pass(self) -> None:
        text = self.base_note() + "\n" + self.practice()
        self.assertEqual(self.check_text(text), [])

    def test_third_level_menu_heading_is_rejected(self) -> None:
        text = self.base_note() + "\n### 看一套围绕「a price to pay」的完整场景对话\n\n**讲解要点**：\n\n- x\n\n**可迁移表达**：\n\n- y\n"
        issues = self.check_text(text)
        self.assertTrue(any("菜单项标题必须与 `## 本轮习题` 同级" in issue["message"] for issue in issues))

    def test_emoji_label_is_rejected(self) -> None:
        text = self.base_note() + "\n" + self.item("🎭 看一套围绕「a price to pay」的完整场景对话")
        issues = self.check_text(text)
        self.assertTrue(any("去掉 emoji" in issue["message"] for issue in issues))

    def test_missing_menu_fields_are_rejected(self) -> None:
        text = self.base_note() + "\n## 看一套围绕「a price to pay」的完整场景对话\n\n**讲解要点**：x\n"
        issues = self.check_text(text)
        self.assertTrue(any("每条菜单必须依次包含" in issue["message"] for issue in issues))


class DocumentationDriftTest(unittest.TestCase):
    def test_documented_commands_exist(self) -> None:
        parser = build_parser()
        commands = set(parser._subparsers._group_actions[0].choices.keys())
        docs = [
            REPO_ROOT / "AGENTS.md",
            REPO_ROOT / "learn-from-english" / "SKILL.md",
            REPO_ROOT / "practice-learning-records" / "SKILL.md",
        ]
        for doc in docs:
            text = doc.read_text(encoding="utf-8")
            referenced = set(re.findall(r"learning_records\.py ([a-z][a-z-]+)", text))
            referenced |= set(re.findall(r"learning_records\.py\s*\\?\s*\n?\s*([a-z][a-z-]+)", text))
            missing = {command for command in referenced if command != "scripts"}
            self.assertFalse(
                missing - commands,
                f"{doc.name} references unknown CLI commands: {sorted(missing - commands)}",
            )

    def test_learn_skill_uses_the_script_menu(self) -> None:
        text = (REPO_ROOT / "learn-from-english" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("--context learn", text)


class ServiceInvariantTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = RecordStore(Path(self.temporary_directory.name))
        self.store.initialize(empty_database())
        self.service = RecordService(self.store)

    def test_key_is_persisted_and_repair_backfills_legacy_records(self) -> None:
        self.service.upsert(payload("grammar", "present-perfect"))
        database = json.loads(
            self.store.category_path("grammar").read_text(encoding="utf-8")
        )
        record = database["records"]["grammar:present-perfect"]
        self.assertEqual(record["key"], normalize_key("present-perfect"))

        record.pop("key")
        self.store.category_path("grammar").write_text(
            json.dumps(database, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        dry = self.service.repair(dry_run=True)
        self.assertTrue(
            any(change["field"] == "key" for change in dry["changes"]),
            dry,
        )
        self.service.repair(dry_run=False)
        repaired = self.service.records()["grammar:present-perfect"]
        self.assertEqual(repaired["key"], "present-perfect")

    def test_error_clusters_report_unclustered_and_tag_families(self) -> None:
        distinct = [
            ("article before countable noun", "单数可数名词前需要限定词，这是英语计量的基本规则。", "article"),
            ("verb tense backshift", "间接引语中的时态需要向过去推移一层，与主句时态呼应。", "tense"),
            ("preposition choice", "介词搭配取决于惯用法，不能按中文语序直译。", "preposition"),
        ]
        for index, (title, explanation, tag) in enumerate(distinct):
            self.service.upsert(
                {
                    "category": "errors",
                    "key": f"error-{index}",
                    "title": title,
                    "explanation": explanation,
                    "source": f"Totally different sentence number {index}.",
                    "example": "",
                    "tags": [tag],
                }
            )
        result = self.service.error_pattern_clusters(minimum_size=2)
        self.assertEqual(result["unclustered_count"], len(result["unclustered"]))
        self.assertEqual(result["unclustered_count"], 3)
        self.assertTrue(any(item["tag"] == "article" for item in result["tag_families"]))

    def test_duplicate_candidates_are_reported(self) -> None:
        from learning_records_tool.models import new_record

        self.service.upsert(payload("phrases", "look-after", "look after someone"))

        def add_twin(database: dict[str, object]) -> dict[str, object]:
            record = new_record(
                {
                    "category": "phrases",
                    "key": "look-after-carefully",
                    "title": "look after someone carefully",
                    "explanation": "look after someone carefully 表示细心照顾某人。",
                    "source": "She looks after her sister carefully.",
                    "example": "",
                    "tags": ["care"],
                }
            )
            database["records"][record["id"]] = record
            return {"added": record["id"]}

        self.store.transaction(add_twin)
        result = self.service.duplicate_candidates(threshold=0.6)
        self.assertGreaterEqual(result["candidate_count"], 1)
        pair = result["pairs"][0]
        self.assertIn("merge", result["merge_hint"])
        self.assertNotEqual(pair["left"]["id"], pair["right"]["id"])

    def test_interrupted_transaction_is_rolled_back_on_next_run(self) -> None:
        self.service.upsert(payload("grammar", "journal-target"))
        target = self.store.category_path("grammar")
        original = target.read_bytes()

        self.store.txn_dir.mkdir(parents=True, exist_ok=True)
        backup = self.store.txn_dir / "backup-0.json"
        backup.write_bytes(original)
        journal = {
            "revision": 1,
            "entries": [{"target": str(target), "backup": str(backup), "mode": 0o644}],
        }
        self.store.txn_journal_path.write_text(
            json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        target.write_text('{"schema_version": 2, "records": {}, "broken', encoding="utf-8")

        self.service.upsert(payload("phrases", "after-recovery"))

        self.assertEqual(target.read_bytes(), original)
        self.assertFalse(self.store.txn_journal_path.exists())
        self.assertFalse(self.store.txn_dir.exists())
        self.assertTrue(self.store.txn_recovery_log_path.exists())

    def test_new_write_never_clobbers_a_pending_journal(self) -> None:
        self.service.upsert(payload("phrases", "journal-guard"))
        database = self.store._load()
        target = self.store.category_path("phrases")
        backup = self.store.txn_dir / "backup-0.json"
        self.store.txn_dir.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(target.read_bytes())
        journal = {
            "revision": 9,
            "entries": [{"target": str(target), "backup": str(backup), "mode": 0o644}],
        }
        self.store.txn_journal_path.write_text(
            json.dumps(journal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        target.unlink()

        # A write path that does not pre-recover (e.g. papers.py) must still
        # recover the stale journal instead of overwriting it with new backups.
        self.store._write(database, force_all=True)

        self.assertTrue(target.exists())
        self.assertFalse(self.store.txn_journal_path.exists())
        self.assertIn(
            "revision 9",
            self.store.txn_recovery_log_path.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
