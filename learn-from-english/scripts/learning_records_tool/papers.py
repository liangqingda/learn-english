"""Persistent CET paper, attempt, grading, and menu workflows."""

from __future__ import annotations

import json
import os
import random
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import CATEGORIES, RecordError, now_iso, parse_timestamp
from .store import RecordStore


PAPER_SCHEMA_VERSION = 1
PAPER_LEVELS = ("cet4", "cet6")
PAPER_STATUSES = ("unanswered", "in-progress", "completed")
ANSWER_KEYS = ("writing", *(str(number) for number in range(26, 56)), "translation")
READING_SECTIONS = {
    "section_a": (range(26, 36), 5.0),
    "section_b": (range(36, 46), 10.0),
    "section_c": (range(46, 56), 20.0),
}
PASS_SCORE = 65 * 425 / 710
CHILD_ICONS = (
    "1️⃣",
    "2️⃣",
    "3️⃣",
    "4️⃣",
    "5️⃣",
    "6️⃣",
    "7️⃣",
    "8️⃣",
    "9️⃣",
    "🔟",
    "①",
    "②",
    "③",
    "④",
    "⑤",
    "⑥",
    "⑦",
    "⑧",
    "⑨",
    "⑩",
)


def _issue(field: str | None, message: str) -> dict[str, Any]:
    return {"id": None, "field": field, "message": message}


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordError(f"{field} must not be empty")
    return value.strip()


def _number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{field} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise RecordError(f"{field} must be between {minimum:g} and {maximum:g}")
    return result


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = parse_timestamp(value)
    except (TypeError, ValueError) as exc:
        raise RecordError(f"{field} must be an ISO timestamp with timezone") from exc
    if parsed is None:
        raise RecordError(f"{field} must not be empty")
    return parsed


def _validate_question(question: Any, expected_number: int, field: str) -> None:
    if not isinstance(question, dict):
        raise RecordError(f"{field} must contain question objects")
    if question.get("number") != expected_number:
        raise RecordError(f"{field} question numbers must be {expected_number}")
    _required_text(question.get("prompt"), f"{field}[{expected_number}].prompt")
    _required_text(question.get("answer"), f"{field}[{expected_number}].answer")
    _required_text(question.get("explanation"), f"{field}[{expected_number}].explanation")
    choices = question.get("choices", [])
    if not isinstance(choices, list) or not all(isinstance(choice, str) for choice in choices):
        raise RecordError(f"{field}[{expected_number}].choices must be an array of strings")


def validate_paper(document: Any) -> list[dict[str, Any]]:
    try:
        if not isinstance(document, dict):
            raise RecordError("paper root must be an object")
        if document.get("schema_version") != PAPER_SCHEMA_VERSION:
            raise RecordError(f"schema_version must be {PAPER_SCHEMA_VERSION}")
        paper_id = _required_text(document.get("paper_id"), "paper_id")
        level = document.get("level")
        if level not in PAPER_LEVELS:
            raise RecordError("level must be cet4 or cet6")
        if not re.fullmatch(rf"{level}-\d{{8}}T\d{{6}}-[0-9a-f]{{8}}", paper_id):
            raise RecordError("paper_id format is invalid")
        theme = _required_text(document.get("theme"), "theme")
        if "\n" in theme or len(theme) > 80:
            raise RecordError("theme must be a single line no longer than 80 characters")
        created_at = _timestamp(document.get("created_at"), "created_at")
        expected_prefix = f"{level}-{created_at.strftime('%Y%m%dT%H%M%S')}-"
        if not paper_id.startswith(expected_prefix):
            raise RecordError("paper_id timestamp must match created_at")
        level_title = "CET-4" if level == "cet4" else "CET-6"
        expected_title = f"{level_title} 模拟卷｜{theme}｜{created_at.date().isoformat()}"
        if document.get("title") != expected_title:
            raise RecordError("title must match the level, theme, and creation date")

        source_ids = document.get("source_record_ids")
        if not isinstance(source_ids, list) or not all(isinstance(item, str) for item in source_ids):
            raise RecordError("source_record_ids must be an array of strings")
        if not source_ids or len(source_ids) != len(set(source_ids)):
            raise RecordError("source_record_ids must contain unique record ids")
        if any(identifier.partition(":")[0] not in CATEGORIES for identifier in source_ids):
            raise RecordError("source_record_ids contains an invalid record id")

        sections = document.get("sections")
        if not isinstance(sections, dict):
            raise RecordError("sections must be an object")
        writing = sections.get("writing")
        if not isinstance(writing, dict):
            raise RecordError("sections.writing must be an object")
        for field in ("directions", "prompt", "word_requirement", "reference_answer"):
            _required_text(writing.get(field), f"sections.writing.{field}")
        listening = sections.get("listening")
        if not isinstance(listening, dict) or listening.get("omitted") is not True:
            raise RecordError("sections.listening must mark listening as omitted")
        if listening.get("question_slots") != 25:
            raise RecordError("sections.listening.question_slots must be 25")

        reading = sections.get("reading")
        if not isinstance(reading, dict):
            raise RecordError("sections.reading must be an object")
        for section_name, (numbers, _points) in READING_SECTIONS.items():
            section = reading.get(section_name)
            if not isinstance(section, dict):
                raise RecordError(f"sections.reading.{section_name} must be an object")
            _required_text(section.get("directions"), f"sections.reading.{section_name}.directions")
            _required_text(section.get("passage"), f"sections.reading.{section_name}.passage")
            questions = section.get("questions")
            expected_numbers = list(numbers)
            if not isinstance(questions, list) or len(questions) != len(expected_numbers):
                raise RecordError(f"sections.reading.{section_name} must contain 10 questions")
            for question, number in zip(questions, expected_numbers):
                _validate_question(question, number, f"sections.reading.{section_name}.questions")

        translation = sections.get("translation")
        if not isinstance(translation, dict):
            raise RecordError("sections.translation must be an object")
        for field in ("directions", "source_text", "reference_answer"):
            _required_text(translation.get(field), f"sections.translation.{field}")

        record_map = document.get("record_map")
        if not isinstance(record_map, dict):
            raise RecordError("record_map must be an object")
        if set(record_map) != set(ANSWER_KEYS):
            raise RecordError("record_map must contain writing, Questions 26-55, and translation")
        for key, identifiers in record_map.items():
            if not isinstance(identifiers, list) or not identifiers:
                raise RecordError(f"record_map.{key} must contain at least one record id")
            if not all(isinstance(identifier, str) and identifier in source_ids for identifier in identifiers):
                raise RecordError(f"record_map.{key} must reference source_record_ids")

        attempts = document.get("attempts")
        if not isinstance(attempts, list):
            raise RecordError("attempts must be an array")
        seen_attempts: set[str] = set()
        for attempt in attempts:
            _validate_attempt(attempt, seen_attempts)
    except RecordError as exc:
        return [_issue(None, str(exc))]
    return []


def _validate_attempt(attempt: Any, seen_attempts: set[str] | None = None) -> None:
    if not isinstance(attempt, dict):
        raise RecordError("each attempt must be an object")
    attempt_id = _required_text(attempt.get("attempt_id"), "attempt_id")
    if not re.fullmatch(r"attempt-[0-9a-f]{12}", attempt_id):
        raise RecordError("attempt_id format is invalid")
    if seen_attempts is not None:
        if attempt_id in seen_attempts:
            raise RecordError("attempt_id must be unique within a paper")
        seen_attempts.add(attempt_id)
    if attempt.get("status") not in {"in_progress", "completed"}:
        raise RecordError("attempt status must be in_progress or completed")
    started_at = _timestamp(attempt.get("started_at"), "started_at")
    updated_at = _timestamp(attempt.get("updated_at"), "updated_at")
    if updated_at < started_at:
        raise RecordError("attempt updated_at cannot precede started_at")
    answers = attempt.get("answers")
    if not isinstance(answers, dict) or not all(
        isinstance(key, str) and key in ANSWER_KEYS and isinstance(value, str)
        for key, value in answers.items()
    ):
        raise RecordError("attempt answers must map valid question keys to strings")
    skipped = attempt.get("skipped")
    if (
        not isinstance(skipped, list)
        or not all(isinstance(key, str) and key in ANSWER_KEYS for key in skipped)
        or len(skipped) != len(set(skipped))
    ):
        raise RecordError("attempt skipped must contain unique valid question keys")
    if set(answers).intersection(skipped):
        raise RecordError("an answer cannot also be skipped")
    if attempt.get("status") == "completed":
        completed_at = _timestamp(attempt.get("completed_at"), "completed_at")
        if completed_at < started_at or completed_at != updated_at:
            raise RecordError("completed_at must equal updated_at and follow started_at")
        grading = attempt.get("grading")
        if not isinstance(grading, dict):
            raise RecordError("completed attempts require grading")
        for field, maximum in (
            ("reading_score", 35), ("writing_score", 15),
            ("translation_score", 15), ("total_score", 65),
        ):
            _number(grading.get(field), f"grading.{field}", 0, maximum)
        expected_total = round(
            float(grading["reading_score"])
            + float(grading["writing_score"])
            + float(grading["translation_score"]),
            2,
        )
        if abs(float(grading["total_score"]) - expected_total) > 1e-9:
            raise RecordError("grading.total_score must equal the three section scores")
        if grading.get("max_score") != 65.0:
            raise RecordError("grading.max_score must be 65")
        if grading.get("pass_score") != round(PASS_SCORE, 2):
            raise RecordError("grading.pass_score is invalid")
        if not isinstance(grading.get("passed"), bool):
            raise RecordError("grading.passed must be a boolean")
        if grading["passed"] != (expected_total + 1e-9 >= PASS_SCORE):
            raise RecordError("grading.passed does not match the no-listening threshold")
        if grading.get("official_score_equivalent") is not None:
            raise RecordError("official_score_equivalent must be null")
        _required_text(grading.get("feedback"), "grading.feedback")
    elif attempt.get("completed_at") is not None or attempt.get("grading") is not None:
        raise RecordError("in-progress attempts cannot contain completion grading")


class PaperService:
    def __init__(self, store: RecordStore):
        self.store = store
        self.paper_dir = self.store.repo_root / "cet-papers"

    def paper_path(self, paper_id: str) -> Path:
        if not re.fullmatch(r"cet[46]-\d{8}T\d{6}-[0-9a-f]{8}", paper_id):
            raise RecordError("paper_id format is invalid")
        return self.paper_dir / f"{paper_id}.json"

    def _read_path(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise RecordError(f"paper does not exist: {path.stem}")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordError(f"cannot read valid paper JSON from {path}: {exc}") from exc
        issues = validate_paper(document)
        if issues:
            raise RecordError(f"paper is invalid: {issues[0]['message']}")
        return document

    def get(self, paper_id: str, attempt_id: str | None = None) -> dict[str, Any]:
        paper = self._read_path(self.paper_path(paper_id))
        if attempt_id is None:
            return paper
        attempt = self._find_attempt(paper, attempt_id)
        return {"paper": paper, "attempt": attempt}

    def _papers(self) -> list[dict[str, Any]]:
        if not self.paper_dir.exists():
            return []
        return [self._read_path(path) for path in sorted(self.paper_dir.glob("cet[46]-*.json"))]

    def validate(self) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        if not self.paper_dir.exists():
            return {"valid": True, "paper_count": 0, "issue_count": 0, "issues": []}
        paths = sorted(self.paper_dir.glob("*.json"))
        for path in paths:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                issues.append({"paper_id": path.stem, "field": None, "message": str(exc)})
                continue
            paper_issues = validate_paper(document)
            if isinstance(document, dict) and document.get("paper_id") != path.stem:
                paper_issues = [
                    _issue("paper_id", "paper_id must match the JSON filename"),
                    *paper_issues,
                ]
            issues.extend({"paper_id": path.stem, **issue} for issue in paper_issues)
        return {
            "valid": not issues,
            "paper_count": len(paths),
            "issue_count": len(issues),
            "issues": issues,
        }

    @staticmethod
    def _summary(
        paper: dict[str, Any], attempt: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        result = {
            "paper_id": paper["paper_id"],
            "title": paper["title"],
            "level": paper["level"],
            "created_at": paper["created_at"],
            "attempt_count": len(paper["attempts"]),
            "completed_attempt_count": sum(
                item["status"] == "completed" for item in paper["attempts"]
            ),
        }
        if attempt is not None:
            result.update(
                attempt_id=attempt["attempt_id"],
                attempt_status=attempt["status"],
                answered_count=len(attempt["answers"]),
                skipped_count=len(attempt["skipped"]),
                updated_at=attempt["updated_at"],
            )
        return result

    def list(
        self, status: str | None = None, *, randomize: bool = False
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        if status is not None and status not in PAPER_STATUSES:
            raise RecordError(f"invalid paper status: {status}")
        if randomize and status != "completed":
            raise RecordError("random paper selection requires status completed")
        results: list[dict[str, Any]] = []
        for paper in self._papers():
            if status in {None, "unanswered"} and not paper["attempts"]:
                results.append(self._summary(paper))
            if status in {None, "in-progress"}:
                results.extend(
                    self._summary(paper, attempt)
                    for attempt in paper["attempts"]
                    if attempt["status"] == "in_progress"
                )
            if status in {None, "completed"} and any(
                attempt["status"] == "completed" for attempt in paper["attempts"]
            ):
                results.append(self._summary(paper))
        results.sort(
            key=lambda item: (
                item.get("updated_at", item["created_at"]),
                item["paper_id"],
            ),
            reverse=True,
        )
        if randomize:
            return random.choice(results) if results else None
        return results

    @staticmethod
    def _paper_id(level: str, timestamp: datetime) -> str:
        return f"{level}-{timestamp.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"

    def create(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RecordError("paper-create input must be an object")
        level = payload.get("level")
        if level not in PAPER_LEVELS:
            raise RecordError("level must be cet4 or cet6")
        theme = _required_text(payload.get("theme"), "theme")
        created_at = now_iso()
        timestamp = parse_timestamp(created_at)
        assert timestamp is not None
        paper_id = self._paper_id(level, timestamp)
        level_title = "CET-4" if level == "cet4" else "CET-6"
        document = {
            "schema_version": PAPER_SCHEMA_VERSION,
            "paper_id": paper_id,
            "level": level,
            "title": f"{level_title} 模拟卷｜{theme}｜{timestamp.date().isoformat()}",
            "theme": theme,
            "created_at": created_at,
            "source_record_ids": payload.get("source_record_ids"),
            "sections": payload.get("sections"),
            "record_map": payload.get("record_map"),
            "attempts": [],
        }
        issues = validate_paper(document)
        if issues:
            raise RecordError(issues[0]["message"])
        path = self.paper_path(paper_id)
        with self.store._exclusive_lock():
            if path.exists():
                raise RecordError(f"paper already exists: {paper_id}")
            records = self.store._load()["records"]
            invalid_sources = [
                identifier
                for identifier in document["source_record_ids"]
                if identifier not in records or records[identifier]["status"] != "mastered"
            ]
            if invalid_sources:
                raise RecordError(
                    "source_record_ids must reference mastered records: "
                    + ", ".join(invalid_sources)
                )
            self.store._write_file(path, document, validate=validate_paper)
        return self._summary(document)

    @staticmethod
    def _find_attempt(paper: dict[str, Any], attempt_id: str) -> dict[str, Any]:
        for attempt in paper["attempts"]:
            if attempt["attempt_id"] == attempt_id:
                return attempt
        raise RecordError(f"attempt does not exist: {attempt_id}")

    @staticmethod
    def _validate_submission(
        payload: Any,
    ) -> tuple[str, str | None, dict[str, str], list[str]]:
        if not isinstance(payload, dict):
            raise RecordError("paper-submit input must be an object")
        paper_id = _required_text(payload.get("paper_id"), "paper_id")
        attempt_id = payload.get("attempt_id")
        if attempt_id is not None and not isinstance(attempt_id, str):
            raise RecordError("attempt_id must be a string")
        answers = payload.get("answers", {})
        if not isinstance(answers, dict) or not all(
            isinstance(key, str) and key in ANSWER_KEYS and isinstance(value, str) and value.strip()
            for key, value in answers.items()
        ):
            raise RecordError("answers must map valid question keys to non-empty strings")
        skipped = payload.get("skipped", [])
        if (
            not isinstance(skipped, list)
            or not all(isinstance(key, str) and key in ANSWER_KEYS for key in skipped)
            or len(skipped) != len(set(skipped))
        ):
            raise RecordError("skipped must contain unique valid question keys")
        if set(answers).intersection(skipped):
            raise RecordError("submitted answers cannot also be skipped")
        if not answers and not skipped:
            raise RecordError("paper-submit requires at least one answer or skipped item")
        return (
            paper_id,
            attempt_id,
            {key: value.strip() for key, value in answers.items()},
            skipped,
        )

    def submit(self, payload: Any) -> dict[str, Any]:
        paper_id, attempt_id, answers, skipped = self._validate_submission(payload)
        path = self.paper_path(paper_id)
        with self.store._exclusive_lock():
            paper = self._read_path(path)
            timestamp = now_iso()
            if attempt_id is None:
                attempt = {
                    "attempt_id": f"attempt-{uuid.uuid4().hex[:12]}",
                    "status": "in_progress",
                    "started_at": timestamp,
                    "updated_at": timestamp,
                    "completed_at": None,
                    "answers": {},
                    "skipped": [],
                    "grading": None,
                }
                paper["attempts"].append(attempt)
            else:
                attempt = self._find_attempt(paper, attempt_id)
                if attempt["status"] != "in_progress":
                    raise RecordError("completed attempts cannot accept more answers")
            attempt["answers"].update(answers)
            attempt["skipped"] = sorted(
                (set(attempt["skipped"]) | set(skipped)) - set(answers),
                key=ANSWER_KEYS.index,
            )
            for key in skipped:
                attempt["answers"].pop(key, None)
            attempt["updated_at"] = timestamp
            self.store._write_file(path, paper, validate=validate_paper)
        return self._summary(paper, attempt)

    @staticmethod
    def _reading_answers(paper: dict[str, Any]) -> dict[str, str]:
        return {
            str(question["number"]): question["answer"]
            for section_name in READING_SECTIONS
            for question in paper["sections"]["reading"][section_name]["questions"]
        }

    @classmethod
    def _reading_score(cls, paper: dict[str, Any], attempt: dict[str, Any]) -> float:
        expected = cls._reading_answers(paper)
        score = 0.0
        for section_name, (numbers, points) in READING_SECTIONS.items():
            per_question = points / 10
            for number in numbers:
                answer = attempt["answers"].get(str(number), "").strip().casefold()
                if answer == expected[str(number)].strip().casefold():
                    score += per_question
        return round(score, 2)

    def complete(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RecordError("paper-complete input must be an object")
        paper_id = _required_text(payload.get("paper_id"), "paper_id")
        attempt_id = _required_text(payload.get("attempt_id"), "attempt_id")
        writing_score = _number(payload.get("writing_score"), "writing_score", 0, 15)
        translation_score = _number(
            payload.get("translation_score"), "translation_score", 0, 15
        )
        feedback = _required_text(payload.get("feedback"), "feedback")
        errors = payload.get("errors", [])
        if not isinstance(errors, list):
            raise RecordError("errors must be an array")

        path = self.paper_path(paper_id)
        with self.store._exclusive_lock():
            database = self.store._load()
            paper = self._read_path(path)
            attempt = self._find_attempt(paper, attempt_id)
            if attempt["status"] != "in_progress":
                raise RecordError("attempt is already completed")
            covered = set(attempt["answers"]) | set(attempt["skipped"])
            if covered != set(ANSWER_KEYS):
                missing = [key for key in ANSWER_KEYS if key not in covered]
                raise RecordError(f"attempt is incomplete; missing: {', '.join(missing)}")
            if "writing" in attempt["skipped"] and writing_score != 0:
                raise RecordError("skipped writing requires a writing_score of 0")
            if "translation" in attempt["skipped"] and translation_score != 0:
                raise RecordError("skipped translation requires a translation_score of 0")

            from .service import RecordService

            timestamp = now_iso()
            error_results = [
                RecordService._upsert_error(database["records"], error, timestamp)
                for error in errors
            ]
            reading_score = self._reading_score(paper, attempt)
            total_score = round(reading_score + writing_score + translation_score, 2)
            passed = total_score + 1e-9 >= PASS_SCORE
            attempt.update(
                status="completed",
                updated_at=timestamp,
                completed_at=timestamp,
                grading={
                    "reading_score": reading_score,
                    "writing_score": writing_score,
                    "translation_score": translation_score,
                    "total_score": total_score,
                    "max_score": 65.0,
                    "pass_score": round(PASS_SCORE, 2),
                    "passed": passed,
                    "official_score_equivalent": None,
                    "feedback": feedback,
                },
            )
            issues = validate_paper(paper)
            if issues:
                raise RecordError(issues[0]["message"])
            database["revision"] += 1
            database["records"] = dict(sorted(database["records"].items()))

            record_paths = [
                path_value
                for category in CATEGORIES
                for path_value in (
                    self.store.category_path(category),
                    self.store.mastered_category_path(category),
                )
            ]
            snapshots = {
                target: (
                    target.read_bytes() if target.exists() else None,
                    target.stat().st_mode & 0o777 if target.exists() else None,
                )
                for target in [*record_paths, path]
            }
            try:
                self.store._write(database)
                if os.environ.get("LEARN_ENGLISH_FAIL_PAPER_COMPLETE") == "1":
                    raise RecordError("injected paper completion failure")
                self.store._write_file(path, paper, validate=validate_paper)
            except Exception as write_error:
                rollback_errors = []
                for target, (content, mode) in snapshots.items():
                    try:
                        self.store._restore_file(target, content, mode)
                    except Exception as rollback_error:
                        rollback_errors.append(f"{target}: {rollback_error}")
                if rollback_errors:
                    raise RecordError(
                        f"paper completion failed ({write_error}); rollback also failed: "
                        + "; ".join(rollback_errors)
                    ) from write_error
                raise RecordError(
                    f"paper completion failed; all changes from this operation were rolled back: {write_error}"
                ) from write_error
        return {
            "paper_id": paper_id,
            "title": paper["title"],
            "level": paper["level"],
            "attempt_id": attempt_id,
            **attempt["grading"],
            "errors": error_results,
        }

    def menu_options(self) -> list[dict[str, Any]]:
        unanswered = self.list("unanswered")
        in_progress = self.list("in-progress")
        completed = self.list("completed")
        assert isinstance(unanswered, list)
        assert isinstance(in_progress, list)
        assert isinstance(completed, list)
        options: list[dict[str, Any]] = []
        if unanswered:
            options.append(
                {
                    "id": "historical-unanswered-papers",
                    "icon": "📄",
                    "label": "历史未作答试卷",
                    "group": "popular",
                    "kind": "paper-history",
                    "count": len(unanswered),
                    "children": [
                        {
                            "id": f"unanswered-paper:{paper['paper_id']}",
                            "icon": CHILD_ICONS[index % len(CHILD_ICONS)],
                            "label": paper["title"],
                            "group": "popular",
                            "kind": "historical-unanswered-paper",
                            "parent_id": "historical-unanswered-papers",
                            "action": {"command": "paper-get", "paper_id": paper["paper_id"]},
                        }
                        for index, paper in enumerate(unanswered)
                    ],
                }
            )
        if in_progress:
            options.append(
                {
                    "id": "in-progress-papers",
                    "icon": "⏳",
                    "label": "继续未完成试卷",
                    "group": "popular",
                    "kind": "paper-history",
                    "count": len(in_progress),
                    "children": [
                        {
                            "id": f"continue-paper:{paper['paper_id']}:{paper['attempt_id']}",
                            "icon": CHILD_ICONS[index % len(CHILD_ICONS)],
                            "label": paper["title"],
                            "group": "popular",
                            "kind": "continue-paper-attempt",
                            "parent_id": "in-progress-papers",
                            "action": {
                                "command": "paper-get",
                                "paper_id": paper["paper_id"],
                                "attempt_id": paper["attempt_id"],
                            },
                        }
                        for index, paper in enumerate(in_progress)
                    ],
                }
            )
        if completed:
            options.append(
                {
                    "id": "retry-random-paper",
                    "icon": "🎲",
                    "label": "再次作答历史试卷（随机）",
                    "group": "popular",
                    "kind": "retry-random-paper",
                    "count": len(completed),
                    "action": {"command": "paper-list", "status": "completed", "random": True},
                }
            )
        return options
