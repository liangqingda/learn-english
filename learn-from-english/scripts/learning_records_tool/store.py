"""Atomic JSON persistence for learning records."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, TypeVar

from .models import (
    CATEGORIES,
    RecordError,
    empty_database,
    normalize_key,
    parse_timestamp,
    validate_database,
)


T = TypeVar("T")


class RecordStore:
    MASTERED_SPILLOVER_THRESHOLD = 10
    MASTERED_CATEGORY = "usage"
    MASTERED_FIELDS = (
        "title",
        "explanation",
        "mastered_at",
    )

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        self.data_path = self.repo_root / "learning-records" / "records.json"
        self.mastered_path = self.repo_root / "learning-records" / "mastered.json"
        self.review_claims_path = self.repo_root / "learning-records" / ".review-claims.json"

    def exists(self) -> bool:
        return self.data_path.exists()

    @contextmanager
    def _exclusive_lock(self):
        import fcntl

        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.data_path.parent / ".records.lock"
        with lock_path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_database_file(
        self, path: Path, *, allow_missing: bool = False
    ) -> dict[str, Any]:
        if not path.exists():
            if allow_missing:
                return empty_database()
            raise RecordError(
                f"record database does not exist: {path}; run migrate-v2 first"
            )
        try:
            with path.open(encoding="utf-8") as handle:
                database = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordError(f"cannot read valid JSON from {path}: {exc}") from exc
        issues = validate_database(database)
        if issues:
            raise RecordError(f"record database is invalid: {issues[0]['message']}")
        return database

    def _read_mastered_database_file(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return empty_database()
        try:
            with path.open(encoding="utf-8") as handle:
                database = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordError(f"cannot read valid JSON from {path}: {exc}") from exc
        issues = validate_database(database)
        if not issues:
            return database
        return self._hydrate_mastered_database(database)

    @classmethod
    def _mastered_records_from_storage(cls, database: Any) -> list[tuple[str | None, dict[str, Any]]]:
        if isinstance(database, list):
            return [(None, record) for record in database]
        if isinstance(database, dict) and isinstance(database.get("records"), dict):
            return list(database["records"].items())
        return []

    @classmethod
    def _mastered_identifier(
        cls,
        record: dict[str, Any],
        fallback_index: int,
        used_identifiers: set[str],
    ) -> str:
        stored_identifier = record.get("id")
        if isinstance(stored_identifier, str) and stored_identifier.strip():
            identifier = stored_identifier
        else:
            title_key = normalize_key(str(record.get("title") or ""))
            suffix = title_key or f"mastered-record-{fallback_index + 1}"
            identifier = f"{cls.MASTERED_CATEGORY}:{suffix}"
        if identifier not in used_identifiers:
            used_identifiers.add(identifier)
            return identifier
        prefix = identifier
        counter = 2
        while f"{prefix}-{counter}" in used_identifiers:
            counter += 1
        identifier = f"{prefix}-{counter}"
        used_identifiers.add(identifier)
        return identifier

    @classmethod
    def _validate_mastered_database(cls, database: Any) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        if not isinstance(database, (dict, list)):
            return [{"id": None, "field": None, "message": "database root must be an object or array"}]
        if isinstance(database, dict):
            if database.get("schema_version") != 2:
                issues.append(
                    {"id": None, "field": "schema_version", "message": "schema_version must be 2"}
                )
            revision = database.get("revision")
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
                issues.append(
                    {"id": None, "field": "revision", "message": "revision must be a non-negative integer"}
                )
        records = cls._mastered_records_from_storage(database)
        if isinstance(database, list) and not records:
            return issues
        if not records:
            if isinstance(database, dict) and database.get("records") == {}:
                return issues
            issues.append({"id": None, "field": "records", "message": "records must be an object or array"})
            return issues
        used_identifiers: set[str] = set()
        for index, (stored_identifier, record) in enumerate(records):
            if stored_identifier is not None and not isinstance(stored_identifier, str):
                issues.append(
                    {"id": None, "field": "records", "message": "record keys must be strings"}
                )
                continue
            if not isinstance(record, dict):
                issues.append({"id": stored_identifier, "field": None, "message": "record must be an object"})
                continue
            identifier = cls._mastered_identifier(record, index, used_identifiers)
            if stored_identifier is not None and record.get("id") not in {None, identifier}:
                issues.append(
                    {"id": identifier, "field": "id", "message": "record id must match its object key"}
                )
            category = record.get("category", cls.MASTERED_CATEGORY)
            if category not in CATEGORIES:
                issues.append(
                    {"id": identifier, "field": "category", "message": "category is invalid"}
                )
            if record.get("status", "mastered") != "mastered":
                issues.append(
                    {"id": identifier, "field": "status", "message": "status must be mastered"}
                )
            for field in ("title", "explanation"):
                if not isinstance(record.get(field), str) or not record[field].strip():
                    issues.append(
                        {"id": identifier, "field": field, "message": f"{field} must not be empty"}
                    )
            if "source" in record and (
                not isinstance(record.get("source"), str) or not record["source"].strip()
            ):
                issues.append(
                    {"id": identifier, "field": "source", "message": "source must not be empty"}
                )
            if "example" in record and not isinstance(record.get("example", ""), str):
                issues.append(
                    {"id": identifier, "field": "example", "message": "example must be a string"}
                )
            tags = record.get("tags")
            if tags is not None:
                if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                    issues.append(
                        {"id": identifier, "field": "tags", "message": "tags must be an array of strings"}
                    )
                elif len(tags) != len({tag.casefold() for tag in tags}):
                    issues.append(
                        {"id": identifier, "field": "tags", "message": "tags must not contain duplicates"}
                    )
            try:
                mastered_at = parse_timestamp(record.get("mastered_at"))
                if mastered_at is None:
                    raise ValueError("mastered_at is required")
            except (TypeError, ValueError):
                issues.append(
                    {
                        "id": identifier,
                        "field": "mastered_at",
                        "message": "mastered_at must be an ISO timestamp with timezone",
                    }
                )
        return issues

    @classmethod
    def _hydrate_mastered_database(cls, database: Any) -> dict[str, Any]:
        issues = cls._validate_mastered_database(database)
        if issues:
            raise RecordError(f"mastered database is invalid: {issues[0]['message']}")
        records = {}
        used_identifiers: set[str] = set()
        for index, (_stored_identifier, record) in enumerate(
            cls._mastered_records_from_storage(database)
        ):
            identifier = cls._mastered_identifier(record, index, used_identifiers)
            mastered_at = record["mastered_at"]
            records[identifier] = {
                "id": identifier,
                "category": record.get("category", cls.MASTERED_CATEGORY),
                "status": "mastered",
                "title": record["title"],
                "explanation": record["explanation"],
                "source": record.get("source") or record["explanation"],
                "example": record.get("example", ""),
                "tags": record.get("tags", []),
                "first_learned_at": mastered_at,
                "last_learned_at": mastered_at,
                "learned_count": 1,
                "mastery_score": 10.0,
                "review_count": 0,
                "high_score_streak": 1,
                "last_reviewed_at": mastered_at,
                "next_review_at": None,
                "lapse_count": 0,
                "mastered_at": mastered_at,
                "review_history": [],
            }
        hydrated = {
            "schema_version": database.get("schema_version", 2)
            if isinstance(database, dict)
            else 2,
            "revision": database.get("revision", 0) if isinstance(database, dict) else 0,
            "records": dict(sorted(records.items())),
        }
        full_issues = validate_database(hydrated)
        if full_issues:
            raise RecordError(f"mastered database is invalid: {full_issues[0]['message']}")
        return hydrated

    @classmethod
    def _slim_mastered_database(cls, database: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                field: record[field]
                for field in cls.MASTERED_FIELDS
                if field in record
            }
            for _identifier, record in sorted(database["records"].items())
        ]

    @staticmethod
    def _merge_databases(
        primary: dict[str, Any], mastered: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        mastered = mastered or empty_database()
        records = {**primary.get("records", {})}
        overlap = set(records).intersection(mastered.get("records", {}))
        if overlap:
            raise RecordError(f"record exists in both databases: {sorted(overlap)[0]}")
        records.update(mastered.get("records", {}))
        return {
            "schema_version": primary.get("schema_version"),
            "revision": max(
                int(primary.get("revision", 0)),
                int(mastered.get("revision", 0)),
            ),
            "records": dict(sorted(records.items())),
        }

    def _load(self, *, allow_missing: bool = False) -> dict[str, Any]:
        primary = self._read_database_file(self.data_path, allow_missing=allow_missing)
        mastered = self._read_mastered_database_file(self.mastered_path)
        return self._merge_databases(primary, mastered)

    def _read_unvalidated_file(self, path: Path, *, allow_missing: bool = False) -> dict[str, Any]:
        if not path.exists():
            if allow_missing:
                return empty_database()
            raise RecordError(f"record database does not exist: {path}")
        try:
            with path.open(encoding="utf-8") as handle:
                database = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordError(f"cannot read valid JSON from {path}: {exc}") from exc
        return database

    def read_unvalidated(self) -> dict[str, Any]:
        primary = self._read_unvalidated_file(self.data_path)
        mastered = (
            self._read_mastered_database_file(self.mastered_path)
            if self.mastered_path.exists()
            else empty_database()
        )
        return self._merge_databases(primary, mastered)

    def read(self) -> dict[str, Any]:
        return self._load()

    def _load_review_claims(self) -> dict[str, Any]:
        if not self.review_claims_path.exists():
            return {"claims": {}}
        try:
            with self.review_claims_path.open(encoding="utf-8") as handle:
                claims = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordError(
                f"cannot read valid JSON from {self.review_claims_path}: {exc}"
            ) from exc
        if not isinstance(claims, dict) or not isinstance(claims.get("claims"), dict):
            raise RecordError("review claims file is invalid")
        return claims

    def _write_review_claims(self, claims: dict[str, Any]) -> None:
        import tempfile

        self.review_claims_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".review-claims.", suffix=".tmp", dir=self.review_claims_path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(claims, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.review_claims_path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def _write_file(
        self,
        path: Path,
        database: Any,
        *,
        fail_before_replace: bool,
        validate: Callable[[Any], list[dict[str, Any]]] = validate_database,
    ) -> None:
        import tempfile

        issues = validate(database)
        if issues:
            raise RecordError(f"refusing to write invalid records: {issues[0]['message']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        file_mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(database, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if fail_before_replace and os.environ.get("LEARN_ENGLISH_FAIL_BEFORE_REPLACE") == "1":
                raise RecordError("injected failure before atomic replace")
            os.chmod(temporary_name, file_mode)
            os.replace(temporary_name, path)
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    def _split_databases(self, database: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        records = dict(sorted(database["records"].items()))
        mastered_records = {
            identifier: record
            for identifier, record in records.items()
            if record["status"] == "mastered"
        }
        spill_mastered = (
            self.mastered_path.exists()
            or len(mastered_records) >= self.MASTERED_SPILLOVER_THRESHOLD
        )
        primary_records = {
            identifier: record
            for identifier, record in records.items()
            if record["status"] != "mastered" or not spill_mastered
        }
        if not spill_mastered:
            mastered_records = {}
        primary = {
            "schema_version": database["schema_version"],
            "revision": database["revision"],
            "records": dict(sorted(primary_records.items())),
        }
        mastered = {
            "schema_version": database["schema_version"],
            "revision": database["revision"],
            "records": dict(sorted(mastered_records.items())),
        }
        return primary, mastered

    def _write(self, database: dict[str, Any]) -> None:
        primary, mastered = self._split_databases(database)
        if mastered["records"] or self.mastered_path.exists():
            self._write_file(
                self.mastered_path,
                self._slim_mastered_database(mastered),
                fail_before_replace=False,
                validate=self._validate_mastered_database,
            )
        self._write_file(self.data_path, primary, fail_before_replace=True)

    def initialize(
        self,
        database: dict[str, Any],
        *,
        before_write: Callable[[], None] | None = None,
        after_write: Callable[[], None] | None = None,
    ) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        if self.data_path.exists():
            raise RecordError(f"record database already exists: {self.data_path}")
        if before_write:
            before_write()
        self._write(database)
        if after_write:
            after_write()

    def transaction(
        self,
        operation: Callable[[dict[str, Any]], T],
        *,
        before_write: Callable[[], None] | None = None,
        after_write: Callable[[], None] | None = None,
    ) -> T:
        with self._exclusive_lock():
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            if before_write:
                before_write()
            database = self._load()
            result = operation(database)
            database["revision"] += 1
            database["records"] = dict(sorted(database["records"].items()))
            self._write(database)
            if after_write:
                after_write()
            return result

    def review_claims_transaction(
        self,
        operation: Callable[[dict[str, Any], dict[str, Any]], T],
    ) -> T:
        with self._exclusive_lock():
            database = self._load()
            claims = self._load_review_claims()
            result = operation(database, claims)
            self._write_review_claims(claims)
            return result

    def transaction_unvalidated(
        self,
        operation: Callable[[dict[str, Any]], T],
        *,
        before_write: Callable[[], None] | None = None,
        after_write: Callable[[], None] | None = None,
    ) -> T:
        with self._exclusive_lock():
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            if before_write:
                before_write()
            database = self.read_unvalidated()
            result = operation(database)
            database["revision"] = int(database.get("revision", 0)) + 1
            database["records"] = dict(sorted(database["records"].items()))
            self._write(database)
            if after_write:
                after_write()
            return result

    def replace(
        self,
        database: dict[str, Any],
        *,
        before_write: Callable[[], None] | None = None,
        after_write: Callable[[], None] | None = None,
    ) -> None:
        with self._exclusive_lock():
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            if before_write:
                before_write()
            database["revision"] = int(database.get("revision", 0)) + 1
            database["records"] = dict(sorted(database["records"].items()))
            self._write(database)
            if after_write:
                after_write()
