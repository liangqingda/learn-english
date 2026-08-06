from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from learning_records_tool.models import RecordError, empty_database  # noqa: E402
from learning_records_tool.menu import build_menu  # noqa: E402
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


def distinct_payload(category: str, key: str, title: str) -> dict[str, object]:
    item = payload(category, key)
    item["title"] = title
    item["explanation"] = f"{title} 的专项说明，重点不同于其他测试记录。"
    item["source"] = f"Source sentence about {title}."
    item["example"] = f"Example sentence about {title}."
    return item


def mark_mastered(service: RecordService, identifier: str) -> dict[str, object]:
    service.complete_review(identifier, 10)
    service.complete_review(identifier, 10)
    return service.complete_review(identifier, 10)


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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

    def test_transaction_does_not_rewrite_unchanged_category_files(self) -> None:
        before = {
            category: self.store.category_path(category).read_bytes()
            for category in ("phrases", "vocabulary", "usage", "errors")
        }

        self.service.upsert(payload("grammar", "category-local-revision"))

        grammar = read_json(self.store.category_path("grammar"))
        self.assertEqual(grammar["revision"], 1)
        for category, content in before.items():
            self.assertEqual(self.store.category_path(category).read_bytes(), content)

    def test_later_transaction_preserves_previously_changed_category(self) -> None:
        self.service.upsert(payload("grammar", "first-category-change"))
        grammar_before = self.store.category_path("grammar").read_bytes()

        self.service.upsert(payload("vocabulary", "second-category-change"))

        self.assertEqual(self.store.category_path("grammar").read_bytes(), grammar_before)
        vocabulary = read_json(self.store.category_path("vocabulary"))
        self.assertEqual(vocabulary["revision"], 2)

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

    def test_fuzzy_upsert_enriches_canonical_record_content(self) -> None:
        original = payload("usage", "polite-request")
        original["title"] = "polite request with could"
        original["explanation"] = "Could makes a request polite."
        original["source"] = "Could you help?"
        original["example"] = ""
        original["tags"] = ["requests"]
        self.service.upsert(original)
        richer = {**original, "key": "polite-could-request"}
        richer["explanation"] = "Could you is a conventional way to make a request sound more polite."
        richer["source"] = "Could you help me carry these boxes after the meeting?"
        richer["example"] = "Could you open the window, please?"
        richer["tags"] = ["requests", "politeness"]

        result = self.service.upsert(richer)

        record = self.service.records()["usage:polite-request"]
        self.assertFalse(result["created"])
        self.assertEqual(
            set(result["enriched_fields"]), {"tags", "explanation", "source", "example"}
        )
        self.assertEqual(record["tags"], ["politeness", "requests"])
        self.assertEqual(record["example"], richer["example"])
        self.assertEqual(record["status"], "learning")

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

    def test_merge_two_single_perfect_records_remains_familiar(self) -> None:
        first = distinct_payload(
            "grammar", "first-perfect", "modal deduction in past contexts"
        )
        second = distinct_payload(
            "grammar", "second-perfect", "article omission before abstract nouns"
        )
        self.service.upsert(first)
        self.service.upsert(second)
        self.service.complete_review("grammar:first-perfect", 10)
        self.service.complete_review("grammar:second-perfect", 10)

        result = self.service.merge_records(
            "grammar:first-perfect", ["grammar:second-perfect"]
        )

        record = self.service.records()["grammar:first-perfect"]
        self.assertEqual(result["status"], "familiar")
        self.assertEqual(record["status"], "familiar")
        self.assertEqual(record["review_count"], 2)
        self.assertEqual(len(record["review_history"]), 2)

    def test_invalid_batch_rolls_back_every_record(self) -> None:
        before = self.store.category_path("usage").read_text(encoding="utf-8")
        invalid = payload("grammar", "broken")
        invalid["source"] = ""

        with self.assertRaisesRegex(RecordError, "source must not be empty"):
            self.service.batch_upsert([payload("usage", "valid"), invalid])

        self.assertEqual(self.store.category_path("usage").read_text(encoding="utf-8"), before)

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
        self.assertEqual(first["status"], "familiar")
        self.assertIsNone(first["mastered_at"])

        second = self.service.complete_review("phrases:solid-phrase", 10)
        self.assertEqual(second["status"], "familiar")
        self.assertIsNone(second["mastered_at"])

        third = self.service.complete_review("phrases:solid-phrase", 10)
        self.assertEqual(third["status"], "mastered")
        mastered_at = third["mastered_at"]

        mastered_record_id = next(
            record["id"]
            for record in self.service.records().values()
            if record["title"] == "phrases solid-phrase"
        )
        fourth = self.service.complete_review(mastered_record_id, 10)
        self.assertEqual(fourth["status"], "mastered")
        self.assertEqual(fourth["mastered_at"], mastered_at)

        lapsed = self.service.complete_review(mastered_record_id, 6)
        self.assertEqual(lapsed["status"], "learning")
        self.assertEqual(lapsed["lapse_count"], 1)

    def test_three_perfect_reviews_are_required_for_mastery(self) -> None:
        self.service.upsert(payload("grammar", "three-perfects"))

        first = self.service.complete_review("grammar:three-perfects", 10)
        second = self.service.complete_review("grammar:three-perfects", 10)
        third = self.service.complete_review("grammar:three-perfects", 10)

        self.assertEqual(first["status"], "familiar")
        self.assertEqual(second["status"], "familiar")
        self.assertEqual(third["status"], "mastered")
        self.assertIsNotNone(third["mastered_at"])

    def test_mastered_records_are_stored_as_slim_content(self) -> None:
        self.service.upsert(payload("usage", "polite-request"))
        mark_mastered(self.service, "usage:polite-request")

        stored = read_json(self.store.mastered_category_path("usage"))
        record = next(
            item for item in self.service.records().values()
            if item["title"] == "usage polite-request"
        )

        self.assertEqual(
            set(stored[0]),
            {
                "id",
                "title",
                "explanation",
                "mastered_at",
            },
        )
        self.assertEqual(stored[0]["id"], "usage:polite-request")
        self.assertEqual(record["status"], "mastered")
        self.assertEqual(record["source"], "Explanation for polite-request")
        self.assertEqual(record["example"], "")
        self.assertEqual(record["tags"], [])

    def test_mastered_records_move_to_mastered_category_file(self) -> None:
        titles = [
            "ancient river metaphor",
            "subway ticket deadline",
            "formal meeting agenda",
            "kitchen safety notice",
            "library renewal policy",
            "weather forecast nuance",
            "hotel checkout request",
            "museum audio guide",
            "software release note",
            "campus shuttle schedule",
        ]
        for index, title in enumerate(titles):
            self.service.upsert(distinct_payload("usage", f"mastered-{index}", title))
            mark_mastered(self.service, f"usage:mastered-{index}")

        primary = read_json(self.store.category_path("usage"))
        mastered = read_json(self.store.mastered_category_path("usage"))

        self.assertFalse(
            any(record["status"] == "mastered" for record in primary["records"].values())
        )
        self.assertEqual(len(mastered), 10)
        first_mastered = mastered[0]
        self.assertEqual(
            set(first_mastered),
            {
                "id",
                "title",
                "explanation",
                "mastered_at",
            },
        )
        self.assertNotIn("review_history", first_mastered)
        self.assertNotIn("mastery_score", first_mastered)
        self.assertNotIn("next_review_at", first_mastered)
        self.assertEqual(self.service.summary()["totals"]["mastered"], 10)
        self.assertEqual(len(self.service.list_records(status="mastered")), 10)

    def test_full_mastered_file_is_read_and_rewritten_as_slim_category_file(self) -> None:
        self.service.upsert(payload("usage", "full-mastered"))
        mark_mastered(self.service, "usage:full-mastered")
        database = self.store.read()
        mastered_record = next(
            record for record in database["records"].values()
            if record["title"] == "usage full-mastered"
        )
        write_json(
            self.store.category_path("usage"),
            {
                "schema_version": 2,
                "revision": database["revision"],
                "category": "usage",
                "records": {},
            },
        )
        write_json(
            self.store.mastered_category_path("usage"),
            {
                "schema_version": 2,
                "revision": database["revision"],
                "category": "usage",
                "records": {"usage:full-mastered": mastered_record},
            },
        )

        self.service.upsert(payload("grammar", "new-learning"))

        hydrated_mastered = [
            record
            for record in self.service.records().values()
            if record["title"] == "usage full-mastered"
        ]
        self.assertEqual(len(hydrated_mastered), 1)
        self.assertEqual(hydrated_mastered[0]["status"], "mastered")
        rewritten = read_json(self.store.mastered_category_path("usage"))
        self.assertEqual(
            set(rewritten[0]),
            {
                "id",
                "title",
                "explanation",
                "mastered_at",
            },
        )

    def test_mastered_menu_and_selection_read_from_mastered_file(self) -> None:
        titles = [
            "relative clause agreement",
            "past perfect sequence",
            "modal verb deduction",
            "article choice in titles",
            "conditional inversion",
            "gerund after preposition",
            "appositive comma pattern",
            "reported speech backshift",
            "subject complement order",
            "emphatic do usage",
        ]
        for index, title in enumerate(titles):
            self.service.upsert(distinct_payload("grammar", f"cet-source-{index}", title))
            mark_mastered(self.service, f"grammar:cet-source-{index}")

        menu = self.service.menu("initial")
        mastered_paper = next(
            option for option in menu["options"] if option["id"] == "mastered-cet-paper"
        )
        selected = self.service.next_review(status="mastered")

        self.assertEqual(mastered_paper["count"], 10)
        self.assertTrue(self.store.mastered_category_path("grammar").exists())
        self.assertEqual(selected["record"]["status"], "mastered")
        self.assertIn(selected["record"]["title"], titles)

    def test_menu_contexts_include_dynamic_other_options(self) -> None:
        for category in ("errors", "grammar", "vocabulary", "phrases", "usage"):
            self.service.upsert(payload(category, f"{category}-item"))
        self.service.complete_review("grammar:grammar-item", 8)
        mark_mastered(self.service, "usage:usage-item")

        initial = self.service.menu("initial")
        complete = self.service.menu("review-complete", focus="present perfect")
        complete_with_errors = self.service.menu(
            "review-complete",
            focus="present perfect",
            has_answer_errors=True,
        )
        explained = self.service.menu(
            "review-complete",
            focus="present perfect",
            has_answer_errors=True,
            current_exercise_explained=True,
        )

        for menu in (initial, complete, complete_with_errors, explained):
            other_options = [option for option in menu["options"] if option["group"] == "other"]
            rendered_options = [
                rendered
                for option in menu["options"]
                for rendered in (option, *option.get("children", []))
            ]
            self.assertGreaterEqual(len(menu["options"]), 3)
            self.assertGreaterEqual(len(other_options), 3)
            self.assertIn("popular", {option["group"] for option in menu["options"]})
            self.assertIn("scenario-dialogue", {option["id"] for option in menu["options"]})
            self.assertEqual(
                len({option["icon"] for option in rendered_options}),
                len(rendered_options),
            )
            self.assertGreaterEqual(
                sum(option["kind"] == "follow-up-learning" for option in other_options),
                2,
            )
            for option in menu["options"]:
                if "count" in option and option["id"] != "mastered-cet-paper":
                    self.assertTrue(option["label"].endswith(f"（{option['count']}）"))
        self.assertNotIn(
            "explain-current-exercise", {item["id"] for item in complete["options"]}
        )
        complete_explain = next(
            item
            for item in complete_with_errors["options"]
            if item["id"] == "explain-current-exercise"
        )
        self.assertEqual(complete_explain["group"], "popular")
        self.assertEqual(complete_explain["label"], "讲解错题")
        self.assertEqual(complete_with_errors["options"][0], complete_explain)
        self.assertNotIn(
            "explain-current-exercise", {item["id"] for item in explained["options"]}
        )
        complete_mastered_paper = next(
            item for item in complete["options"] if item["id"] == "mastered-cet-paper"
        )
        self.assertEqual(complete_mastered_paper["count"], 1)
        self.assertEqual(complete_mastered_paper["group"], "popular")
        self.assertEqual(
            complete_mastered_paper["label"],
            "基于 1 个已掌握知识点生成完整四六级套题（不含听力）",
        )
        self.assertEqual(complete_mastered_paper["action"], {"command": "mastered-list"})
        complete_labels = {item["id"]: item["label"] for item in complete["options"]}
        self.assertNotIn("cet-practice", complete_labels)
        self.assertIn("mastered-cet-paper", complete_labels)
        self.assertIn(
            "follow-up-learning",
            {item["kind"] for item in complete["options"] if item["group"] == "other"},
        )
        self.assertTrue(
            any(
                "present perfect" in item["label"]
                for item in complete["options"]
                if item["kind"] == "follow-up-learning"
            )
        )
        self.assertIn("present perfect", complete_labels["scenario-dialogue"])
        self.assertIn("完整场景对话", complete_labels["scenario-dialogue"])
        self.assertNotIn("开始一段", complete_labels["scenario-dialogue"])
        initial_labels = {item["id"]: item["label"] for item in initial["options"]}
        self.assertNotIn("咖啡店", initial_labels["scenario-dialogue"])
        self.assertIn("errors errors-item", initial_labels["scenario-dialogue"])
        self.assertIn("完整场景对话", initial_labels["scenario-dialogue"])
        mastered_paper = next(
            item for item in initial["options"] if item["id"] == "mastered-cet-paper"
        )
        self.assertEqual(mastered_paper["count"], 1)
        self.assertEqual(mastered_paper["group"], "popular")
        self.assertEqual(
            mastered_paper["label"],
            "基于 1 个已掌握知识点生成完整四六级套题（不含听力）",
        )
        mastered_review = next(
            item for item in initial["options"] if item["id"] == "mastered-review"
        )
        self.assertEqual(
            mastered_review["action"],
            {"command": "next-review", "status": "mastered", "random": True},
        )
        self.assertIn("learning-progress", initial_labels)
        progress = next(
            item for item in initial["options"] if item["id"] == "learning-progress"
        )
        self.assertEqual(progress["action"], {"command": "stats", "period": "30d"})
        self.assertNotIn(
            "复习掌握不稳的知识点、语法和句型",
            {item["label"] for item in initial["options"]},
        )

    def test_empty_menu_includes_at_least_three_other_options(self) -> None:
        menu = self.service.menu("initial")
        other_options = [option for option in menu["options"] if option["group"] == "other"]

        self.assertEqual(menu["state"], "empty")
        self.assertGreaterEqual(len(other_options), 3)
        self.assertIn("starter-practice", {option["id"] for option in other_options})
        self.assertIn("scenario-dialogue", {option["id"] for option in other_options})

    def test_follow_up_menu_only_includes_available_review_statuses(self) -> None:
        self.service.upsert(payload("grammar", "status-matrix"))

        learning = self.service.menu("review-complete")
        learning_ids = {option["id"] for option in learning["options"]}
        self.assertIn("continue-review", learning_ids)
        self.assertNotIn("familiar-review", learning_ids)
        self.assertNotIn("mastered-review", learning_ids)

        self.service.complete_review("grammar:status-matrix", 8)
        familiar = self.service.menu("review-complete")
        familiar_ids = {option["id"] for option in familiar["options"]}
        self.assertNotIn("continue-review", familiar_ids)
        self.assertIn("familiar-review", familiar_ids)
        self.assertNotIn("mastered-review", familiar_ids)

        self.service.upsert(payload("usage", "mastered-alongside-familiar"))
        mark_mastered(self.service, "usage:mastered-alongside-familiar")
        mixed = self.service.menu("review-complete", has_answer_errors=True)
        mixed_ids = {option["id"] for option in mixed["options"]}
        self.assertNotIn("continue-review", mixed_ids)
        self.assertIn("familiar-review", mixed_ids)
        self.assertIn("mastered-review", mixed_ids)
        self.assertIn("mastered-cet-paper", mixed_ids)
        self.assertIn("explain-current-exercise", mixed_ids)
        self.assertTrue(any(option["group"] == "popular" for option in mixed["options"]))
        self.assertTrue(
            all(option.get("count", 1) > 0 for option in mixed["options"])
        )

    def test_initial_menu_treats_whitespace_focus_as_missing(self) -> None:
        self.service.upsert(payload("grammar", "whitespace-focus"))

        menu = self.service.menu("initial", focus="   ")
        scenario = next(
            option for option in menu["options"] if option["id"] == "scenario-dialogue"
        )

        self.assertNotIn("咖啡店", scenario["label"])
        self.assertEqual(scenario["focus"], "grammar whitespace-focus")

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
        self.assertEqual(len(mixed["children"]), 3)
        self.assertTrue(
            all(child["parent_id"] == mixed["id"] for child in mixed["children"])
        )
        self.assertEqual(
            {child["action"]["path"] for child in mixed["children"]},
            {"errors-grammar", "vocabulary-phrases", "usage"},
        )
        self.assertEqual(
            set(mixed["categories"]), {"errors", "grammar", "vocabulary", "phrases", "usage"}
        )
        self.assertIn(selected["record"]["category"], mixed["categories"])

    def test_menu_exposes_claim_availability_and_busy_state(self) -> None:
        self.service.upsert(payload("grammar", "claimed-grammar"))
        self.service.upsert(payload("vocabulary", "available-vocabulary"))
        availability_counts = {
            "by_status": {"learning": 1, "familiar": 0, "mastered": 0},
            "by_category": {
                "vocabulary": 1,
                "phrases": 0,
                "grammar": 0,
                "usage": 0,
                "errors": 0,
            },
            "claimed_by_status": {"learning": 1, "familiar": 0, "mastered": 0},
            "claimed_by_category": {
                "vocabulary": 0,
                "phrases": 0,
                "grammar": 1,
                "usage": 0,
                "errors": 0,
            },
        }

        initial = build_menu(
            self.service.records(),
            "initial",
            availability_counts=availability_counts,
        )
        mixed = next(item for item in initial["options"] if item["kind"] == "review-path")
        children = {child["id"]: child for child in mixed["children"]}
        self.assertEqual(mixed["available_count"], 1)
        self.assertEqual(mixed["claimed_count"], 1)
        self.assertFalse(mixed["busy"])
        self.assertTrue(children["errors-grammar"]["busy"])
        self.assertTrue(children["errors-grammar"]["disabled"])
        self.assertIn("暂时无可用", children["errors-grammar"]["label"])

        complete = build_menu(
            self.service.records(),
            "review-complete",
            availability_counts=availability_counts,
        )
        continuation = next(
            item for item in complete["options"] if item["id"] == "continue-review"
        )
        self.assertEqual(continuation["available_count"], 1)
        self.assertEqual(continuation["claimed_count"], 1)
        self.assertIn("可用 1", continuation["label"])

    def test_initial_menu_offers_error_cluster_review_for_multiple_errors(self) -> None:
        first = distinct_payload("errors", "article-error", "missing article before job title")
        second = distinct_payload("errors", "preposition-error", "wrong preposition after wait")
        first["tags"] = ["articles", "review-error"]
        second["tags"] = ["prepositions"]
        self.service.upsert(first)
        self.service.upsert(second)

        menu = self.service.menu("initial")
        cluster_option = next(
            item for item in menu["options"] if item["id"] == "error-clusters"
        )

        self.assertEqual(cluster_option["group"], "other")
        self.assertEqual(cluster_option["kind"], "error-clusters")
        self.assertEqual(cluster_option["count"], 2)
        self.assertEqual(
            cluster_option["action"],
            {"command": "error-clusters", "minimum_size": 2},
        )
        self.assertGreaterEqual(
            sum(item["group"] == "other" for item in menu["options"]), 3
        )

    def test_exercise_active_menu_context_is_rejected(self) -> None:
        with self.assertRaisesRegex(RecordError, "invalid menu context"):
            self.service.menu("exercise-active")

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
        self.assertTrue(claimed["token"])
        self.assertNotIn("review_claim", self.service.records()["grammar:first"])

        self.service.complete_review(
            "grammar:first",
            7,
            claim_owner="session-a",
            claim_token=claimed["token"],
        )

        self.assertNotIn("review_claim", self.service.records()["grammar:first"])
        claims = json.loads(self.store.review_claims_path.read_text(encoding="utf-8"))
        self.assertNotIn("grammar:first", claims["claims"])

    def test_same_owner_resumes_claim_and_token_guards_completion_and_release(self) -> None:
        self.service.upsert(payload("grammar", "claim-resume"))
        first = self.service.next_review(categories=["grammar"], claim_owner="session-a")

        resumed = self.service.next_review(categories=["grammar"], claim_owner="session-a")

        self.assertTrue(resumed["resumed"])
        self.assertEqual(resumed["record"]["id"], first["record"]["id"])
        claim = resumed["record"]["review_claim"]
        self.assertEqual(claim["token"], first["record"]["review_claim"]["token"])
        with self.assertRaisesRegex(RecordError, "does not match"):
            self.service.complete_review(
                "grammar:claim-resume",
                7,
                claim_owner="session-a",
                claim_token="wrong-token",
            )
        with self.assertRaisesRegex(RecordError, "does not match"):
            self.service.release_claim(
                "grammar:claim-resume",
                claim_owner="session-b",
                claim_token=claim["token"],
            )

        released = self.service.release_claim(
            "grammar:claim-resume",
            claim_owner="session-a",
            claim_token=claim["token"],
        )

        self.assertTrue(released["released"])
        self.service.complete_review("grammar:claim-resume", 7)

    def test_claim_release_failure_keeps_saved_score_and_is_cleaned_lazily(self) -> None:
        self.service.upsert(payload("grammar", "claim-release-failure"))
        selected = self.service.next_review(
            categories=["grammar"], claim_owner="failing-claim-session"
        )
        claim = selected["record"]["review_claim"]

        with mock.patch.object(
            self.store,
            "_write_review_claims",
            side_effect=OSError("injected claim write failure"),
        ):
            result = self.service.complete_review(
                "grammar:claim-release-failure",
                7,
                claim_owner="failing-claim-session",
                claim_token=claim["token"],
            )

        record = self.service.records()["grammar:claim-release-failure"]
        self.assertEqual(record["review_count"], 1)
        self.assertEqual(record["mastery_score"], 7)
        self.assertFalse(result["claim_released"])
        self.assertIn("cleanup failed", result["warning"])

        selected_again = self.service.next_review(
            categories=["grammar"], claim_owner="retry-session"
        )

        self.assertEqual(selected_again["record"]["id"], "grammar:claim-release-failure")
        self.assertEqual(self.service.records()["grammar:claim-release-failure"]["review_count"], 1)

    def test_database_failure_retains_claim_for_exact_retry(self) -> None:
        self.service.upsert(payload("grammar", "claim-retry"))
        selected = self.service.next_review(categories=["grammar"], claim_owner="session-a")
        claim = selected["record"]["review_claim"]
        os.environ["LEARN_ENGLISH_FAIL_BEFORE_REPLACE"] = "1"
        try:
            with self.assertRaisesRegex(RecordError, "injected failure"):
                self.service.complete_review(
                    "grammar:claim-retry",
                    7,
                    claim_owner="session-a",
                    claim_token=claim["token"],
                )
        finally:
            os.environ.pop("LEARN_ENGLISH_FAIL_BEFORE_REPLACE", None)

        persisted_claim = read_json(self.store.review_claims_path)["claims"][
            "grammar:claim-retry"
        ]
        self.assertEqual(persisted_claim["token"], claim["token"])
        result = self.service.complete_review(
            "grammar:claim-retry",
            7,
            claim_owner="session-a",
            claim_token=claim["token"],
        )
        self.assertEqual(result["review_count"], 1)

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

    def test_overdue_records_precede_new_items_but_new_item_gets_fixed_quota(self) -> None:
        self.service.upsert(
            distinct_payload("grammar", "overdue-item", "conditional inversion review")
        )
        self.service.complete_review("grammar:overdue-item", 7)
        self.service.complete_review("grammar:overdue-item", 7)
        self.service.upsert(
            distinct_payload("grammar", "new-item", "article choice in newspaper titles")
        )

        def make_overdue(database: dict[str, object]) -> None:
            record = database["records"]["grammar:overdue-item"]  # type: ignore[index]
            record["first_learned_at"] = (
                datetime.now().astimezone() - timedelta(days=4)
            ).isoformat(timespec="seconds")
            record["last_reviewed_at"] = (
                datetime.now().astimezone() - timedelta(days=3)
            ).isoformat(timespec="seconds")
            record["next_review_at"] = (
                datetime.now().astimezone() - timedelta(days=2)
            ).isoformat(timespec="seconds")

        self.store.transaction(make_overdue)
        overdue = self.service.next_review(categories=["grammar"], claim_owner="session-a")
        self.assertEqual(overdue["record"]["id"], "grammar:overdue-item")
        claim = overdue["record"]["review_claim"]
        self.service.complete_review(
            "grammar:overdue-item",
            7,
            claim_owner="session-a",
            claim_token=claim["token"],
        )
        self.store.transaction(make_overdue)

        quota = self.service.next_review(categories=["grammar"], claim_owner="session-b")

        self.assertEqual(quota["record"]["id"], "grammar:new-item")

    def test_review_priority_compares_timezone_offsets_as_instants(self) -> None:
        self.service.upsert(
            distinct_payload("grammar", "earlier-instant", "modal deduction timeline")
        )
        self.service.upsert(
            distinct_payload("grammar", "later-instant", "gerund after a preposition")
        )

        def set_due_times(database: dict[str, object]) -> None:
            records = database["records"]  # type: ignore[assignment]
            records["grammar:earlier-instant"]["next_review_at"] = "2020-01-01T08:00:00+08:00"
            records["grammar:later-instant"]["next_review_at"] = "2020-01-01T01:00:00+00:00"

        self.store.transaction(set_due_times)

        selected = self.service.next_review(categories=["grammar"], claim_owner="timezone-test")

        self.assertEqual(selected["record"]["id"], "grammar:earlier-instant")

    def test_search_summary_history_and_stats(self) -> None:
        self.service.upsert(payload("vocabulary", "context-word"))
        self.service.complete_review("vocabulary:context-word", 7)

        self.assertEqual(self.service.search("context word")[0]["id"], "vocabulary:context-word")
        self.assertEqual(self.service.summary()["totals"]["learning"], 1)
        self.assertEqual(len(self.service.history("vocabulary:context-word")["history"]), 1)
        stats = self.service.stats(30)
        self.assertEqual(stats["review_count"], 1)
        self.assertEqual(stats["average_score"], 7)

    def test_search_rejects_punctuation_and_ranks_named_fields_across_statuses(self) -> None:
        title_match = distinct_payload(
            "vocabulary", "resilient-title", "resilient"
        )
        source_match = distinct_payload(
            "usage", "resilient-source", "recovering after a difficult event"
        )
        source_match["source"] = "The community proved resilient after the storm."
        self.service.upsert(title_match)
        self.service.upsert(source_match)
        self.service.complete_review("usage:resilient-source", 8)

        with self.assertRaisesRegex(RecordError, "letter or number"):
            self.service.search("!!!")
        results = self.service.search("resilient")

        self.assertEqual(results[0]["id"], "vocabulary:resilient-title")
        self.assertIn("title", results[0]["matched_fields"])
        self.assertIn("source", results[1]["matched_fields"])
        self.assertEqual(results[1]["status"], "familiar")
        self.assertTrue(results[1]["snippet"])

    def test_error_pattern_clusters_returns_related_groups_and_unclustered_items(self) -> None:
        first = distinct_payload(
            "errors", "missing-article-job", "missing article before a job title"
        )
        first["tags"] = ["articles"]
        second = distinct_payload(
            "errors", "article-profession", "article omitted before a profession"
        )
        second["tags"] = ["articles", "review-error"]
        unrelated = distinct_payload(
            "errors", "modal-base-form", "modal verbs require the base form"
        )
        unrelated["tags"] = ["modal-verbs", "review-error"]
        self.service.batch_upsert([first, second, unrelated])

        result = self.service.error_pattern_clusters()

        self.assertEqual(result["cluster_count"], 1)
        self.assertEqual(
            set(result["clusters"][0]["record_ids"]),
            {"errors:missing-article-job", "errors:article-profession"},
        )
        self.assertEqual(
            [record["id"] for record in result["unclustered"]],
            ["errors:modal-base-form"],
        )

    def test_stats_include_daily_category_distribution_backlog_and_transitions(self) -> None:
        self.service.upsert(
            distinct_payload("grammar", "lapse-stat", "reported speech backshift")
        )
        self.service.complete_review("grammar:lapse-stat", 8)
        self.service.complete_review("grammar:lapse-stat", 6)
        self.service.upsert(
            distinct_payload("usage", "mastery-stat", "formal meeting agenda")
        )
        mark_mastered(self.service, "usage:mastery-stat")
        self.service.upsert(
            distinct_payload("vocabulary", "new-backlog-stat", "queue vocabulary review")
        )

        stats = self.service.stats(7)

        self.assertEqual(len(stats["daily"]), 7)
        grammar = next(
            item for item in stats["by_category"] if item["category"] == "grammar"
        )
        self.assertEqual(grammar["review_count"], 2)
        self.assertEqual(grammar["average_score"], 7)
        self.assertEqual(stats["score_distribution"]["5-7"], 1)
        self.assertEqual(stats["score_distribution"]["8-9"], 1)
        self.assertEqual(stats["lapse_count"], 1)
        self.assertEqual(stats["mastery_count"], 1)
        self.assertEqual(stats["snapshot_totals"], stats["status_counts"])
        self.assertEqual(stats["mastered_random_pool"], 1)
        self.assertEqual(stats["due_backlog"]["by_status"]["mastered"], 0)
        self.assertEqual(stats["due_backlog"]["total"], 1)

    def test_validate_reports_all_schema_errors(self) -> None:
        self.service.upsert(payload("grammar", "invalid-time"))
        database = self.store.read()
        database["records"]["grammar:invalid-time"]["last_learned_at"] = "yesterday"
        database["records"]["grammar:invalid-time"]["tags"] = ["same", "same"]
        write_json(
            self.store.category_path("grammar"),
            {
                "schema_version": database["schema_version"],
                "revision": database["revision"],
                "category": "grammar",
                "records": {"grammar:invalid-time": database["records"]["grammar:invalid-time"]},
            },
        )

        result = self.service.validate()

        self.assertFalse(result["valid"])
        self.assertEqual(result["issue_count"], 2)

    def test_validate_reports_malformed_category_root(self) -> None:
        write_json(self.store.category_path("grammar"), [])

        result = self.service.validate()

        self.assertFalse(result["valid"])
        self.assertEqual(result["issue_count"], 1)
        self.assertEqual(result["issues"], [{"message": "database root must be an object"}])

    def test_repair_deduplicates_tags_and_supports_dry_run(self) -> None:
        self.service.upsert(payload("usage", "repair-tags"))
        database = self.store.read()
        database["records"]["usage:repair-tags"]["tags"] = ["core", "core", " review "]
        write_json(
            self.store.category_path("usage"),
            {
                "schema_version": database["schema_version"],
                "revision": database["revision"],
                "category": "usage",
                "records": {"usage:repair-tags": database["records"]["usage:repair-tags"]},
            },
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
        write_json(
            self.store.category_path("grammar"),
            {
                "schema_version": database["schema_version"],
                "revision": database["revision"],
                "category": "grammar",
                "records": {"grammar:repair-status": database["records"]["grammar:repair-status"]},
            },
        )

        result = self.service.repair(dry_run=False)

        self.assertIn(
            {"id": "grammar:repair-status", "field": "status"}, result["changes"]
        )
        self.assertEqual(self.service.records()["grammar:repair-status"]["status"], "familiar")

    def test_atomic_failure_preserves_previous_database(self) -> None:
        self.service.upsert(payload("grammar", "before-failure"))
        before = self.store.category_path("grammar").read_bytes()
        os.environ["LEARN_ENGLISH_FAIL_BEFORE_REPLACE"] = "1"
        self.addCleanup(os.environ.pop, "LEARN_ENGLISH_FAIL_BEFORE_REPLACE", None)

        with self.assertRaisesRegex(RecordError, "injected failure"):
            self.service.upsert(payload("grammar", "after-failure"))

        self.assertEqual(self.store.category_path("grammar").read_bytes(), before)

    def test_cross_category_write_failure_rolls_back_replaced_files(self) -> None:
        self.service.upsert(payload("grammar", "rollback-target"))
        grammar_path = self.store.category_path("grammar")
        errors_path = self.store.category_path("errors")
        before_grammar = grammar_path.read_bytes()
        before_errors = errors_path.read_bytes()
        original_write_file = self.store._write_file
        call_count = 0

        def fail_second_write(*args: object, **kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("injected second-file failure")
            original_write_file(*args, **kwargs)

        with mock.patch.object(self.store, "_write_file", side_effect=fail_second_write):
            with self.assertRaisesRegex(RecordError, "all changes.*rolled back"):
                self.service.complete_review(
                    "grammar:rollback-target",
                    7,
                    [payload("errors", "rollback-error")],
                )

        self.assertEqual(grammar_path.read_bytes(), before_grammar)
        self.assertEqual(errors_path.read_bytes(), before_errors)

    def test_atomic_write_preserves_database_permissions(self) -> None:
        self.store.category_path("grammar").chmod(0o644)

        self.service.upsert(payload("grammar", "permissions"))

        self.assertEqual(self.store.category_path("grammar").stat().st_mode & 0o777, 0o644)

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

    def test_migration_refuses_existing_slim_mastered_layout(self) -> None:
        migration_root = self.root / "current-layout"
        mastered = migration_root / "mastered-learning-records"
        mastered.mkdir(parents=True)
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        write_json(
            mastered / "grammar.json",
            [
                {
                    "id": "grammar:already-mastered",
                    "title": "Already mastered",
                    "explanation": "Existing slim mastered record.",
                    "mastered_at": timestamp,
                }
            ],
        )
        migration_service = RecordService(RecordStore(migration_root))

        with self.assertRaisesRegex(RecordError, "record database already exists"):
            migration_service.migrate_legacy(dry_run=True)

    def test_record_service_does_not_commit_git_changes(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Tests"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "learning-records/grammar.json"], cwd=self.root, check=True)
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
        self.assertIn(" M learning-records/grammar.json", status)
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

    def test_cli_review_claim_can_be_released_and_completed(self) -> None:
        self.service.upsert(payload("grammar", "cli-claim"))
        environment = {
            **os.environ,
            "LEARN_ENGLISH_REPO_ROOT": str(self.root),
        }

        claimed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "next-review",
                "--claim-owner",
                "cli-test",
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        claimed_record = json.loads(claimed.stdout)["record"]
        claim = claimed_record["review_claim"]
        released = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "release-claim",
                "--id",
                claimed_record["id"],
                "--claim-owner",
                claim["owner"],
                "--claim-token",
                claim["token"],
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertTrue(json.loads(released.stdout)["released"])

        reclaimed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "next-review",
                "--claim-owner",
                "cli-test",
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        reclaimed_record = json.loads(reclaimed.stdout)["record"]
        reclaimed_claim = reclaimed_record["review_claim"]
        reviewed = subprocess.run(
            [sys.executable, str(SCRIPT), "complete-review", "--input", "-"],
            env=environment,
            input=json.dumps(
                {
                    "id": reclaimed_record["id"],
                    "score": 7,
                    "errors": [],
                    "claim_owner": reclaimed_claim["owner"],
                    "claim_token": reclaimed_claim["token"],
                }
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(reviewed.stdout)["score"], 7)

    def test_cli_search_defaults_to_all_statuses_and_accepts_filters(self) -> None:
        learning_payload = payload("grammar", "search-learning")
        familiar_payload = payload("phrases", "search-familiar")
        mastered_payload = payload("usage", "search-mastered")
        for item in (learning_payload, familiar_payload, mastered_payload):
            item["title"] = f"CLI shared marker {item['key']}"
        self.service.upsert(learning_payload)
        self.service.upsert(familiar_payload)
        self.service.complete_review("phrases:search-familiar", 8)
        self.service.upsert(mastered_payload)
        mark_mastered(self.service, "usage:search-mastered")
        environment = {
            **os.environ,
            "LEARN_ENGLISH_REPO_ROOT": str(self.root),
        }

        all_statuses = subprocess.run(
            [sys.executable, str(SCRIPT), "search", "--query", "CLI shared marker"],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        filtered = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "search",
                "--query",
                "CLI shared marker",
                "--status",
                "learning",
                "--status",
                "mastered",
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            {item["status"] for item in json.loads(all_statuses.stdout)},
            {"learning", "familiar", "mastered"},
        )
        self.assertEqual(
            {item["status"] for item in json.loads(filtered.stdout)},
            {"learning", "mastered"},
        )

    def test_cli_error_clusters_exposes_minimum_size(self) -> None:
        environment = {
            **os.environ,
            "LEARN_ENGLISH_REPO_ROOT": str(self.root),
        }

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "error-clusters",
                "--minimum-size",
                "3",
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        output = json.loads(result.stdout)
        self.assertEqual(output["cluster_count"], 0)
        self.assertEqual(output["clusters"], [])

    def test_cli_validate_returns_nonzero_for_invalid_data(self) -> None:
        invalid_root = self.root / "invalid-cli"
        invalid_store = RecordStore(invalid_root)
        invalid_store.initialize(empty_database())
        database = invalid_store.read()
        database["schema_version"] = 999
        write_json(
            invalid_store.category_path("grammar"),
            {
                "schema_version": 999,
                "revision": database["revision"],
                "category": "grammar",
                "records": {},
            },
        )
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

    def test_cli_next_review_rejects_conflicting_status_selectors(self) -> None:
        environment = {
            **os.environ,
            "LEARN_ENGLISH_REPO_ROOT": str(self.root),
        }
        conflicting_selectors = (
            ("--familiar", "--mastered"),
            ("--status", "learning", "--familiar"),
            ("--status", "mastered", "--mastered"),
        )

        for selectors in conflicting_selectors:
            with self.subTest(selectors=selectors):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "next-review", *selectors],
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("not allowed with argument", result.stderr)

    def test_cli_menu_rejects_removed_exercise_active_context(self) -> None:
        environment = {
            **os.environ,
            "LEARN_ENGLISH_REPO_ROOT": str(self.root),
        }

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "menu",
                "--context",
                "exercise-active",
            ],
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()
