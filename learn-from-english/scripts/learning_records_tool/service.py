"""Application services for learning-record workflows."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections import Counter
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
from .scheduler import review_priority, schedule_review, status_for_score, ten_score_count
from .store import RecordStore


LEGACY_LOCATIONS = {
    "learning-records": "learning",
    "familiar-learning-records": "familiar",
    "mastered-learning-records": "mastered",
}
REVIEW_CLAIM_TTL = timedelta(minutes=45)
NEW_ITEM_REVIEW_INTERVAL = 4


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

    @classmethod
    def _merge_richer_candidate_content(
        cls, existing: dict[str, Any], candidate: dict[str, Any]
    ) -> list[str]:
        enriched_fields = []
        merged_tags = normalize_tags([*existing.get("tags", []), *candidate.get("tags", [])])
        if merged_tags != existing.get("tags", []):
            existing["tags"] = merged_tags
            enriched_fields.append("tags")
        for field in ("explanation", "source", "example"):
            current = str(existing.get(field) or "").strip()
            incoming = str(candidate.get(field) or "").strip()
            if incoming and len(cls._normalized_similarity_text(incoming)) > len(
                cls._normalized_similarity_text(current)
            ):
                existing[field] = incoming
                enriched_fields.append(field)
        return enriched_fields

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
        included_mastered_record = any(record.get("status") == "mastered" for record in records)
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
        if target["mastery_score"] == 10:
            target["status"] = (
                "mastered"
                if included_mastered_record or ten_score_count(target) >= 3
                else "familiar"
            )
        else:
            target["status"] = cls._status_for_score(float(target["mastery_score"]))
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
                    enriched_fields = self._merge_richer_candidate_content(existing, candidate)
                    results.append(
                        {
                            "id": existing["id"],
                            "created": False,
                            "encountered": True,
                            "match_reason": reason,
                            "similarity": similarity,
                            "status": existing["status"],
                            "learned_count": existing["learned_count"],
                            "enriched_fields": enriched_fields,
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
            enriched_fields = RecordService._merge_richer_candidate_content(existing, candidate)
            return {
                "id": existing["id"],
                "created": False,
                "match_reason": reason,
                "similarity": similarity,
                "enriched_fields": enriched_fields,
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
        claim_owner: str | None = None,
        claim_token: str | None = None,
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

        result = self.store.transaction_releasing_claim(
            identifier,
            operation,
            claim_owner=claim_owner,
            claim_token=claim_token,
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
        if not normalized_needle:
            raise RecordError("query must contain at least one letter or number")
        field_weights = {
            "title": 8,
            "tags": 7,
            "source": 5,
            "example": 4,
            "explanation": 3,
        }
        ranked_results = []
        for record in self.records().values():
            if statuses is not None and record["status"] not in statuses:
                continue
            values = {
                "title": str(record.get("title", "")),
                "explanation": str(record.get("explanation", "")),
                "source": str(record.get("source", "")),
                "example": str(record.get("example", "")),
                "tags": " ".join(record.get("tags", [])),
            }
            matched_fields = [
                field
                for field, value in values.items()
                if raw_needle in value.casefold()
                or normalized_needle in normalize_key(value)
            ]
            if not matched_fields:
                continue
            score = sum(field_weights[field] for field in matched_fields)
            if values["title"].casefold() == raw_needle:
                score += 10
            snippet_field = max(matched_fields, key=lambda field: field_weights[field])
            snippet = values[snippet_field].strip()
            if len(snippet) > 180:
                snippet = snippet[:177].rstrip() + "..."
            ranked_results.append(
                (
                    -score,
                    record["id"],
                    {
                        **record,
                        "matched_fields": matched_fields,
                        "snippet": snippet,
                        "relevance": score,
                    },
                )
            )
        return [item[2] for item in sorted(ranked_results)]

    def error_pattern_clusters(self, *, minimum_size: int = 2) -> dict[str, Any]:
        if minimum_size < 2:
            raise RecordError("minimum cluster size must be at least 2")
        errors = self.list_records(category="errors", status=None)
        generic_tags = {
            "error",
            "errors",
            "learning-record",
            "migrated-mastered-record",
            "review",
            "review-error",
        }

        def meaningful_tags(record: dict[str, Any]) -> set[str]:
            return {
                tag.casefold()
                for tag in record.get("tags", [])
                if tag.casefold() not in generic_tags
            }

        def relationship(left: dict[str, Any], right: dict[str, Any]) -> float | None:
            title_similarity = self._text_similarity(left.get("title"), right.get("title"))
            explanation_similarity = self._text_similarity(
                left.get("explanation"), right.get("explanation")
            )
            shared_tags = meaningful_tags(left).intersection(meaningful_tags(right))
            if title_similarity >= 0.68 or explanation_similarity >= 0.78:
                return max(title_similarity, explanation_similarity)
            if shared_tags and (title_similarity >= 0.45 or explanation_similarity >= 0.55):
                return max(title_similarity, explanation_similarity) + 0.1
            return None

        grouped: list[list[dict[str, Any]]] = []
        for record in errors:
            candidates = []
            for index, group in enumerate(grouped):
                score = relationship(group[0], record)
                if score is not None:
                    candidates.append((score, index))
            if candidates:
                _score, group_index = max(candidates, key=lambda item: (item[0], -item[1]))
                grouped[group_index].append(record)
            else:
                grouped.append([record])
        clusters = []
        clustered_ids = set()
        for records in grouped:
            if len(records) < minimum_size:
                continue
            ordered = sorted(
                records,
                key=lambda item: (
                    float(item.get("mastery_score", 0)),
                    -int(item.get("lapse_count", 0)),
                    item["id"],
                ),
            )
            clustered_ids.update(item["id"] for item in ordered)
            common_tags = sorted(set.intersection(*(meaningful_tags(item) for item in ordered)))
            clusters.append(
                {
                    "id": f"error-cluster:{ordered[0]['id'].partition(':')[2]}",
                    "label": common_tags[0] if common_tags else ordered[0]["title"],
                    "count": len(ordered),
                    "record_ids": [item["id"] for item in ordered],
                    "records": ordered,
                }
            )
        clusters.sort(key=lambda item: (-item["count"], item["id"]))
        return {
            "cluster_count": len(clusters),
            "clusters": clusters,
            "unclustered": [
                record for record in errors if record["id"] not in clustered_ids
            ],
        }

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
        records = self.records()
        now = datetime.now().astimezone()
        claims = self.store.read_review_claims().get("claims", {})
        active_claimed_ids = {
            identifier
            for identifier, claim in claims.items()
            if identifier in records and self._active_review_claim(claim, now) is not None
        }
        available = [
            record for identifier, record in records.items() if identifier not in active_claimed_ids
        ]
        claimed = [records[identifier] for identifier in active_claimed_ids]
        availability_counts = {
            "by_status": {
                status: sum(record["status"] == status for record in available)
                for status in ("learning", "familiar", "mastered")
            },
            "by_category": {
                category: sum(
                    record["category"] == category and record["status"] == "learning"
                    for record in available
                )
                for category in CATEGORIES
            },
            "claimed_by_status": {
                status: sum(record["status"] == status for record in claimed)
                for status in ("learning", "familiar", "mastered")
            },
            "claimed_by_category": {
                category: sum(
                    record["category"] == category and record["status"] == "learning"
                    for record in claimed
                )
                for category in CATEGORIES
            },
        }
        effective_focus = focus.strip() if focus and focus.strip() else None
        if effective_focus is None:
            focus_candidates = [record for record in available if record["status"] == "learning"]
            if focus_candidates:
                effective_focus = min(
                    focus_candidates, key=lambda record: review_priority(record, now)
                )["title"]
        return build_menu(
            records,
            context,
            focus=effective_focus,
            current_exercise_explained=current_exercise_explained,
            has_answer_errors=has_answer_errors,
            availability_counts=availability_counts,
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
                record = records.get(identifier)
                active_claim = self._active_review_claim(claim, now)
                try:
                    claimed_at = parse_timestamp(claim.get("claimed_at"))
                    last_reviewed_at = parse_timestamp(
                        record.get("last_reviewed_at") if record is not None else None
                    )
                except (TypeError, ValueError):
                    claimed_at = None
                    last_reviewed_at = None
                claimed_review_count = claim.get("review_count")
                review_completed = (
                    isinstance(claimed_review_count, int)
                    and int(record.get("review_count", 0)) > claimed_review_count
                ) or (
                    claimed_review_count is None
                    and claimed_at is not None
                    and last_reviewed_at is not None
                    and last_reviewed_at >= claimed_at
                )
                if record is None or active_claim is None or review_completed:
                    del claim_index[identifier]
            resumable = [
                (identifier, claim)
                for identifier, claim in claim_index.items()
                if claim.get("owner") == owner
                and identifier in records
                and records[identifier]["status"] == status
                and records[identifier]["category"] in selected_categories
            ]
            if resumable:
                identifier, claim = min(resumable, key=lambda item: item[0])
                if not claim.get("token"):
                    claim["token"] = uuid.uuid4().hex
                claim.setdefault("review_count", int(records[identifier].get("review_count", 0)))
                return {
                    "status": status,
                    "record": {**records[identifier], "review_claim": claim},
                    "resumed": True,
                }
            candidates = [
                record
                for record in records.values()
                if record["status"] == status
                and record["category"] in selected_categories
                and record["id"] not in claim_index
            ]
            overdue = [record for record in candidates if review_priority(record, now)[0] == 0]
            new_items = [record for record in candidates if review_priority(record, now)[0] == 1]
            future = [record for record in candidates if review_priority(record, now)[0] == 2]
            if due_only:
                future = []
            completed_reviews = sum(
                int(record.get("review_count", 0)) for record in records.values()
            )
            if overdue and new_items:
                selection_pool = (
                    new_items
                    if completed_reviews % NEW_ITEM_REVIEW_INTERVAL
                    == NEW_ITEM_REVIEW_INTERVAL - 1
                    else overdue
                )
            elif overdue:
                selection_pool = overdue
            elif new_items:
                selection_pool = new_items
            else:
                selection_pool = future
            if randomize and selection_pool:
                import random

                weights = [
                    max(1.0, 11.0 - float(record["mastery_score"]) + record["lapse_count"] * 2)
                    for record in selection_pool
                ]
                selected = random.choices(selection_pool, weights=weights, k=1)[0]
            else:
                selected = (
                    min(selection_pool, key=lambda item: review_priority(item, now))
                    if selection_pool
                    else None
                )
            if selected is not None:
                claim = {
                    "owner": owner,
                    "token": uuid.uuid4().hex,
                    "review_count": int(selected.get("review_count", 0)),
                    "claimed_at": now.isoformat(timespec="seconds"),
                    "expires_at": (now + REVIEW_CLAIM_TTL).isoformat(timespec="seconds"),
                }
                claim_index[selected["id"]] = claim
                selected = {**selected, "review_claim": claim}
            return {"status": status, "record": selected, "resumed": False}

        return self.store.review_claims_transaction(operation)

    def release_claim(
        self, identifier: str, *, claim_owner: str, claim_token: str
    ) -> dict[str, Any]:
        if not claim_owner or not claim_token:
            raise RecordError("claim owner and token are required")

        def operation(_database: dict[str, Any], claims: dict[str, Any]) -> dict[str, Any]:
            claim_index = claims.setdefault("claims", {})
            claim = claim_index.get(identifier)
            if claim is None:
                raise RecordError(f"review claim does not exist: {identifier}")
            if claim.get("owner") != claim_owner or claim.get("token") != claim_token:
                raise RecordError("review claim owner or token does not match")
            del claim_index[identifier]
            return {"id": identifier, "released": True}

        return self.store.review_claims_transaction(operation)

    def history(self, identifier: str) -> dict[str, Any]:
        record = self.records().get(identifier)
        if record is None:
            raise RecordError(f"record does not exist: {identifier}")
        return {"id": identifier, "history": record["review_history"]}

    def stats(self, days: int) -> dict[str, Any]:
        if days <= 0:
            raise RecordError("period must be a positive number of days")
        now = datetime.now().astimezone()
        start_date = now.date() - timedelta(days=days - 1)
        cutoff = datetime.combine(start_date, datetime.min.time(), tzinfo=now.tzinfo)
        records = list(self.records().values())
        events = []
        for record in records:
            events.extend(
                {"id": record["id"], "category": record["category"], **event}
                for event in record["review_history"]
                if datetime.fromisoformat(event["reviewed_at"]) >= cutoff
            )
        average = sum(float(event["score"]) for event in events) / len(events) if events else None
        distribution = {"0-4": 0, "5-7": 0, "8-9": 0, "10": 0}
        daily_index = {
            (now.date() - timedelta(days=offset)).isoformat(): {
                "date": (now.date() - timedelta(days=offset)).isoformat(),
                "review_count": 0,
                "average_score": None,
                "lapse_count": 0,
                "mastery_count": 0,
                "_score_total": 0.0,
            }
            for offset in reversed(range(days))
        }
        category_index = {
            category: {
                "category": category,
                "review_count": 0,
                "average_score": None,
                "lapse_count": 0,
                "mastery_count": 0,
                "_score_total": 0.0,
            }
            for category in CATEGORIES
        }
        lapse_count = 0
        mastery_count = 0
        for event in events:
            score = float(event["score"])
            bucket = "10" if score == 10 else "8-9" if score >= 8 else "5-7" if score >= 5 else "0-4"
            distribution[bucket] += 1
            lapsed = event.get("previous_status") in {"familiar", "mastered"} and event.get(
                "new_status"
            ) == "learning"
            mastered = event.get("previous_status") != "mastered" and event.get(
                "new_status"
            ) == "mastered"
            lapse_count += int(lapsed)
            mastery_count += int(mastered)
            day = datetime.fromisoformat(event["reviewed_at"]).astimezone(now.tzinfo).date().isoformat()
            for group in (daily_index.get(day), category_index[event["category"]]):
                if group is None:
                    continue
                group["review_count"] += 1
                group["_score_total"] += score
                group["lapse_count"] += int(lapsed)
                group["mastery_count"] += int(mastered)
        mastery_event_ids = {
            event["id"]
            for event in events
            if event.get("previous_status") != "mastered"
            and event.get("new_status") == "mastered"
        }
        for record in records:
            mastered_at = parse_timestamp(record.get("mastered_at"))
            if (
                record["id"] in mastery_event_ids
                or mastered_at is None
                or mastered_at < cutoff
            ):
                continue
            mastery_count += 1
            day = mastered_at.astimezone(now.tzinfo).date().isoformat()
            if day in daily_index:
                daily_index[day]["mastery_count"] += 1
            category_index[record["category"]]["mastery_count"] += 1
        for group in [*daily_index.values(), *category_index.values()]:
            if group["review_count"]:
                group["average_score"] = round(
                    group.pop("_score_total") / group["review_count"], 2
                )
            else:
                group.pop("_score_total")
        due_records = [
            record
            for record in records
            if record["status"] != "mastered"
            and (
                record.get("next_review_at") is None
                or datetime.fromisoformat(record["next_review_at"]) <= now
            )
        ]
        due_by_status = Counter(record["status"] for record in due_records)
        due_by_category = Counter(record["category"] for record in due_records)
        snapshot_totals = self.summary()["totals"]
        return {
            "period_days": days,
            "review_count": len(events),
            "average_score": round(average, 2) if average is not None else None,
            "status_counts": snapshot_totals,
            "snapshot_totals": snapshot_totals,
            "mastered_random_pool": snapshot_totals["mastered"],
            "daily": list(daily_index.values()),
            "by_category": list(category_index.values()),
            "score_distribution": distribution,
            "due_backlog": {
                "total": len(due_records),
                "by_status": {status: due_by_status[status] for status in ("learning", "familiar", "mastered")},
                "by_category": {category: due_by_category[category] for category in CATEGORIES},
            },
            "lapse_count": lapse_count,
            "mastery_count": mastery_count,
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
