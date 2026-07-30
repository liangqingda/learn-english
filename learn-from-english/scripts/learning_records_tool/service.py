"""Application services for learning-record workflows."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .git_adapter import commit_paths, ensure_paths_clean
from .menu import REVIEW_PATHS, build_menu, counts_for
from .models import (
    CATEGORIES,
    RecordError,
    empty_database,
    new_record,
    normalize_key,
    normalize_tags,
    now_iso,
    record_id,
    validate_database,
)
from .scheduler import review_priority, schedule_review
from .store import RecordStore


LEGACY_LOCATIONS = {
    "learning-records": "learning",
    "familiar-learning-records": "familiar",
    "mastered-learning-records": "mastered",
}


class RecordService:
    def __init__(self, store: RecordStore, *, auto_commit: bool = True):
        self.store = store
        self.auto_commit = auto_commit

    def _commit(self, reason: str) -> None:
        commit_paths(
            self.store.repo_root,
            reason,
            [self.store.data_path],
            enabled=self.auto_commit,
        )

    def _ensure_clean(self) -> None:
        ensure_paths_clean(
            self.store.repo_root,
            [self.store.data_path],
            enabled=self.auto_commit,
        )

    def records(self) -> dict[str, dict[str, Any]]:
        return self.store.read()["records"]

    @staticmethod
    def _encounter(record: dict[str, Any], timestamp: str) -> None:
        record["last_learned_at"] = timestamp
        record["learned_count"] = int(record.get("learned_count", 0)) + 1

    def batch_upsert(self, payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
        payload_list = list(payloads)
        if not payload_list:
            raise RecordError("at least one record is required")
        timestamp = now_iso()

        def operation(database: dict[str, Any]) -> dict[str, Any]:
            results = []
            for payload in payload_list:
                candidate = new_record(payload, timestamp=timestamp)
                existing = database["records"].get(candidate["id"])
                if existing is not None:
                    self._encounter(existing, timestamp)
                    results.append(
                        {
                            "id": existing["id"],
                            "created": False,
                            "encountered": True,
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
                        "status": candidate["status"],
                        "learned_count": 1,
                    }
                )
            return {"results": results, "count": len(results)}

        reason = f"batch upsert {len(payload_list)} record(s)"
        result = self.store.transaction(
            operation,
            before_write=self._ensure_clean,
            after_write=lambda: self._commit(reason),
        )
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

        result = self.store.transaction(
            operation,
            before_write=self._ensure_clean,
            after_write=lambda: self._commit("record repeated encounter"),
        )
        return result

    @staticmethod
    def _upsert_error(
        records: dict[str, dict[str, Any]], payload: dict[str, Any], timestamp: str
    ) -> dict[str, Any]:
        normalized = {**payload, "category": "errors"}
        candidate = new_record(normalized, timestamp=timestamp)
        existing = records.get(candidate["id"])
        if existing is not None:
            RecordService._encounter(existing, timestamp)
            return {"id": existing["id"], "created": False}
        records[candidate["id"]] = candidate
        return {"id": candidate["id"], "created": True}

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

        result = self.store.transaction(
            operation,
            before_write=self._ensure_clean,
            after_write=lambda: self._commit(f"complete review {identifier}"),
        )
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

    def menu(self, context: str, *, focus: str | None = None) -> dict[str, Any]:
        return build_menu(self.records(), context, focus=focus)

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

    def next_review(
        self,
        *,
        categories: Iterable[str] = (),
        path: str | None = None,
        status: str = "learning",
        randomize: bool = False,
        due_only: bool = False,
    ) -> dict[str, Any]:
        selected_categories = list(categories)
        if path:
            selected_categories.extend(self._categories_for_path(path))
        if not selected_categories:
            selected_categories = list(CATEGORIES)
        now = datetime.now().astimezone()
        candidates = [
            record
            for record in self.records().values()
            if record["status"] == status and record["category"] in selected_categories
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
            selected = min(candidates, key=lambda item: review_priority(item, now)) if candidates else None
        return {"status": status, "record": selected}

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
                expected_status = (
                    "mastered" if score == 10 else "familiar" if score >= 8 else "learning"
                )
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
            changes = self.store.transaction_unvalidated(
                apply_repairs,
                before_write=self._ensure_clean,
                after_write=lambda: self._commit("repair records"),
            )
        return {"dry_run": dry_run, "change_count": len(changes), "changes": changes}

    def migrate_legacy(self, *, dry_run: bool) -> dict[str, Any]:
        if self.store.exists():
            raise RecordError(f"record database already exists: {self.store.data_path}")
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
            "target": str(self.store.data_path),
        }
        if not dry_run:
            self.store.initialize(
                database,
                before_write=self._ensure_clean,
                after_write=lambda: self._commit("migrate records to schema v2"),
            )
        return result
