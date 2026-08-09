"""Persistent exam paper, attempt, grading, and menu workflows."""

from __future__ import annotations

import json
import math
import os
import random
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import CATEGORIES, RecordError, now_iso, parse_timestamp
from .store import RecordStore


PAPER_SCHEMA_VERSION = 2
PAPER_STATUSES = ("unanswered", "in-progress", "completed")
CONVERSION_METHODS = ("linear", "identity")
CET_FORMAT = "cet-no-listening-v1"
CET_ANSWER_KEYS = (
    "writing",
    *(str(number) for number in range(26, 56)),
    "translation",
)
CET_READING_SECTIONS = {
    "section_a": (range(26, 36), 5.0),
    "section_b": (range(36, 46), 10.0),
    "section_c": (range(46, 56), 20.0),
}
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


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordError(f"{field} must be a number")
    result = float(value)
    if result <= 0:
        raise RecordError(f"{field} must be positive")
    return result


def _timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = parse_timestamp(value)
    except (TypeError, ValueError) as exc:
        raise RecordError(f"{field} must be an ISO timestamp with timezone") from exc
    if parsed is None:
        raise RecordError(f"{field} must not be empty")
    return parsed


def _slug(value: Any, field: str) -> str:
    result = _required_text(value, field)
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", result):
        raise RecordError(f"{field} must be a lowercase hyphenated slug")
    return result


def _answer_keys(document: dict[str, Any]) -> tuple[str, ...]:
    keys = document.get("answer_keys")
    if (
        not isinstance(keys, list)
        or not keys
        or not all(isinstance(key, str) and key.strip() for key in keys)
        or len(keys) != len(set(keys))
    ):
        raise RecordError("answer_keys must contain unique non-empty strings")
    return tuple(keys)


def _validate_cet_question(question: Any, expected_number: int, field: str) -> None:
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


def _validate_cet_format(document: dict[str, Any]) -> None:
    exam_type = document["exam_type"]
    if exam_type not in {"cet4", "cet6"}:
        raise RecordError(f"{CET_FORMAT} requires exam_type cet4 or cet6")
    expected_name = "CET-4" if exam_type == "cet4" else "CET-6"
    if document["exam_name"] != expected_name:
        raise RecordError(f"{CET_FORMAT} exam_name must be {expected_name}")
    if tuple(document["answer_keys"]) != CET_ANSWER_KEYS:
        raise RecordError(f"{CET_FORMAT} requires writing, Questions 26-55, and translation")

    sections = document["sections"]
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
    objective_items = document["objective_items"]
    for section_name, (numbers, points) in CET_READING_SECTIONS.items():
        section = reading.get(section_name)
        if not isinstance(section, dict):
            raise RecordError(f"sections.reading.{section_name} must be an object")
        _required_text(section.get("directions"), f"sections.reading.{section_name}.directions")
        _required_text(section.get("passage"), f"sections.reading.{section_name}.passage")
        questions = section.get("questions")
        expected_numbers = list(numbers)
        if not isinstance(questions, list) or len(questions) != 10:
            raise RecordError(f"sections.reading.{section_name} must contain 10 questions")
        section_points = 0.0
        for question, number in zip(questions, expected_numbers):
            _validate_cet_question(
                question, number, f"sections.reading.{section_name}.questions"
            )
            item = objective_items.get(str(number))
            if not isinstance(item, dict) or item.get("answer") != question["answer"]:
                raise RecordError(f"objective_items.{number} must match the stored answer")
            section_points += float(item["points"])
        if abs(section_points - points) > 1e-9:
            raise RecordError(f"{section_name} objective points must total {points:g}")

    translation = sections.get("translation")
    if not isinstance(translation, dict):
        raise RecordError("sections.translation must be an object")
    for field in ("directions", "source_text", "reference_answer"):
        _required_text(translation.get(field), f"sections.translation.{field}")

    subjective = document["subjective_components"]
    if set(subjective) != {"writing", "translation"}:
        raise RecordError(f"{CET_FORMAT} requires writing and translation subjective scores")
    if subjective["writing"]["max_score"] != 15.0:
        raise RecordError("writing max_score must be 15")
    if subjective["translation"]["max_score"] != 15.0:
        raise RecordError("translation max_score must be 15")
    scheme = document["grading_scheme"]
    if (
        scheme["raw_max_score"] != 65.0
        or scheme["reported_max_score"] != 710.0
        or scheme["pass_score"] != 425.0
        or scheme["conversion"] != "linear"
        or scheme["precision"] != 2
        or scheme["rounding_step"] is not None
    ):
        raise RecordError(f"{CET_FORMAT} must use the 65-to-710 linear grading profile")


def _reported_score(raw_score: float, scheme: dict[str, Any]) -> float:
    if scheme["conversion"] == "linear":
        score = raw_score / scheme["raw_max_score"] * scheme["reported_max_score"]
    else:
        score = raw_score
    rounding_step = scheme["rounding_step"]
    if rounding_step is not None:
        score = math.floor(score / rounding_step + 0.5) * rounding_step
    return round(score, scheme["precision"])


def _objective_score(document: dict[str, Any], answers: dict[str, str]) -> float:
    score = 0.0
    for key, item in document["objective_items"].items():
        if answers.get(key, "").strip().casefold() == item["answer"].strip().casefold():
            score += item["points"]
    return round(score, 6)


def _validate_attempt(attempt: Any, document: dict[str, Any]) -> None:
    if not isinstance(attempt, dict):
        raise RecordError("each attempt must be an object")
    attempt_id = _required_text(attempt.get("attempt_id"), "attempt_id")
    if not re.fullmatch(r"attempt-[0-9a-f]{12}", attempt_id):
        raise RecordError("attempt_id format is invalid")
    if attempt.get("status") not in {"in_progress", "completed"}:
        raise RecordError("attempt status must be in_progress or completed")
    started_at = _timestamp(attempt.get("started_at"), "started_at")
    updated_at = _timestamp(attempt.get("updated_at"), "updated_at")
    if updated_at < started_at:
        raise RecordError("attempt updated_at cannot precede started_at")

    valid_keys = set(document["answer_keys"])
    answers = attempt.get("answers")
    if not isinstance(answers, dict) or not all(
        isinstance(key, str) and key in valid_keys and isinstance(value, str)
        for key, value in answers.items()
    ):
        raise RecordError("attempt answers must map valid answer keys to strings")
    skipped = attempt.get("skipped")
    if (
        not isinstance(skipped, list)
        or not all(isinstance(key, str) and key in valid_keys for key in skipped)
        or len(skipped) != len(set(skipped))
    ):
        raise RecordError("attempt skipped must contain unique valid answer keys")
    if set(answers).intersection(skipped):
        raise RecordError("an answer cannot also be skipped")

    if attempt["status"] == "completed":
        completed_at = _timestamp(attempt.get("completed_at"), "completed_at")
        if completed_at < started_at or completed_at != updated_at:
            raise RecordError("completed_at must equal updated_at and follow started_at")
        grading = attempt.get("grading")
        if not isinstance(grading, dict):
            raise RecordError("completed attempts require grading")
        scheme = document["grading_scheme"]
        expected_objective = _objective_score(document, answers)
        if grading.get("objective_score") != expected_objective:
            raise RecordError("grading.objective_score does not match stored answers")
        subjective_scores = grading.get("subjective_scores")
        if not isinstance(subjective_scores, dict) or set(subjective_scores) != set(
            document["subjective_components"]
        ):
            raise RecordError("grading.subjective_scores must cover every subjective component")
        for key, component in document["subjective_components"].items():
            _number(
                subjective_scores[key],
                f"grading.subjective_scores.{key}",
                0,
                component["max_score"],
            )
        expected_raw = round(expected_objective + sum(subjective_scores.values()), 6)
        if grading.get("raw_score") != expected_raw:
            raise RecordError("grading.raw_score does not match component scores")
        if grading.get("raw_max_score") != scheme["raw_max_score"]:
            raise RecordError("grading.raw_max_score does not match grading_scheme")
        expected_reported = _reported_score(expected_raw, scheme)
        if grading.get("reported_score") != expected_reported:
            raise RecordError("grading.reported_score does not match grading_scheme")
        for field in (
            "reported_max_score",
            "pass_score",
            "rounding_step",
            "score_unit",
            "score_note",
        ):
            if grading.get(field) != scheme[field]:
                raise RecordError(f"grading.{field} does not match grading_scheme")
        expected_passed = (
            None
            if scheme["pass_score"] is None
            else expected_reported >= scheme["pass_score"]
        )
        if grading.get("passed") != expected_passed:
            raise RecordError("grading.passed does not match the configured threshold")
        _required_text(grading.get("feedback"), "grading.feedback")
    elif attempt.get("completed_at") is not None or attempt.get("grading") is not None:
        raise RecordError("in-progress attempts cannot contain completion grading")


def validate_paper(document: Any) -> list[dict[str, Any]]:
    try:
        if not isinstance(document, dict):
            raise RecordError("paper root must be an object")
        if document.get("schema_version") != PAPER_SCHEMA_VERSION:
            raise RecordError(f"schema_version must be {PAPER_SCHEMA_VERSION}")
        exam_type = _slug(document.get("exam_type"), "exam_type")
        exam_name = _required_text(document.get("exam_name"), "exam_name")
        format_id = _slug(document.get("format_id"), "format_id")
        paper_id = _required_text(document.get("paper_id"), "paper_id")
        if not re.fullmatch(rf"{exam_type}-\d{{8}}T\d{{6}}-[0-9a-f]{{8}}", paper_id):
            raise RecordError("paper_id format is invalid")
        theme = _required_text(document.get("theme"), "theme")
        if "\n" in theme or len(theme) > 80:
            raise RecordError("theme must be a single line no longer than 80 characters")
        created_at = _timestamp(document.get("created_at"), "created_at")
        if not paper_id.startswith(f"{exam_type}-{created_at.strftime('%Y%m%dT%H%M%S')}-"):
            raise RecordError("paper_id timestamp must match created_at")
        expected_title = f"{exam_name} 模拟卷｜{theme}｜{created_at.date().isoformat()}"
        if document.get("title") != expected_title:
            raise RecordError("title must match the exam name, theme, and creation date")

        source_ids = document.get("source_record_ids")
        if (
            not isinstance(source_ids, list)
            or not source_ids
            or not all(isinstance(item, str) for item in source_ids)
            or len(source_ids) != len(set(source_ids))
        ):
            raise RecordError("source_record_ids must contain unique record ids")
        if any(identifier.partition(":")[0] not in CATEGORIES for identifier in source_ids):
            raise RecordError("source_record_ids contains an invalid record id")
        if not isinstance(document.get("sections"), dict) or not document["sections"]:
            raise RecordError("sections must be a non-empty object")

        answer_keys = _answer_keys(document)
        objective = document.get("objective_items")
        if not isinstance(objective, dict):
            raise RecordError("objective_items must be an object")
        for key, item in objective.items():
            if key not in answer_keys or not isinstance(item, dict):
                raise RecordError("objective_items must use valid answer keys")
            _required_text(item.get("answer"), f"objective_items.{key}.answer")
            _positive_number(item.get("points"), f"objective_items.{key}.points")
        subjective = document.get("subjective_components")
        if not isinstance(subjective, dict):
            raise RecordError("subjective_components must be an object")
        for key, component in subjective.items():
            if key not in answer_keys or not isinstance(component, dict):
                raise RecordError("subjective_components must use valid answer keys")
            _positive_number(
                component.get("max_score"), f"subjective_components.{key}.max_score"
            )
        if set(objective).intersection(subjective) or set(objective) | set(subjective) != set(
            answer_keys
        ):
            raise RecordError(
                "objective_items and subjective_components must partition answer_keys"
            )

        scheme = document.get("grading_scheme")
        if not isinstance(scheme, dict):
            raise RecordError("grading_scheme must be an object")
        raw_max = _positive_number(scheme.get("raw_max_score"), "raw_max_score")
        computed_raw_max = sum(item["points"] for item in objective.values()) + sum(
            item["max_score"] for item in subjective.values()
        )
        if abs(raw_max - computed_raw_max) > 1e-9:
            raise RecordError("raw_max_score must equal objective and subjective maxima")
        reported_max = _positive_number(
            scheme.get("reported_max_score"), "reported_max_score"
        )
        pass_score = scheme.get("pass_score")
        if pass_score is not None:
            _number(pass_score, "pass_score", 0, reported_max)
        if scheme.get("conversion") not in CONVERSION_METHODS:
            raise RecordError("conversion must be linear or identity")
        if scheme["conversion"] == "identity" and raw_max != reported_max:
            raise RecordError("identity conversion requires equal raw and reported maxima")
        precision = scheme.get("precision")
        if not isinstance(precision, int) or isinstance(precision, bool) or not 0 <= precision <= 4:
            raise RecordError("precision must be an integer from 0 to 4")
        if "rounding_step" not in scheme:
            raise RecordError("grading_scheme must include rounding_step")
        rounding_step = scheme.get("rounding_step")
        if rounding_step is not None:
            step = _positive_number(rounding_step, "rounding_step")
            if step > reported_max:
                raise RecordError("rounding_step cannot exceed reported_max_score")
        _required_text(scheme.get("score_unit"), "score_unit")
        _required_text(scheme.get("score_note"), "score_note")

        record_map = document.get("record_map")
        if not isinstance(record_map, dict) or set(record_map) != set(answer_keys):
            raise RecordError("record_map must cover every answer key")
        for key, identifiers in record_map.items():
            if not isinstance(identifiers, list) or not identifiers:
                raise RecordError(f"record_map.{key} must contain at least one record id")
            if not all(isinstance(identifier, str) and identifier in source_ids for identifier in identifiers):
                raise RecordError(f"record_map.{key} must reference source_record_ids")

        if format_id == CET_FORMAT:
            _validate_cet_format(document)

        attempts = document.get("attempts")
        if not isinstance(attempts, list):
            raise RecordError("attempts must be an array")
        seen_attempts: set[str] = set()
        for attempt in attempts:
            _validate_attempt(attempt, document)
            attempt_id = attempt["attempt_id"]
            if attempt_id in seen_attempts:
                raise RecordError("attempt_id must be unique within a paper")
            seen_attempts.add(attempt_id)
    except RecordError as exc:
        return [_issue(None, str(exc))]
    return []


class PaperService:
    def __init__(self, store: RecordStore):
        self.store = store
        self.paper_dir = self.store.repo_root / "exam-papers"

    def paper_path(self, paper_id: str) -> Path:
        if not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*-\d{8}T\d{6}-[0-9a-f]{8}", paper_id
        ):
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
        return {"paper": paper, "attempt": self._find_attempt(paper, attempt_id)}

    def _papers(self) -> list[dict[str, Any]]:
        if not self.paper_dir.exists():
            return []
        return [self._read_path(path) for path in sorted(self.paper_dir.glob("*.json"))]

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
            "exam_type": paper["exam_type"],
            "exam_name": paper["exam_name"],
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
    def _paper_id(exam_type: str, timestamp: datetime) -> str:
        return f"{exam_type}-{timestamp.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"

    def create(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RecordError("paper-create input must be an object")
        exam_type = _slug(payload.get("exam_type"), "exam_type")
        exam_name = _required_text(payload.get("exam_name"), "exam_name")
        theme = _required_text(payload.get("theme"), "theme")
        created_at = now_iso()
        timestamp = parse_timestamp(created_at)
        assert timestamp is not None
        paper_id = self._paper_id(exam_type, timestamp)
        document = {
            "schema_version": PAPER_SCHEMA_VERSION,
            "paper_id": paper_id,
            "exam_type": exam_type,
            "exam_name": exam_name,
            "format_id": payload.get("format_id"),
            "title": f"{exam_name} 模拟卷｜{theme}｜{timestamp.date().isoformat()}",
            "theme": theme,
            "created_at": created_at,
            "source_record_ids": payload.get("source_record_ids"),
            "sections": payload.get("sections"),
            "answer_keys": payload.get("answer_keys"),
            "objective_items": payload.get("objective_items"),
            "subjective_components": payload.get("subjective_components"),
            "grading_scheme": payload.get("grading_scheme"),
            "record_map": payload.get("record_map"),
            "attempts": [],
        }
        issues = validate_paper(document)
        if issues:
            raise RecordError(issues[0]["message"])
        path = self.paper_path(paper_id)
        with self.store._exclusive_lock():
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
        payload: Any, valid_keys: set[str]
    ) -> tuple[str, str | None, dict[str, str], list[str]]:
        if not isinstance(payload, dict):
            raise RecordError("paper-submit input must be an object")
        paper_id = _required_text(payload.get("paper_id"), "paper_id")
        attempt_id = payload.get("attempt_id")
        if attempt_id is not None and not isinstance(attempt_id, str):
            raise RecordError("attempt_id must be a string")
        answers = payload.get("answers", {})
        if not isinstance(answers, dict) or not all(
            isinstance(key, str)
            and key in valid_keys
            and isinstance(value, str)
            and value.strip()
            for key, value in answers.items()
        ):
            raise RecordError("answers must map valid answer keys to non-empty strings")
        skipped = payload.get("skipped", [])
        if (
            not isinstance(skipped, list)
            or not all(isinstance(key, str) and key in valid_keys for key in skipped)
            or len(skipped) != len(set(skipped))
        ):
            raise RecordError("skipped must contain unique valid answer keys")
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
        if not isinstance(payload, dict):
            raise RecordError("paper-submit input must be an object")
        paper_id = _required_text(payload.get("paper_id"), "paper_id")
        path = self.paper_path(paper_id)
        with self.store._exclusive_lock():
            paper = self._read_path(path)
            _, attempt_id, answers, skipped = self._validate_submission(
                payload, set(paper["answer_keys"])
            )
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
                key=paper["answer_keys"].index,
            )
            for key in skipped:
                attempt["answers"].pop(key, None)
            attempt["updated_at"] = timestamp
            self.store._write_file(path, paper, validate=validate_paper)
        return self._summary(paper, attempt)

    def complete(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RecordError("paper-complete input must be an object")
        paper_id = _required_text(payload.get("paper_id"), "paper_id")
        attempt_id = _required_text(payload.get("attempt_id"), "attempt_id")
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
            if covered != set(paper["answer_keys"]):
                missing = [key for key in paper["answer_keys"] if key not in covered]
                raise RecordError(f"attempt is incomplete; missing: {', '.join(missing)}")

            subjective_scores = payload.get("subjective_scores")
            components = paper["subjective_components"]
            if not isinstance(subjective_scores, dict) or set(subjective_scores) != set(
                components
            ):
                raise RecordError("subjective_scores must cover every subjective component")
            normalized_subjective: dict[str, float] = {}
            for key, component in components.items():
                score = _number(
                    subjective_scores[key],
                    f"subjective_scores.{key}",
                    0,
                    component["max_score"],
                )
                if key in attempt["skipped"] and score != 0:
                    raise RecordError(f"skipped {key} requires a score of 0")
                normalized_subjective[key] = score

            from .service import RecordService

            timestamp = now_iso()
            error_results = [
                RecordService._upsert_error(database["records"], error, timestamp)
                for error in errors
            ]
            objective_score = _objective_score(paper, attempt["answers"])
            raw_score = round(objective_score + sum(normalized_subjective.values()), 6)
            scheme = paper["grading_scheme"]
            reported_score = _reported_score(raw_score, scheme)
            passed = (
                None
                if scheme["pass_score"] is None
                else reported_score >= scheme["pass_score"]
            )
            attempt.update(
                status="completed",
                updated_at=timestamp,
                completed_at=timestamp,
                grading={
                    "objective_score": objective_score,
                    "subjective_scores": normalized_subjective,
                    "raw_score": raw_score,
                    "raw_max_score": scheme["raw_max_score"],
                    "reported_score": reported_score,
                    "reported_max_score": scheme["reported_max_score"],
                    "pass_score": scheme["pass_score"],
                    "passed": passed,
                    "rounding_step": scheme["rounding_step"],
                    "score_unit": scheme["score_unit"],
                    "score_note": scheme["score_note"],
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
                    "paper completion failed; all changes from this operation were "
                    f"rolled back: {write_error}"
                ) from write_error
        return {
            "paper_id": paper_id,
            "title": paper["title"],
            "exam_type": paper["exam_type"],
            "exam_name": paper["exam_name"],
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
                    "action": {
                        "command": "paper-list",
                        "status": "completed",
                        "random": True,
                    },
                }
            )
        return options
