from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "learning_records.py"
SPEC = importlib.util.spec_from_file_location("learning_records", SCRIPT)
assert SPEC and SPEC.loader
records = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(records)


class LearningRecordsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        records.RECORDS_DIR = root / "learning-records"
        records.FAMILIAR_RECORDS_DIR = root / "familiar-learning-records"
        records.MASTERED_RECORDS_DIR = root / "mastered-learning-records"
        records.RECORDS_DIR.mkdir()
        records.FAMILIAR_RECORDS_DIR.mkdir()
        records.MASTERED_RECORDS_DIR.mkdir()

    @staticmethod
    def args(category: str, key: str | None = None) -> argparse.Namespace:
        return argparse.Namespace(
            category=category,
            key=key,
            title=f"{category} title",
            explanation=f"{category} explanation",
            source=f"{category} source",
            example=f"{category} example",
            tag=["core", "Core", "review"],
        )

    def test_upserts_all_categories_and_initializes_missing_files(self) -> None:
        for category in records.CATEGORIES:
            item = records.upsert(self.args(category))
            self.assertEqual(item["id"], f"{category}:{category}-title")
            self.assertTrue(item["created"])
            self.assertEqual(item["location"], "learning-records")
            self.assertEqual(item["learned_count"], 1)
            self.assertEqual(item["mastery_score"], 0)
            self.assertTrue((records.RECORDS_DIR / f"{category}.json").exists())

    def test_duplicate_key_in_learning_records_is_skipped(self) -> None:
        first_args = self.args("grammar", "present perfect experience")
        first_args.title = "现在完成时表示延续"
        first_args.explanation = "表示过去开始并持续到现在的状态或动作。"
        first_args.source = "I've worked here since 2020."
        first_args.example = "She has lived here for five years."
        first = records.upsert(first_args)
        second_args = self.args("grammar", "present-perfect-experience")
        second_args.explanation = "updated explanation"
        second = records.upsert(second_args)

        document = records.load_document("grammar")
        self.assertEqual(len(document["items"]), 1)
        self.assertEqual(first["id"], second["id"])
        self.assertFalse(second["created"])
        self.assertEqual(second["location"], "learning-records")
        self.assertEqual(second["learned_count"], 1)
        self.assertEqual(second["explanation"], first["explanation"])
        self.assertEqual(second["tags"], first["tags"])

    def test_duplicate_key_in_familiar_records_is_skipped(self) -> None:
        args = self.args("grammar", "reviewed rule")
        item = records.upsert(args)
        document = records.load_document("grammar")
        document["items"].remove(document["items"][0])
        records.write_document("grammar", document)
        records.archive_record("grammar", {
            key: value
            for key, value in item.items()
            if key not in {"created", "location"}
        })

        duplicate = records.upsert(args)

        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["location"], "familiar-learning-records")
        self.assertEqual(records.load_document("grammar")["items"], [])
        self.assertEqual(len(records.load_familiar_document("grammar")["items"]), 1)

    def test_review_scores_records_and_lists_low_scores_first(self) -> None:
        records.upsert(self.args("grammar", "low score"))
        records.upsert(self.args("grammar", "partial score"))

        reviewed = records.review_record(
            argparse.Namespace(category="grammar", key="partial score", score=7)
        )

        self.assertFalse(reviewed["archived"])
        self.assertEqual(reviewed["mastery_score"], 7)
        self.assertEqual(reviewed["review_count"], 1)
        self.assertEqual(reviewed["high_score_streak"], 0)
        listed = records.list_records(argparse.Namespace(category="grammar"))
        self.assertEqual([item["id"] for item in listed], [
            "grammar:low-score",
            "grammar:partial-score",
        ])

    def test_single_mastery_score_archives_record(self) -> None:
        records.upsert(self.args("phrases", "mastered phrase"))

        result = records.review_record(
            argparse.Namespace(category="phrases", key="mastered phrase", score=8)
        )
        self.assertTrue(result["archived"])
        self.assertFalse(result["deleted"])
        self.assertEqual(result["high_score_streak"], 1)
        self.assertEqual(records.load_document("phrases")["items"], [])
        familiar = records.load_familiar_document("phrases")
        self.assertEqual([item["id"] for item in familiar["items"]], [
            "phrases:mastered-phrase"
        ])
        self.assertEqual(familiar["items"][0]["mastery_score"], 8)
        self.assertEqual(familiar["items"][0]["review_count"], 1)

    def test_perfect_review_score_moves_concise_record_to_mastered(self) -> None:
        records.upsert(self.args("grammar", "perfect answer"))

        result = records.review_record(
            argparse.Namespace(category="grammar", key="perfect answer", score=10)
        )

        self.assertFalse(result["deleted"])
        self.assertFalse(result["archived"])
        self.assertTrue(result["mastered"])
        self.assertEqual(result["mastery_score"], 10)
        self.assertEqual(result["review_count"], 1)
        self.assertEqual(records.load_document("grammar")["items"], [])
        self.assertEqual(records.load_familiar_document("grammar")["items"], [])
        mastered = records.load_mastered_document("grammar")
        self.assertEqual([item["id"] for item in mastered["items"]], [
            "grammar:perfect-answer"
        ])
        self.assertEqual(
            list(mastered["items"][0]),
            ["id", "title", "summary", "mastered_at"],
        )
        self.assertEqual(mastered["items"][0]["title"], "grammar title")
        self.assertEqual(mastered["items"][0]["summary"], "grammar explanation")

    def test_low_score_resets_high_score_streak(self) -> None:
        records.upsert(self.args("usage", "polite request"))
        document = records.load_document("usage")
        document["items"][0]["high_score_streak"] = 2
        records.write_document("usage", document)

        result = records.review_record(
            argparse.Namespace(category="usage", key="polite request", score=7)
        )

        self.assertFalse(result["archived"])
        self.assertEqual(result["high_score_streak"], 0)
        self.assertEqual(result["review_count"], 1)

    def test_review_rejects_invalid_score_and_missing_record(self) -> None:
        records.upsert(self.args("vocabulary", "known word"))
        with self.assertRaisesRegex(records.RecordError, "between 0 and 10"):
            records.review_record(
                argparse.Namespace(category="vocabulary", key="known word", score=11)
            )
        with self.assertRaisesRegex(records.RecordError, "record does not exist"):
            records.review_record(
                argparse.Namespace(category="vocabulary", key="missing", score=5)
            )

    def test_familiar_records_are_listed_by_oldest_review_time_across_categories(self) -> None:
        grammar = records.upsert(self.args("grammar", "later reviewed"))
        phrase = records.upsert(self.args("phrases", "never reviewed"))
        grammar_item = {key: value for key, value in grammar.items() if key not in {"created", "location"}}
        phrase_item = {key: value for key, value in phrase.items() if key not in {"created", "location"}}
        grammar_item["last_reviewed_at"] = "2026-07-01T12:00:00+08:00"
        for category, item in (("grammar", grammar_item), ("phrases", phrase_item)):
            document = records.load_document(category)
            document["items"].clear()
            records.write_document(category, document)
            records.archive_record(category, item)

        listed = records.list_familiar_records(argparse.Namespace())

        self.assertEqual(
            [item["id"] for item in listed],
            ["phrases:never-reviewed", "grammar:later-reviewed"],
        )
        self.assertEqual(listed[0]["category"], "phrases")

    def test_low_familiar_review_score_moves_record_back_to_learning(self) -> None:
        item = records.upsert(self.args("grammar", "rusty rule"))
        archived = {key: value for key, value in item.items() if key not in {"created", "location"}}
        document = records.load_document("grammar")
        document["items"].clear()
        records.write_document("grammar", document)
        records.archive_record("grammar", archived)

        result = records.review_familiar_record(
            argparse.Namespace(category="grammar", key="rusty rule", score=7)
        )

        self.assertTrue(result["moved_to_learning_records"])
        self.assertEqual(result["mastery_score"], 7)
        self.assertEqual(result["review_count"], 1)
        self.assertEqual(result["high_score_streak"], 0)
        self.assertIsNotNone(result["last_reviewed_at"])
        self.assertEqual(records.load_familiar_document("grammar")["items"], [])
        self.assertEqual(records.load_document("grammar")["items"][0]["id"], "grammar:rusty-rule")

    def test_high_familiar_review_score_updates_time_and_keeps_record_familiar(self) -> None:
        item = records.upsert(self.args("phrases", "solid phrase"))
        archived = {key: value for key, value in item.items() if key not in {"created", "location"}}
        archived["last_reviewed_at"] = "2026-01-01T00:00:00+08:00"
        document = records.load_document("phrases")
        document["items"].clear()
        records.write_document("phrases", document)
        records.archive_record("phrases", archived)

        result = records.review_familiar_record(
            argparse.Namespace(category="phrases", key="solid phrase", score=8)
        )

        self.assertFalse(result["moved_to_learning_records"])
        self.assertEqual(result["mastery_score"], 8)
        self.assertEqual(result["review_count"], 1)
        self.assertNotEqual(result["last_reviewed_at"], "2026-01-01T00:00:00+08:00")
        self.assertEqual(records.load_document("phrases")["items"], [])
        self.assertEqual(len(records.load_familiar_document("phrases")["items"]), 1)

    def test_perfect_familiar_review_score_moves_concise_record_to_mastered(self) -> None:
        item = records.upsert(self.args("errors", "settled error"))
        archived = {key: value for key, value in item.items() if key not in {"created", "location"}}
        document = records.load_document("errors")
        document["items"].clear()
        records.write_document("errors", document)
        records.archive_record("errors", archived)

        result = records.review_familiar_record(
            argparse.Namespace(category="errors", key="settled error", score=10)
        )

        self.assertFalse(result["deleted"])
        self.assertFalse(result["moved_to_learning_records"])
        self.assertTrue(result["mastered"])
        self.assertEqual(result["mastery_score"], 10)
        self.assertEqual(result["review_count"], 1)
        self.assertEqual(records.load_familiar_document("errors")["items"], [])
        self.assertEqual(records.load_document("errors")["items"], [])
        mastered = records.load_mastered_document("errors")
        self.assertEqual([item["id"] for item in mastered["items"]], [
            "errors:settled-error"
        ])
        self.assertEqual(mastered["items"][0]["summary"], "errors explanation")

    def test_familiar_review_rejects_invalid_score_and_missing_record(self) -> None:
        with self.assertRaisesRegex(records.RecordError, "between 0 and 10"):
            records.review_familiar_record(
                argparse.Namespace(category="usage", key="known usage", score=-1)
            )
        with self.assertRaisesRegex(records.RecordError, "familiar record does not exist"):
            records.review_familiar_record(
                argparse.Namespace(category="usage", key="missing", score=8)
            )

    def test_searches_across_categories(self) -> None:
        for category in records.CATEGORIES:
            records.upsert(self.args(category))

        matches = records.search_records(argparse.Namespace(query="grammar explanation"))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["category"], "grammar")

    def test_search_can_include_familiar_records(self) -> None:
        item = records.upsert(self.args("grammar", "archived grammar"))
        archived = {
            key: value
            for key, value in item.items()
            if key not in {"created", "location"}
        }
        document = records.load_document("grammar")
        document["items"].clear()
        records.write_document("grammar", document)
        records.archive_record("grammar", archived)

        normal_matches = records.search_records(
            argparse.Namespace(query="grammar explanation", include_familiar=False)
        )
        familiar_matches = records.search_records(
            argparse.Namespace(query="grammar explanation", include_familiar=True)
        )

        self.assertEqual(normal_matches, [])
        self.assertEqual(len(familiar_matches), 1)
        self.assertEqual(familiar_matches[0]["location"], "familiar-learning-records")

    def test_duplicate_key_in_mastered_records_is_skipped(self) -> None:
        args = self.args("grammar", "settled rule")
        item = records.upsert(args)
        records.review_record(
            argparse.Namespace(category="grammar", key="settled rule", score=10)
        )

        duplicate = records.upsert(args)

        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["location"], "mastered-learning-records")
        self.assertEqual(records.load_document("grammar")["items"], [])
        self.assertEqual(len(records.load_mastered_document("grammar")["items"]), 1)

    def test_search_can_include_mastered_records(self) -> None:
        records.upsert(self.args("usage", "mastered usage"))
        records.review_record(
            argparse.Namespace(category="usage", key="mastered usage", score=10)
        )

        normal_matches = records.search_records(
            argparse.Namespace(
                query="usage explanation",
                include_familiar=False,
                include_mastered=False,
            )
        )
        mastered_matches = records.search_records(
            argparse.Namespace(
                query="usage explanation",
                include_familiar=False,
                include_mastered=True,
            )
        )

        self.assertEqual(normal_matches, [])
        self.assertEqual(len(mastered_matches), 1)
        self.assertEqual(mastered_matches[0]["location"], "mastered-learning-records")

    def test_summarizes_category_counts_without_returning_items(self) -> None:
        for category in records.CATEGORIES:
            records.upsert(self.args(category))
        records.upsert(self.args("errors", "second error"))

        self.assertEqual(
            records.summarize_records(argparse.Namespace()),
            [
                {"category": "vocabulary", "count": 1},
                {"category": "phrases", "count": 1},
                {"category": "grammar", "count": 1},
                {"category": "usage", "count": 1},
                {"category": "errors", "count": 2},
            ],
        )

    def test_summary_can_include_familiar_counts(self) -> None:
        item = records.upsert(self.args("phrases", "archived phrase"))
        archived = {
            key: value
            for key, value in item.items()
            if key not in {"created", "location"}
        }
        document = records.load_document("phrases")
        document["items"].clear()
        records.write_document("phrases", document)
        records.archive_record("phrases", archived)

        summary = records.summarize_records(argparse.Namespace(include_familiar=True))

        phrases = next(item for item in summary if item["category"] == "phrases")
        self.assertEqual(phrases["count"], 0)
        self.assertEqual(phrases["familiar_count"], 1)
        self.assertEqual(phrases["total_count"], 1)

    def test_summary_can_include_mastered_counts(self) -> None:
        records.upsert(self.args("vocabulary", "mastered word"))
        records.review_record(
            argparse.Namespace(category="vocabulary", key="mastered word", score=10)
        )

        summary = records.summarize_records(
            argparse.Namespace(include_familiar=True, include_mastered=True)
        )

        vocabulary = next(item for item in summary if item["category"] == "vocabulary")
        self.assertEqual(vocabulary["count"], 0)
        self.assertEqual(vocabulary["familiar_count"], 0)
        self.assertEqual(vocabulary["mastered_count"], 1)
        self.assertEqual(vocabulary["total_count"], 1)

    def test_lists_mastered_records_across_categories(self) -> None:
        records.upsert(self.args("vocabulary", "settled word"))
        records.upsert(self.args("grammar", "settled rule"))
        records.review_record(
            argparse.Namespace(category="vocabulary", key="settled word", score=10)
        )
        records.review_record(
            argparse.Namespace(category="grammar", key="settled rule", score=10)
        )

        mastered = records.list_mastered_records(argparse.Namespace())

        self.assertEqual(
            {item["id"] for item in mastered},
            {"vocabulary:settled-word", "grammar:settled-rule"},
        )
        self.assertTrue(all(item["location"] == "mastered-learning-records" for item in mastered))
        self.assertEqual({item["category"] for item in mastered}, {"vocabulary", "grammar"})

    def test_menu_merges_paths_and_includes_fixed_options(self) -> None:
        records.upsert(self.args("errors", "unstable error"))
        records.upsert(self.args("vocabulary", "useful word"))
        records.upsert(self.args("usage", "polite tone"))
        records.upsert(self.args("grammar", "mastered grammar"))
        records.review_record(
            argparse.Namespace(category="grammar", key="mastered grammar", score=10)
        )

        menu = records.build_review_menu(argparse.Namespace())

        self.assertEqual(menu["state"], "ready")
        self.assertEqual(menu["regular_total"], 3)
        self.assertEqual(menu["mastered_total"], 1)
        self.assertLessEqual(len(menu["options"]), 5)
        option_ids = [option["id"] for option in menu["options"]]
        self.assertIn("cet-practice", option_ids)
        self.assertIn("mastered-cet-paper", option_ids)
        self.assertIn("scenario-dialogue", option_ids)
        self.assertIn("familiar-review", option_ids)
        mastered_paper = next(option for option in menu["options"] if option["id"] == "mastered-cet-paper")
        self.assertNotIn("count", mastered_paper)
        mixed = next(option for option in menu["options"] if option["id"].startswith("mixed-"))
        selected = records.next_review_record(
            argparse.Namespace(category=[], path=mixed["id"], familiar=False, random=False)
        )
        self.assertIn(selected["record"]["category"], mixed["categories"])

    def test_menu_can_open_from_mastered_records_only(self) -> None:
        records.upsert(self.args("usage", "mastered usage"))
        records.review_record(
            argparse.Namespace(category="usage", key="mastered usage", score=10)
        )

        menu = records.build_review_menu(argparse.Namespace())

        self.assertEqual(menu["state"], "ready")
        self.assertEqual(menu["regular_total"], 0)
        self.assertEqual(menu["familiar_count"], 0)
        self.assertEqual(menu["mastered_total"], 1)
        self.assertEqual(
            [option["id"] for option in menu["options"]],
            [
                "cet-practice",
                "mastered-cet-paper",
                "scenario-dialogue",
                "familiar-review",
            ],
        )

    def test_empty_menu_uses_general_options(self) -> None:
        menu = records.build_review_menu(argparse.Namespace())

        self.assertEqual(menu["state"], "empty")
        self.assertEqual(menu["regular_total"], 0)
        self.assertEqual(menu["mastered_total"], 0)
        self.assertEqual([option["id"] for option in menu["options"]], [
            "status",
            "cet-practice",
            "scenario-dialogue",
        ])

    def test_next_review_selects_lowest_score_or_oldest_familiar(self) -> None:
        records.upsert(self.args("grammar", "low score"))
        records.upsert(self.args("grammar", "high score"))
        records.review_record(
            argparse.Namespace(category="grammar", key="high score", score=9)
        )
        next_normal = records.next_review_record(
            argparse.Namespace(category=["grammar"], path=None, familiar=False, random=False)
        )

        self.assertEqual(next_normal["record"]["id"], "grammar:low-score")

        grammar = records.upsert(self.args("grammar", "later familiar"))
        phrase = records.upsert(self.args("phrases", "older familiar"))
        grammar_item = {
            key: value
            for key, value in grammar.items()
            if key not in {"created", "location"}
        }
        phrase_item = {
            key: value
            for key, value in phrase.items()
            if key not in {"created", "location"}
        }
        grammar_item["last_reviewed_at"] = "2026-07-01T12:00:00+08:00"
        for category, item in (("grammar", grammar_item), ("phrases", phrase_item)):
            document = records.load_document(category)
            document["items"] = [
                candidate
                for candidate in document["items"]
                if candidate["id"] != item["id"]
            ]
            records.write_document(category, document)
            records.archive_record(category, item)

        next_familiar = records.next_review_record(
            argparse.Namespace(category=[], path=None, familiar=True, random=False)
        )

        self.assertEqual(next_familiar["record"]["id"], "phrases:older-familiar")

    def test_next_review_can_select_random_learning_record(self) -> None:
        records.upsert(self.args("grammar", "first rule"))
        records.upsert(self.args("phrases", "second phrase"))

        selected = records.next_review_record(
            argparse.Namespace(
                category=["grammar", "phrases"],
                path=None,
                familiar=False,
                random=True,
            )
        )

        self.assertIn(
            selected["record"]["id"],
            {"grammar:first-rule", "phrases:second-phrase"},
        )

    def test_invalid_category_and_required_fields_are_rejected(self) -> None:
        with self.assertRaises(records.RecordError):
            records.category_path("other")

        args = self.args("vocabulary")
        args.title = " "
        with self.assertRaisesRegex(records.RecordError, "title must not be empty"):
            records.upsert(args)

    def test_corrupt_json_is_not_overwritten(self) -> None:
        path = records.category_path("phrases")
        path.write_text("not json\n", encoding="utf-8")

        with self.assertRaisesRegex(records.RecordError, "cannot read valid JSON"):
            records.upsert(self.args("phrases"))
        self.assertEqual(path.read_text(encoding="utf-8"), "not json\n")

    def test_validate_reports_missing_fields_and_migrate_fills_defaults(self) -> None:
        records.upsert(self.args("phrases", "legacy phrase"))
        document = records.load_document("phrases")
        for field in (
            "mastery_score",
            "review_count",
            "high_score_streak",
            "last_reviewed_at",
        ):
            del document["items"][0][field]
        records.write_document("phrases", document)

        validation = records.validate_records(argparse.Namespace())
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["issue_count"], 4)

        migration = records.migrate_records(argparse.Namespace(dry_run=False))
        self.assertEqual(migration["changed"][0]["ids"], ["phrases:legacy-phrase"])
        migrated = records.load_document("phrases")["items"][0]
        self.assertEqual(migrated["mastery_score"], 0)
        self.assertEqual(migrated["review_count"], 0)
        self.assertEqual(migrated["high_score_streak"], 0)
        self.assertIsNone(migrated["last_reviewed_at"])
        self.assertTrue(records.validate_records(argparse.Namespace())["valid"])

    def test_json_is_utf8_indented_and_has_stable_fields(self) -> None:
        args = self.args("vocabulary", "context meaning")
        args.title = "语境词义"
        records.upsert(args)

        path = records.category_path("vocabulary")
        text = path.read_text(encoding="utf-8")
        document = json.loads(text)
        self.assertIn('\n  "items": [', text)
        self.assertEqual(
            list(document["items"][0]),
            [
                "id",
                "title",
                "explanation",
                "source",
                "example",
                "tags",
                "first_learned_at",
                "last_learned_at",
                "learned_count",
                "mastery_score",
                "review_count",
                "high_score_streak",
                "last_reviewed_at",
            ],
        )


if __name__ == "__main__":
    unittest.main()
