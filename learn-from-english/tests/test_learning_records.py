from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from learning_records_tool.models import RecordError, empty_database  # noqa: E402
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
        "tags": ["core", "review"],
    }


class LearningRecordsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.store = RecordStore(self.root)
        self.store.initialize(empty_database())
        self.service = RecordService(self.store)

    def test_batch_upsert_is_atomic_and_tracks_repeated_encounters(self) -> None:
        result = self.service.batch_upsert(
            [payload("grammar", "present-perfect"), payload("phrases", "wait-for")]
        )
        self.assertEqual(result["count"], 2)
        self.assertTrue(all(item["created"] for item in result["results"]))

        repeated = self.service.upsert(payload("grammar", "present perfect"))

        self.assertFalse(repeated["created"])
        self.assertTrue(repeated["encountered"])
        self.assertEqual(repeated["learned_count"], 2)
        self.assertEqual(len(self.service.records()), 2)

    def test_batch_upsert_reuses_similar_existing_records(self) -> None:
        original = payload("errors", "back-east-direction")
        original["title"] = "back east 不能表示西行方向"
        original["explanation"] = "back east 通常指美国东部，不适合修饰从东部去西部的行程。"
        original["source"] = "She travels to Los Angeles back east every summer."
        original["example"] = "She travels west to Los Angeles every summer."
        self.service.upsert(original)
        similar = payload("errors", "back-east-geographic-direction")
        similar["title"] = "back east 的地域方向误用"
        similar["explanation"] = "back east 通常指美国东部，不能描述去美国西部的行程。"
        similar["source"] = original["source"]
        similar["example"] = original["example"]

        repeated = self.service.upsert(similar)

        self.assertFalse(repeated["created"])
        self.assertEqual(repeated["id"], "errors:back-east-direction")
        self.assertEqual(repeated["match_reason"], "same-source-example")
        self.assertEqual(len(self.service.records()), 1)
        self.assertEqual(self.service.records()["errors:back-east-direction"]["learned_count"], 2)

    def test_merge_records_combines_counts_and_deletes_sources(self) -> None:
        first = payload("errors", "first-error")
        first["title"] = "will 后接动词原形"
        first["explanation"] = "情态动词 will 后面接动词原形，不能接第三人称单数形式。"
        first["source"] = "That will makes work difficult."
        first["example"] = "That will make work difficult."
        second = payload("errors", "second-error")
        second["title"] = "before 后接动名词"
        second["explanation"] = "介词 before 后面接动作时，常使用动名词形式。"
        second["source"] = "Before begin the test, read the instructions."
        second["example"] = "Before beginning the test, read the instructions."
        self.service.upsert(first)
        self.service.upsert(second)
        self.service.complete_review("errors:first-error", 7)
        self.service.complete_review("errors:second-error", 6)

        result = self.service.merge_records(
            "errors:first-error",
            ["errors:second-error"],
            title="合并后的错误模式",
            explanation="合并后的复习说明。",
        )

        records = self.service.records()
        self.assertEqual(result["deleted_count"], 1)
        self.assertIn("errors:first-error", records)
        self.assertNotIn("errors:second-error", records)
        self.assertEqual(records["errors:first-error"]["title"], "合并后的错误模式")
        self.assertEqual(records["errors:first-error"]["learned_count"], 2)
        self.assertEqual(records["errors:first-error"]["review_count"], 2)
        self.assertEqual(records["errors:first-error"]["mastery_score"], 6)

    def test_invalid_batch_rolls_back_every_record(self) -> None:
        before = self.store.data_path.read_text(encoding="utf-8")
        invalid = payload("grammar", "broken")
        invalid["source"] = ""

        with self.assertRaisesRegex(RecordError, "source must not be empty"):
            self.service.batch_upsert([payload("usage", "valid"), invalid])

        self.assertEqual(self.store.data_path.read_text(encoding="utf-8"), before)

    def test_batch_rejects_non_object_records_and_non_string_tags(self) -> None:
        with self.assertRaisesRegex(RecordError, "record must be an object"):
            self.service.batch_upsert(["not-an-object"])  # type: ignore[list-item]
        invalid_tags = payload("usage", "invalid-tags")
        invalid_tags["tags"] = ["valid", 3]
        with self.assertRaisesRegex(RecordError, "tags must be an array of strings"):
            self.service.batch_upsert([invalid_tags])
        self.assertEqual(self.service.records(), {})

    def test_tags_are_deduplicated_case_insensitively(self) -> None:
        record_payload = payload("usage", "tag-normalization")
        record_payload["tags"] = ["Core", "core", " review "]

        result = self.service.upsert(record_payload)

        self.assertEqual(result["tags"], ["Core", "review"])

    def test_complete_review_scores_and_records_errors_in_one_transaction(self) -> None:
        self.service.upsert(payload("grammar", "target-rule"))
        error = payload("errors", "missing-article")

        result = self.service.complete_review("grammar:target-rule", 8, [error])

        self.assertEqual(result["status"], "familiar")
        self.assertTrue(result["archived"])
        self.assertEqual(result["review_count"], 1)
        self.assertEqual(len(result["errors"]), 1)
        records = self.service.records()
        self.assertIn("errors:missing-article", records)
        self.assertEqual(records["grammar:target-rule"]["review_history"][0]["score"], 8)
        self.assertIsNotNone(records["grammar:target-rule"]["next_review_at"])

    def test_invalid_error_rolls_back_review_score(self) -> None:
        self.service.upsert(payload("grammar", "target-rule"))
        invalid_error = payload("errors", "invalid-error")
        invalid_error["source"] = ""

        with self.assertRaisesRegex(RecordError, "source must not be empty"):
            self.service.complete_review("grammar:target-rule", 7, [invalid_error])

        record = self.service.records()["grammar:target-rule"]
        self.assertEqual(record["review_count"], 0)
        self.assertEqual(record["mastery_score"], 0)

    def test_expected_review_status_is_checked_inside_transaction(self) -> None:
        self.service.upsert(payload("grammar", "status-check"))

        with self.assertRaisesRegex(RecordError, "familiar record does not exist"):
            self.service.complete_review(
                "grammar:status-check", 8, expected_status="familiar"
            )

        self.assertEqual(self.service.records()["grammar:status-check"]["review_count"], 0)

    def test_status_transitions_and_lapses(self) -> None:
        self.service.upsert(payload("phrases", "solid-phrase"))
        first = self.service.complete_review("phrases:solid-phrase", 10)
        self.assertEqual(first["status"], "mastered")
        mastered_at = first["mastered_at"]

        second = self.service.complete_review("phrases:solid-phrase", 10)
        self.assertEqual(second["mastered_at"], mastered_at)

        third = self.service.complete_review("phrases:solid-phrase", 6)
        self.assertEqual(third["status"], "learning")
        self.assertEqual(third["lapse_count"], 1)

    def test_mastered_records_keep_full_learning_content(self) -> None:
        self.service.upsert(payload("usage", "polite-request"))
        self.service.complete_review("usage:polite-request", 10)

        record = self.service.records()["usage:polite-request"]

        self.assertEqual(record["status"], "mastered")
        self.assertEqual(record["source"], "Source for polite-request")
        self.assertEqual(record["example"], "Example for polite-request")
        self.assertEqual(record["tags"], ["core", "review"])

    def test_menu_contexts_are_centralized_and_bounded(self) -> None:
        for category in ("errors", "grammar", "vocabulary", "phrases", "usage"):
            self.service.upsert(payload(category, f"{category}-item"))
        self.service.complete_review("grammar:grammar-item", 8)
        self.service.complete_review("usage:usage-item", 10)

        initial = self.service.menu("initial")
        active = self.service.menu("exercise-active", focus="present perfect")
        complete = self.service.menu("review-complete", focus="present perfect")
        explained = self.service.menu(
            "review-complete",
            focus="present perfect",
            current_exercise_explained=True,
        )

        for menu in (initial, active, complete):
            self.assertGreaterEqual(len(menu["options"]), 3)
            self.assertLessEqual(len(menu["options"]), 5)
            self.assertIn("popular", {option["group"] for option in menu["options"]})
            self.assertIn("scenario-dialogue", {option["id"] for option in menu["options"]})
            for option in menu["options"]:
                if "count" in option:
                    self.assertTrue(option["label"].endswith(f"（{option['count']}）"))
        self.assertIn("explain-current-exercise", {item["id"] for item in active["options"]})
        complete_explain = next(
            item for item in complete["options"] if item["id"] == "explain-current-exercise"
        )
        self.assertEqual(complete_explain["group"], "popular")
        self.assertNotIn(
            "explain-current-exercise", {item["id"] for item in explained["options"]}
        )
        active_mastered_paper = next(
            item for item in active["options"] if item["id"] == "mastered-cet-paper"
        )
        self.assertEqual(active_mastered_paper["count"], 1)
        complete_mastered_paper = next(
            item for item in complete["options"] if item["id"] == "mastered-cet-paper"
        )
        self.assertEqual(complete_mastered_paper["count"], 1)
        active_labels = {item["id"]: item["label"] for item in active["options"]}
        self.assertNotIn("cet-practice", active_labels)
        self.assertIn("mastered-cet-paper", active_labels)
        self.assertNotIn("present perfect", active_labels["scenario-dialogue"])
        self.assertIn("完整场景对话", active_labels["scenario-dialogue"])
        self.assertNotIn("开始一段", active_labels["scenario-dialogue"])
        initial_labels = {item["id"]: item["label"] for item in initial["options"]}
        self.assertIn("咖啡店", initial_labels["scenario-dialogue"])
        self.assertIn("完整场景对话", initial_labels["scenario-dialogue"])
        mastered_paper = next(
            item for item in initial["options"] if item["id"] == "mastered-cet-paper"
        )
        self.assertEqual(mastered_paper["count"], 1)
        self.assertTrue(mastered_paper["label"].endswith("（1）"))
        self.assertNotIn(
            "复习掌握不稳的知识点、语法和句型",
            {item["label"] for item in initial["options"]},
        )

    def test_merged_review_path_includes_every_category(self) -> None:
        for category in ("errors", "grammar", "vocabulary", "phrases", "usage"):
            self.service.upsert(payload(category, f"{category}-item"))
        self.service.complete_review("errors:errors-item", 2)
        self.service.complete_review("grammar:grammar-item", 3)
        self.service.complete_review("usage:usage-item", 1)
        menu = self.service.menu("initial")
        mixed = next(option for option in menu["options"] if option["id"].startswith("mixed+"))

        selected = self.service.next_review(path=mixed["id"])

        self.assertEqual(mixed["count"], menu["counts"]["totals"]["learning"])
        self.assertEqual(mixed["icon"], "🎯")
        self.assertEqual(
            set(mixed["categories"]), {"errors", "grammar", "vocabulary", "phrases", "usage"}
        )
        self.assertIn(selected["record"]["category"], mixed["categories"])

    def test_next_review_prefers_due_low_score_and_supports_statuses(self) -> None:
        self.service.upsert(payload("grammar", "low"))
        self.service.upsert(payload("grammar", "high"))
        self.service.complete_review("grammar:high", 8)

        learning = self.service.next_review(categories=["grammar"])
        familiar = self.service.next_review(categories=["grammar"], status="familiar")

        self.assertEqual(learning["record"]["id"], "grammar:low")
        self.assertEqual(familiar["record"]["id"], "grammar:high")

    def test_next_review_claims_records_to_avoid_parallel_duplicates(self) -> None:
        self.service.upsert(payload("grammar", "first"))
        self.service.upsert(payload("grammar", "second"))

        first = self.service.next_review(categories=["grammar"], claim_owner="session-a")
        second = self.service.next_review(categories=["grammar"], claim_owner="session-b")

        self.assertEqual(first["record"]["id"], "grammar:first")
        self.assertEqual(second["record"]["id"], "grammar:second")
        claims = json.loads(self.store.review_claims_path.read_text(encoding="utf-8"))
        claimed = claims["claims"]["grammar:first"]
        self.assertEqual(claimed["owner"], "session-a")
        self.assertNotIn("review_claim", self.service.records()["grammar:first"])

        self.service.complete_review("grammar:first", 7)

        self.assertNotIn("review_claim", self.service.records()["grammar:first"])

    def test_expired_review_claims_are_reused(self) -> None:
        self.service.upsert(payload("grammar", "claim-timeout"))
        first = self.service.next_review(categories=["grammar"], claim_owner="session-a")
        claims = json.loads(self.store.review_claims_path.read_text(encoding="utf-8"))
        claims["claims"]["grammar:claim-timeout"]["expires_at"] = (
            datetime.now().astimezone() - timedelta(seconds=1)
        ).isoformat(timespec="seconds")
        self.store.review_claims_path.write_text(
            json.dumps(claims, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        second = self.service.next_review(categories=["grammar"], claim_owner="session-b")

        self.assertEqual(first["record"]["id"], "grammar:claim-timeout")
        self.assertEqual(second["record"]["id"], "grammar:claim-timeout")
        self.assertEqual(second["record"]["review_claim"]["owner"], "session-b")

    def test_search_summary_history_and_stats(self) -> None:
        self.service.upsert(payload("vocabulary", "context-word"))
        self.service.complete_review("vocabulary:context-word", 7)

        self.assertEqual(self.service.search("context word")[0]["id"], "vocabulary:context-word")
        self.assertEqual(self.service.summary()["totals"]["learning"], 1)
        self.assertEqual(len(self.service.history("vocabulary:context-word")["history"]), 1)
        stats = self.service.stats(30)
        self.assertEqual(stats["review_count"], 1)
        self.assertEqual(stats["average_score"], 7)

    def test_validate_reports_all_schema_errors(self) -> None:
        self.service.upsert(payload("grammar", "invalid-time"))
        database = self.store.read()
        database["records"]["grammar:invalid-time"]["last_learned_at"] = "yesterday"
        database["records"]["grammar:invalid-time"]["tags"] = ["same", "same"]
        self.store.data_path.write_text(
            json.dumps(database, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        result = self.service.validate()

        self.assertFalse(result["valid"])
        self.assertEqual(result["issue_count"], 2)

    def test_repair_deduplicates_tags_and_supports_dry_run(self) -> None:
        self.service.upsert(payload("usage", "repair-tags"))
        database = self.store.read()
        database["records"]["usage:repair-tags"]["tags"] = ["core", "core", " review "]
        self.store.data_path.write_text(
            json.dumps(database, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        preview = self.service.repair(dry_run=True)
        self.assertEqual(preview["change_count"], 1)
        self.assertFalse(self.service.validate()["valid"])

        applied = self.service.repair(dry_run=False)
        self.assertEqual(applied["change_count"], 1)
        self.assertTrue(self.service.validate()["valid"])

    def test_repair_reconciles_status_with_mastery_score(self) -> None:
        self.service.upsert(payload("grammar", "repair-status"))
        database = self.store.read()
        database["records"]["grammar:repair-status"]["mastery_score"] = 8
        self.store.data_path.write_text(
            json.dumps(database, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        result = self.service.repair(dry_run=False)

        self.assertIn(
            {"id": "grammar:repair-status", "field": "status"}, result["changes"]
        )
        self.assertEqual(self.service.records()["grammar:repair-status"]["status"], "familiar")

    def test_atomic_failure_preserves_previous_database(self) -> None:
        self.service.upsert(payload("grammar", "before-failure"))
        before = self.store.data_path.read_bytes()
        os.environ["LEARN_ENGLISH_FAIL_BEFORE_REPLACE"] = "1"
        self.addCleanup(os.environ.pop, "LEARN_ENGLISH_FAIL_BEFORE_REPLACE", None)

        with self.assertRaisesRegex(RecordError, "injected failure"):
            self.service.upsert(payload("grammar", "after-failure"))

        self.assertEqual(self.store.data_path.read_bytes(), before)

    def test_atomic_write_preserves_database_permissions(self) -> None:
        self.store.data_path.chmod(0o644)

        self.service.upsert(payload("grammar", "permissions"))

        self.assertEqual(self.store.data_path.stat().st_mode & 0o777, 0o644)

    def test_legacy_migration_preserves_statuses_and_counts(self) -> None:
        migration_root = self.root / "migration"
        learning = migration_root / "learning-records"
        mastered = migration_root / "mastered-learning-records"
        learning.mkdir(parents=True)
        mastered.mkdir(parents=True)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        (learning / "grammar.json").write_text(
            json.dumps(
                {
                    "category": "grammar",
                    "items": [
                        {
                            "id": "grammar:legacy-rule",
                            "title": "Legacy rule",
                            "explanation": "Legacy explanation",
                            "source": "Legacy source",
                            "example": "Legacy example",
                            "tags": [],
                            "first_learned_at": timestamp,
                            "last_learned_at": timestamp,
                            "learned_count": 2,
                            "mastery_score": 5,
                            "review_count": 1,
                            "high_score_streak": 0,
                            "last_reviewed_at": timestamp,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (mastered / "usage.json").write_text(
            json.dumps(
                {
                    "category": "usage",
                    "items": [
                        {
                            "id": "usage:legacy-mastered",
                            "title": "Legacy mastered",
                            "summary": "Preserved summary",
                            "mastered_at": timestamp,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        migration_service = RecordService(RecordStore(migration_root))

        preview = migration_service.migrate_legacy(dry_run=True)
        applied = migration_service.migrate_legacy(dry_run=False)

        self.assertEqual(preview["record_count"], 2)
        self.assertEqual(applied["counts"], {"learning": 1, "familiar": 0, "mastered": 1})
        migrated = migration_service.records()
        self.assertEqual(migrated["grammar:legacy-rule"]["learned_count"], 2)
        self.assertEqual(migrated["usage:legacy-mastered"]["status"], "mastered")
        self.assertEqual(migrated["usage:legacy-mastered"]["explanation"], "Preserved summary")

    def test_record_service_does_not_commit_git_changes(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Tests"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "learning-records/records.json"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "initial"], cwd=self.root, check=True)
        unrelated = self.root / "notes.txt"
        unrelated.write_text("staged\n", encoding="utf-8")
        subprocess.run(["git", "add", "notes.txt"], cwd=self.root, check=True)

        RecordService(self.store).upsert(payload("grammar", "git-scope"))

        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        self.assertIn(" M learning-records/records.json", status)
        self.assertIn("A  notes.txt", status)

    def test_cli_compatibility_and_batch_input(self) -> None:
        input_path = self.root / "batch.json"
        input_path.write_text(json.dumps({"records": [payload("phrases", "cli-batch")]}), encoding="utf-8")
        environment = {
            **os.environ,
            "LEARN_ENGLISH_REPO_ROOT": str(self.root),
        }

        subprocess.run(
            [sys.executable, str(SCRIPT), "batch-upsert", "--input", str(input_path)],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        listed = subprocess.run(
            [sys.executable, str(SCRIPT), "list", "--category", "phrases"],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(listed.stdout)[0]["id"], "phrases:cli-batch")
        reviewed = subprocess.run(
            [sys.executable, str(SCRIPT), "complete-review", "--input", "-"],
            env=environment,
            input=json.dumps({"id": "phrases:cli-batch", "score": 8, "errors": []}),
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(reviewed.stdout)["status"], "familiar")

    def test_cli_validate_returns_nonzero_for_invalid_data(self) -> None:
        invalid_root = self.root / "invalid-cli"
        invalid_store = RecordStore(invalid_root)
        invalid_store.initialize(empty_database())
        database = invalid_store.read()
        database["schema_version"] = 999
        invalid_store.data_path.write_text(json.dumps(database), encoding="utf-8")
        environment = {
            **os.environ,
            "LEARN_ENGLISH_REPO_ROOT": str(invalid_root),
        }

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "validate"],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["valid"])


if __name__ == "__main__":
    unittest.main()
