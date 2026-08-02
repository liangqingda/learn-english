"""Application services for learning-record workflows."""

from __future__ import annotations

import json
import os
import re
import uuid
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .menu import REVIEW_PATHS, build_menu, counts_for
from .models import (
    CATEGORIES,
    RecordError,
    empty_database,
    new_record,
    normalize_key,
    normalize_tags,
    now_iso,
    parse_timestamp,
    record_id,
    validate_database,
)
from .scheduler import review_priority, schedule_review, status_for_score
from .store import RecordStore


LEGACY_LOCATIONS = {
    "learning-records": "learning",
    "familiar-learning-records": "familiar",
    "mastered-learning-records": "mastered",
}
REVIEW_CLAIM_TTL = timedelta(minutes=45)


class RecordService:
    def __init__(self, store: RecordStore):
        self.store = store

    def records(self) -> dict[str, dict[str, Any]]:
        return self.store.read()["records"]

    @staticmethod
    def _normalized_similarity_text(value: str | None) -> str:
        normalized = (value or "").casefold()
        return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)

    @classmethod
    def _text_similarity(cls, left: str | None, right: str | None) -> float:
        return SequenceMatcher(
            None, cls._normalized_similarity_text(left), cls._normalized_similarity_text(right)
        ).ratio()

    @classmethod
    def _similar_match_reason(
        cls, candidate: dict[str, Any], existing: dict[str, Any]
    ) -> tuple[str, float] | None:
        if candidate["category"] != existing["category"]:
            return None
        if candidate["id"] == existing["id"]:
            return ("exact-id", 1.0)

        candidate_source = cls._normalized_similarity_text(candidate.get("source"))
        existing_source = cls._normalized_similarity_text(existing.get("source"))
        candidate_example = cls._normalized_similarity_text(candidate.get("example"))
        existing_example = cls._normalized_similarity_text(existing.get("example"))
        if (
            candidate_source
            and candidate_example
            and candidate_source == existing_source
            and candidate_example == existing_example
        ):
            return ("same-source-example", 0.99)

        title_similarity = cls._text_similarity(candidate.get("title"), existing.get("title"))
        explanation_similarity = cls._text_similarity(
            candidate.get("explanation"), existing.get("explanation")
        )
        source_similarity = cls._text_similarity(candidate.get("source"), existing.get("source"))
        if title_similarity >= 0.78 and explanation_similarity >= 0.45:
            return ("similar-title-explanation", round((title_similarity + explanation_similarity) / 2, 3))
        if title_similarity >= 0.72 and source_similarity >= 0.72:
            return ("similar-title-source", round((title_similarity + source_similarity) / 2, 3))
        if explanation_similarity >= 0.82 and title_similarity >= 0.50:
            return ("similar-explanation", round((title_similarity + explanation_similarity) / 2, 3))
        return None

    @classmethod
    def _find_similar_record(
        cls, records: dict[str, dict[str, Any]], candidate: dict[str, Any]
    ) -> tuple[dict[str, Any], str, float] | None:
        exact = records.get(candidate["id"])
        if exact is not None:
            return exact, "exact-id", 1.0
        matches = []
        for existing in records.values():
            reason = cls._similar_match_reason(candidate, existing)
            if reason is not None:
                matches.append((reason[1], existing["id"], existing, reason[0]))
        if not matches:
            return None
        score, _, existing, reason = max(matches, key=lambda item: (item[0], item[1]))
        return existing, reason, score

    @staticmethod
    def _encounter(record: dict[str, Any], timestamp: str) -> None:
        record["last_learned_at"] = timestamp
        record["learned_count"] = int(record.get("learned_count", 0)) + 1

    @staticmethod
    def _timestamp_key(value: str | None) -> datetime | None:
        if not value:
            return None
        return parse_timestamp(value)

    @classmethod
    def _earliest_timestamp(cls, values: Iterable[str | None]) -> str | None:
        parsed = [(cls._timestamp_key(value), value) for value in values if value]
        parsed = [(timestamp, value) for timestamp, value in parsed if timestamp is not None]
        return min(parsed, key=lambda item: item[0])[1] if parsed else None

    @classmethod
    def _latest_timestamp(cls, values: Iterable[str | None]) -> str | None:
        parsed = [(cls._timestamp_key(value), value) for value in values if value]
        parsed = [(timestamp, value) for timestamp, value in parsed if timestamp is not None]
        return max(parsed, key=lambda item: item[0])[1] if parsed else None

    @staticmethod
    def _status_for_score(score: float, record: dict[str, Any] | None = None) -> str:
        return status_for_score(score, record)

    @classmethod
    def _merge_record_content(
        cls,
        target: dict[str, Any],
        sources: list[dict[str, Any]],
        *,
        title: str | None = None,
        explanation: str | None = None,
        source: str | None = None,
        example: str | None = None,
    ) -> None:
        records = [target, *sources]
        if title is not None:
            target["title"] = title.strip()
        if explanation is not None:
            target["explanation"] = explanation.strip()
        if source is not None:
            target["source"] = source.strip()
        if example is not None:
            target["example"] = example.strip()

        target["tags"] = normalize_tags(
            [tag for record in records for tag in record.get("tags", [])]
        )
        target["first_learned_at"] = cls._earliest_timestamp(
            record.get("first_learned_at") for record in records
        )
        target["last_learned_at"] = cls._latest_timestamp(
            record.get("last_learned_at") for record in records
        )
        target["learned_count"] = sum(int(record.get("learned_count", 0)) for record in records)
        target["review_count"] = sum(int(record.get("review_count", 0)) for record in records)
        target["lapse_count"] = sum(int(record.get("lapse_count", 0)) for record in records)
        target["review_history"] = sorted(
            [
                event
                for record in records
                for event in record.get("review_history", [])
            ],
            key=lambda event: event.get("reviewed_at", ""),
        )
        target["last_reviewed_at"] = cls._latest_timestamp(
            record.get("last_reviewed_at") for record in records
        )
        target["mastery_score"] = min(float(record.get("mastery_score", 0)) for record in records)
        target["status"] = cls._status_for_score(float(target["mastery_score"]), target)
        if target["status"] == "learning":
            target["high_score_streak"] = 0
            target["mastered_at"] = None
            target["next_review_at"] = cls._earliest_timestamp(
                record.get("next_review_at") for record in records
            )
        else:
            target["high_score_streak"] = max(
                int(record.get("high_score_streak", 0)) for record in records
            )
            target["next_review_at"] = cls._latest_timestamp(
                record.get("next_review_at") for record in records
            )
            target["mastered_at"] = (
                cls._earliest_timestamp(record.get("mastered_at") for record in records)
                if target["status"] == "mastered"
                else None
            )

    def batch_upsert(self, payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
        payload_list = list(payloads)
        if not payload_list:
            raise RecordError("at least one record is required")
        timestamp = now_iso()

        def operation(database: dict[str, Any]) -> dict[str, Any]:
            results = []
            for payload in payload_list:
                candidate = new_record(payload, timestamp=timestamp)
                match = self._find_similar_record(database["records"], candidate)
                if match is not None:
                    existing, reason, similarity = match
                    self._encounter(existing, timestamp)
                    results.append(
                        {
                            "id": existing["id"],
                            "created": False,
                            "encountered": True,
                            "match_reason": reason,
                            "similarity": similarity,
                            "status": existing["status"],
                            "learned_count": existing["learned_count"],
                        }
                    )
                    continue
                database["records"][candidate["id"]] = candidate
                results.append(
                    {
                        "id": candidate["id"],
                        "created": True,
                        "encountered": False,
                        "match_reason": None,
                        "similarity": None,
                        "status": candidate["status"],
                        "learned_count": 1,
                    }
                )
            return {"results": results, "count": len(results)}

        result = self.store.transaction(operation)
        return result

    def upsert(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.batch_upsert([payload])["results"][0]
        record = self.records()[result["id"]]
        return {**record, **result, "location": "learning-records"}

    def encounter(self, identifier: str) -> dict[str, Any]:
        timestamp = now_iso()

        def operation(database: dict[str, Any]) -> dict[str, Any]:
            record = database["records"].get(identifier)
            if record is None:
                raise RecordError(f"record does not exist: {identifier}")
            self._encounter(record, timestamp)
            return {
                "id": identifier,
                "learned_count": record["learned_count"],
                "last_learned_at": timestamp,
            }

        result = self.store.transaction(operation)
        return result

    @staticmethod
    def _upsert_error(
        records: dict[str, dict[str, Any]], payload: dict[str, Any], timestamp: str
    ) -> dict[str, Any]:
        normalized = {**payload, "category": "errors"}
        candidate = new_record(normalized, timestamp=timestamp)
        match = RecordService._find_similar_record(records, candidate)
        if match is not None:
            existing, reason, similarity = match
            RecordService._encounter(existing, timestamp)
            return {
                "id": existing["id"],
                "created": False,
                "match_reason": reason,
                "similarity": similarity,
            }
        records[candidate["id"]] = candidate
        return {
            "id": candidate["id"],
            "created": True,
            "match_reason": None,
            "similarity": None,
        }

    def merge_records(
        self,
        target_id: str,
        source_ids: Iterable[str],
        *,
        title: str | None = None,
        explanation: str | None = None,
        source: str | None = None,
        example: str | None = None,
    ) -> dict[str, Any]:
        source_list = list(source_ids)
        if not source_list:
            raise RecordError("at least one source record is required")
        if target_id in source_list:
            raise RecordError("target record cannot also be a source")

        def operation(database: dict[str, Any]) -> dict[str, Any]:
            records = database["records"]
            target = records.get(target_id)
            if target is None:
                raise RecordError(f"target record does not exist: {target_id}")
            sources = []
            for source_id in source_list:
                source_record = records.get(source_id)
                if source_record is None:
                    raise RecordError(f"source record does not exist: {source_id}")
                if source_record["category"] != target["category"]:
                    raise RecordError("merged records must belong to the same category")
                sources.append(source_record)
            self._merge_record_content(
                target,
                sources,
                title=title,
                explanation=explanation,
                source=source,
                example=example,
            )
            for source_id in source_list:
                del records[source_id]
            return {
                "target": target["id"],
                "merged": source_list,
                "deleted_count": len(source_list),
                "status": target["status"],
                "mastery_score": target["mastery_score"],
                "learned_count": target["learned_count"],
                "review_count": target["review_count"],
            }

        return self.store.transaction(operation)

    def complete_review(
        self,
        identifier: str,
        score: float,
        errors: Iterable[dict[str, Any]] = (),
        *,
        expected_status: str | None = None,
    ) -> dict[str, Any]:
        if not 0 <= score <= 10:
            raise RecordError("score must be between 0 and 10")
        error_payloads = list(errors)
        reviewed_at = datetime.now().astimezone()
        reviewed_at_text = reviewed_at.isoformat(timespec="seconds")

        def operation(database: dict[str, Any]) -> dict[str, Any]:
            record = database["records"].get(identifier)
            if record is None:
                raise RecordError(f"record does not exist: {identifier}")
            if expected_status is not None and record["status"] != expected_status:
                raise RecordError(f"{expected_status} record does not exist: {identifier}")
            previous_status = record["status"]
            record["mastery_score"] = float(score)
            record["review_count"] = int(record.get("review_count", 0)) + 1
            record["last_reviewed_at"] = reviewed_at_text
            schedule_review(record, score, reviewed_at)
            record.pop("review_claim", None)
            record["review_history"].append(
                {
                    "score": float(score),
                    "reviewed_at": reviewed_at_text,
                    "previous_status": previous_status,
                    "new_status": record["status"],
                }
            )
            error_results = [
                self._upsert_error(database["records"], payload, reviewed_at_text)
                for payload in error_payloads
            ]
            return {
                "id": identifier,
                "score": float(score),
                "previous_status": previous_status,
                "status": record["status"],
                "mastery_score": record["mastery_score"],
                "review_count": record["review_count"],
                "high_score_streak": record["high_score_streak"],
                "lapse_count": record["lapse_count"],
                "last_reviewed_at": record["last_reviewed_at"],
                "next_review_at": record["next_review_at"],
                "mastered_at": record["mastered_at"],
                "errors": error_results,
                "archived": record["status"] == "familiar",
                "mastered": record["status"] == "mastered",
                "moved_to_learning_records": previous_status in {"familiar", "mastered"}
                and record["status"] == "learning",
                "deleted": False,
            }

        result = self.store.transaction(operation)
        return result

    def list_records(
        self, *, category: str | None = None, status: str | None = None
    ) -> list[dict[str, Any]]:
        records = self.records().values()
        filtered = [
            record
            for record in records
            if (category is None or record["category"] == category)
            and (status is None or record["status"] == status)
        ]
        return sorted(filtered, key=lambda item: (item["category"], item["id"]))

    def search(self, query: str, statuses: set[str] | None = None) -> list[dict[str, Any]]:
        normalized_needle = normalize_key(query)
        raw_needle = query.casefold().strip()
        if not raw_needle:
            raise RecordError("query must not be empty")
        results = []
        for record in self.records().values():
            if statuses is not None and record["status"] not in statuses:
                continue
            searchable = json.dumps(record, ensure_ascii=False).casefold()
            if raw_needle in searchable or normalized_needle in normalize_key(searchable):
                results.append(record)
        return sorted(results, key=lambda item: item["id"])

    def summary(self) -> dict[str, Any]:
        return counts_for(self.records())

    def menu(
        self,
        context: str,
        *,
        focus: str | None = None,
        current_exercise_explained: bool = False,
        has_answer_errors: bool = False,
    ) -> dict[str, Any]:
        return build_menu(
            self.records(),
            context,
            focus=focus,
            current_exercise_explained=current_exercise_explained,
            has_answer_errors=has_answer_errors,
        )

    @staticmethod
    def _categories_for_path(path_id: str) -> list[str]:
        if path_id.startswith("mixed+"):
            path_ids = path_id.split("+")[1:]
        else:
            path_ids = [path_id]
        matched = [path for path in REVIEW_PATHS if path["id"] in path_ids]
        if len(matched) != len(path_ids):
            raise RecordError(f"review path does not exist: {path_id}")
        return [category for path in matched for category in path["categories"]]

    @staticmethod
    def _active_review_claim(claim: Any, now: datetime) -> dict[str, Any] | None:
        if not isinstance(claim, dict):
            return None
        try:
            expires_at = parse_timestamp(claim.get("expires_at"))
        except (TypeError, ValueError):
            return None
        return claim if expires_at is not None and expires_at > now else None

    @staticmethod
    def _claim_owner() -> str:
        return f"pid-{os.getpid()}:{uuid.uuid4().hex}"

    def next_review(
        self,
        *,
        categories: Iterable[str] = (),
        path: str | None = None,
        status: str = "learning",
        randomize: bool = False,
        due_only: bool = False,
        claim_owner: str | None = None,
    ) -> dict[str, Any]:
        selected_categories = list(categories)
        if path:
            selected_categories.extend(self._categories_for_path(path))
        if not selected_categories:
            selected_categories = list(CATEGORIES)
        now = datetime.now().astimezone()
        owner = claim_owner or self._claim_owner()

        def operation(database: dict[str, Any], claims: dict[str, Any]) -> dict[str, Any]:
            records = database["records"]
            claim_index = claims.setdefault("claims", {})
            for identifier, claim in list(claim_index.items()):
                if identifier not in records or self._active_review_claim(claim, now) is None:
                    del claim_index[identifier]
            candidates = [
                record
                for record in records.values()
                if record["status"] == status
                and record["category"] in selected_categories
                and record["id"] not in claim_index
            ]
            due = [record for record in candidates if review_priority(record, now)[0] == 0]
            if due_only:
                candidates = due
            elif due:
                candidates = due
            if randomize and candidates:
                import random

                weights = [
                    max(1.0, 11.0 - float(record["mastery_score"]) + record["lapse_count"] * 2)
                    for record in candidates
                ]
                selected = random.choices(candidates, weights=weights, k=1)[0]
            else:
                selected = (
                    min(candidates, key=lambda item: review_priority(item, now))
                    if candidates
                    else None
                )
            if selected is not None:
                claim = {
                    "owner": owner,
                    "claimed_at": now.isoformat(timespec="seconds"),
                    "expires_at": (now + REVIEW_CLAIM_TTL).isoformat(timespec="seconds"),
                }
                claim_index[selected["id"]] = claim
                selected = {**selected, "review_claim": claim}
            return {"status": status, "record": selected}

        return self.store.review_claims_transaction(operation)

    def history(self, identifier: str) -> dict[str, Any]:
        record = self.records().get(identifier)
        if record is None:
            raise RecordError(f"record does not exist: {identifier}")
        return {"id": identifier, "history": record["review_history"]}

    def stats(self, days: int) -> dict[str, Any]:
        if days <= 0:
            raise RecordError("period must be a positive number of days")
        cutoff = datetime.now().astimezone() - timedelta(days=days)
        events = []
        for record in self.records().values():
            events.extend(
                {"id": record["id"], "category": record["category"], **event}
                for event in record["review_history"]
                if datetime.fromisoformat(event["reviewed_at"]) >= cutoff
            )
        average = sum(float(event["score"]) for event in events) / len(events) if events else None
        return {
            "period_days": days,
            "review_count": len(events),
            "average_score": round(average, 2) if average is not None else None,
            "status_counts": self.summary()["totals"],
            "events": sorted(events, key=lambda event: event["reviewed_at"]),
        }

    def validate(self) -> dict[str, Any]:
        try:
            database = self.store.read_unvalidated()
        except RecordError as exc:
            return {"valid": False, "issue_count": 1, "issues": [{"message": str(exc)}]}
        issues = validate_database(database)
        return {"valid": not issues, "issue_count": len(issues), "issues": issues}

    def repair(self, *, dry_run: bool) -> dict[str, Any]:
        database = self.store.read_unvalidated()
        def apply_repairs(target: dict[str, Any]) -> list[dict[str, Any]]:
            changes = []
            for record in target["records"].values():
                raw_tags = record.get("tags")
                if not isinstance(raw_tags, list) or not all(
                    isinstance(tag, str) for tag in raw_tags
                ):
                    continue
                normalized = normalize_tags(raw_tags)
                if normalized != record.get("tags"):
                    changes.append({"id": record["id"], "field": "tags"})
                    record["tags"] = normalized
                score = float(record.get("mastery_score", 0))
                expected_status = status_for_score(score, record)
                if record.get("status") != expected_status:
                    changes.append({"id": record["id"], "field": "status"})
                    record["status"] = expected_status
                expected_mastered_at = (
                    record.get("mastered_at")
                    or record.get("last_reviewed_at")
                    or record.get("last_learned_at")
                    if expected_status == "mastered"
                    else None
                )
                if record.get("mastered_at") != expected_mastered_at:
                    changes.append({"id": record["id"], "field": "mastered_at"})
                    record["mastered_at"] = expected_mastered_at
            return changes

        changes = apply_repairs(database)
        if changes and not dry_run:
            changes = self.store.transaction_unvalidated(apply_repairs)
        return {"dry_run": dry_run, "change_count": len(changes), "changes": changes}

    @staticmethod
    def _looks_like_current_layout_document(document: Any) -> bool:
        if isinstance(document, list):
            return True
        return isinstance(document, dict) and (
            "records" in document or "schema_version" in document
        )

    def migrate_legacy(self, *, dry_run: bool) -> dict[str, Any]:
        current_layout_exists = False
        for category in CATEGORIES:
            for path in (
                self.store.category_path(category),
                self.store.mastered_category_path(category),
            ):
                if not path.exists():
                    continue
                try:
                    document = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise RecordError(f"cannot inspect existing record file {path}: {exc}") from exc
                if self._looks_like_current_layout_document(document):
                    current_layout_exists = True
                    break
            if current_layout_exists:
                break
        if self.store.legacy_data_path.exists() or current_layout_exists:
            raise RecordError(f"record database already exists: {self.store.legacy_data_path}")
        database = empty_database()
        migrated_counts = {status: 0 for status in ("learning", "familiar", "mastered")}
        for location, status in LEGACY_LOCATIONS.items():
            for category in CATEGORIES:
                path = self.store.repo_root / location / f"{category}.json"
                if not path.exists():
                    continue
                try:
                    document = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise RecordError(f"cannot migrate {path}: {exc}") from exc
                if document.get("category") != category or not isinstance(document.get("items"), list):
                    raise RecordError(f"invalid legacy document: {path}")
                for legacy in document["items"]:
                    identifier = str(legacy.get("id", ""))
                    if identifier in database["records"]:
                        raise RecordError(f"duplicate legacy record id: {identifier}")
                    if status == "mastered":
                        learned_at = legacy.get("mastered_at") or now_iso()
                        migrated_summary = legacy.get("summary") or "Migrated mastered record"
                        record = new_record(
                            {
                                "category": category,
                                "key": identifier.partition(":")[2],
                                "title": legacy.get("title", identifier),
                                "explanation": migrated_summary,
                                "source": migrated_summary,
                                "example": "",
                                "tags": ["migrated-mastered-record"],
                            },
                            timestamp=learned_at,
                        )
                        record.update(
                            {
                                "status": "mastered",
                                "mastery_score": 10.0,
                                "high_score_streak": 1,
                                "mastered_at": learned_at,
                            }
                        )
                    else:
                        legacy_score = float(legacy.get("mastery_score", 0))
                        inferred_status = (
                            "mastered"
                            if legacy_score == 10
                            else "familiar"
                            if legacy_score >= 8
                            else "learning"
                        )
                        record = new_record(
                            {
                                "category": category,
                                "key": identifier.partition(":")[2],
                                "title": legacy.get("title", identifier),
                                "explanation": legacy.get("explanation", "Migrated record"),
                                "source": legacy.get("source", ""),
                                "example": legacy.get("example", ""),
                                "tags": legacy.get("tags", []),
                            },
                            timestamp=legacy.get("first_learned_at") or now_iso(),
                        )
                        record.update(
                            {
                                "status": inferred_status,
                                "last_learned_at": legacy.get("last_learned_at")
                                or record["first_learned_at"],
                                "learned_count": int(legacy.get("learned_count", 1)),
                                "mastery_score": legacy_score,
                                "review_count": int(legacy.get("review_count", 0)),
                                "high_score_streak": int(legacy.get("high_score_streak", 0)),
                                "last_reviewed_at": legacy.get("last_reviewed_at"),
                            }
                        )
                        if inferred_status == "mastered":
                            record["mastered_at"] = (
                                legacy.get("last_reviewed_at")
                                or legacy.get("last_learned_at")
                                or record["first_learned_at"]
                            )
                    database["records"][identifier] = record
                    migrated_counts[record["status"]] += 1
        issues = validate_database(database)
        if issues:
            raise RecordError(f"legacy migration would create invalid data: {issues[0]['message']}")
        result = {
            "dry_run": dry_run,
            "record_count": len(database["records"]),
            "counts": migrated_counts,
            "target": str(self.store.learning_dir),
        }
        if not dry_run:
            self.store.replace(database)
        return result
