"""Atomic JSON persistence for learning records."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, TypeVar

from .models import (
    CATEGORIES,
    SCHEMA_VERSION,
    RecordError,
    empty_database,
    normalize_key,
    parse_timestamp,
    validate_database,
)


T = TypeVar("T")


class RecordStore:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        self.learning_dir = self.repo_root / "learning-records"
        self.mastered_dir = self.repo_root / "mastered-learning-records"
        self.legacy_data_path = self.learning_dir / "records.json"
        self.legacy_mastered_path = self.learning_dir / "mastered.json"
        self.data_path = self.legacy_data_path
        self.mastered_path = self.legacy_mastered_path
        self.review_claims_path = self.learning_dir / ".review-claims.json"

    def category_path(self, category: str) -> Path:
        self._require_category(category)
        return self.learning_dir / f"{category}.json"

    def mastered_category_path(self, category: str) -> Path:
        self._require_category(category)
        return self.mastered_dir / f"{category}.json"

    @staticmethod
    def _require_category(category: str) -> None:
        if category not in CATEGORIES:
            raise RecordError(
                f"invalid category {category!r}; expected one of: {', '.join(CATEGORIES)}"
            )

    def exists(self) -> bool:
        return (
            self.legacy_data_path.exists()
            or any(self.category_path(category).exists() for category in CATEGORIES)
            or any(self.mastered_category_path(category).exists() for category in CATEGORIES)
        )

    def _uses_category_layout(self) -> bool:
        return any(self.category_path(category).exists() for category in CATEGORIES) or any(
            self.mastered_category_path(category).exists() for category in CATEGORIES
        )

    @contextmanager
    def _exclusive_lock(self):
        import fcntl

        self.learning_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.learning_dir / ".records.lock"
        with lock_path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _empty_category_database(category: str, revision: int = 0) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "revision": revision,
            "category": category,
            "records": {},
        }

    @staticmethod
    def _category_database(
        category: str,
        records: dict[str, dict[str, Any]],
        revision: int,
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "revision": revision,
            "category": category,
            "records": dict(sorted(records.items())),
        }

    @staticmethod
    def _validate_category_database(
        database: Any,
        category: str,
        *,
        allow_mastered: bool,
    ) -> list[dict[str, Any]]:
        issues = validate_database(database)
        if issues:
            return issues
        if database.get("category") not in {None, category}:
            return [
                {
                    "id": None,
                    "field": "category",
                    "message": f"file category must be {category}",
                }
            ]
        for identifier, record in database["records"].items():
            if record["category"] != category:
                return [
                    {
                        "id": identifier,
                        "field": "category",
                        "message": f"record category must be {category}",
                    }
                ]
            if not allow_mastered and record["status"] == "mastered":
                return [
                    {
                        "id": identifier,
                        "field": "status",
                        "message": "mastered records belong in mastered-learning-records",
                    }
                ]
        return []

    def _read_database_file(
        self,
        path: Path,
        *,
        allow_missing: bool = False,
        category: str | None = None,
        allow_mastered: bool = True,
    ) -> dict[str, Any]:
        if not path.exists():
            if allow_missing:
                return (
                    self._empty_category_database(category)
                    if category is not None
                    else empty_database()
                )
            raise RecordError(
                f"record database does not exist: {path}; run migrate-v2 first"
            )
        try:
            with path.open(encoding="utf-8") as handle:
                database = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordError(f"cannot read valid JSON from {path}: {exc}") from exc
        issues = (
            self._validate_category_database(
                database,
                category,
                allow_mastered=allow_mastered,
            )
            if category is not None
            else validate_database(database)
        )
        if issues:
            raise RecordError(f"record database is invalid: {issues[0]['message']}")
        return database

    def _read_mastered_database_file(self, path: Path, category: str) -> dict[str, Any]:
        if not path.exists():
            return self._empty_category_database(category)
        try:
            with path.open(encoding="utf-8") as handle:
                database = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordError(f"cannot read valid JSON from {path}: {exc}") from exc
        issues = self._validate_mastered_database(database, category)
        if issues:
            raise RecordError(f"mastered database is invalid: {issues[0]['message']}")
        return self._hydrate_mastered_database(database, category)

    @classmethod
    def _mastered_records_from_storage(
        cls, database: Any
    ) -> list[tuple[str | None, dict[str, Any]]]:
        if isinstance(database, list):
            return [(None, record) for record in database]
        if isinstance(database, dict) and isinstance(database.get("records"), dict):
            return list(database["records"].items())
        return []

    @staticmethod
    def _mastered_identifier(
        record: dict[str, Any],
        category: str,
        fallback_index: int,
        used_identifiers: set[str],
    ) -> str:
        stored_identifier = record.get("id")
        if isinstance(stored_identifier, str) and stored_identifier.strip():
            identifier = stored_identifier
        else:
            title_key = normalize_key(str(record.get("title") or ""))
            suffix = title_key or f"mastered-record-{fallback_index + 1}"
            identifier = f"{category}:{suffix}"
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
    def _validate_mastered_database(
        cls, database: Any, category: str
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        if not isinstance(database, (dict, list)):
            return [
                {
                    "id": None,
                    "field": None,
                    "message": "database root must be an object or array",
                }
            ]
        if isinstance(database, dict):
            if database.get("schema_version") != SCHEMA_VERSION:
                issues.append(
                    {
                        "id": None,
                        "field": "schema_version",
                        "message": f"schema_version must be {SCHEMA_VERSION}",
                    }
                )
            revision = database.get("revision")
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
                issues.append(
                    {
                        "id": None,
                        "field": "revision",
                        "message": "revision must be a non-negative integer",
                    }
                )
            if database.get("category") not in {None, category}:
                issues.append(
                    {
                        "id": None,
                        "field": "category",
                        "message": f"file category must be {category}",
                    }
                )
        records = cls._mastered_records_from_storage(database)
        if isinstance(database, list) and not records:
            return issues
        if not records:
            if isinstance(database, dict) and database.get("records") == {}:
                return issues
            issues.append(
                {
                    "id": None,
                    "field": "records",
                    "message": "records must be an object or array",
                }
            )
            return issues
        used_identifiers: set[str] = set()
        for index, (stored_identifier, record) in enumerate(records):
            if stored_identifier is not None and not isinstance(stored_identifier, str):
                issues.append(
                    {"id": None, "field": "records", "message": "record keys must be strings"}
                )
                continue
            if not isinstance(record, dict):
                issues.append(
                    {"id": stored_identifier, "field": None, "message": "record must be an object"}
                )
                continue
            identifier = cls._mastered_identifier(record, category, index, used_identifiers)
            if not identifier.startswith(f"{category}:"):
                issues.append(
                    {
                        "id": identifier,
                        "field": "id",
                        "message": f"mastered record id must start with {category}:",
                    }
                )
            if stored_identifier is not None and record.get("id") not in {None, identifier}:
                issues.append(
                    {"id": identifier, "field": "id", "message": "record id must match its object key"}
                )
            record_category = record.get("category", category)
            if record_category != category:
                issues.append(
                    {
                        "id": identifier,
                        "field": "category",
                        "message": f"record category must be {category}",
                    }
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
                        {
                            "id": identifier,
                            "field": "tags",
                            "message": "tags must be an array of strings",
                        }
                    )
                elif len(tags) != len({tag.casefold() for tag in tags}):
                    issues.append(
                        {
                            "id": identifier,
                            "field": "tags",
                            "message": "tags must not contain duplicates",
                        }
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
    def _hydrate_mastered_database(cls, database: Any, category: str) -> dict[str, Any]:
        if isinstance(database, dict) and isinstance(database.get("records"), dict):
            database = {**database, "category": category}
            issues = cls._validate_category_database(database, category, allow_mastered=True)
            if not issues and all(
                record["status"] == "mastered"
                for record in database["records"].values()
            ):
                return {
                    **database,
                    "records": dict(sorted(database["records"].items())),
                }

        records = {}
        used_identifiers: set[str] = set()
        for index, (_stored_identifier, record) in enumerate(
            cls._mastered_records_from_storage(database)
        ):
            identifier = cls._mastered_identifier(record, category, index, used_identifiers)
            mastered_at = record["mastered_at"]
            records[identifier] = {
                "id": identifier,
                "category": category,
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
            "schema_version": SCHEMA_VERSION,
            "revision": database.get("revision", 0) if isinstance(database, dict) else 0,
            "category": category,
            "records": dict(sorted(records.items())),
        }
        full_issues = cls._validate_category_database(
            hydrated, category, allow_mastered=True
        )
        if full_issues:
            raise RecordError(f"mastered database is invalid: {full_issues[0]['message']}")
        return hydrated

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
            "schema_version": SCHEMA_VERSION,
            "revision": max(
                int(primary.get("revision", 0)),
                int(mastered.get("revision", 0)),
            ),
            "records": dict(sorted(records.items())),
        }

    def _merge_category_files(
        self,
        reader: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        merged = empty_database()
        invalid_schema_version: Any = None
        for category in CATEGORIES:
            database = reader(category)
            if (
                isinstance(database, dict)
                and database.get("schema_version") != SCHEMA_VERSION
                and invalid_schema_version is None
            ):
                invalid_schema_version = database.get("schema_version")
            merged = self._merge_databases(merged, database)
        if invalid_schema_version is not None:
            merged["schema_version"] = invalid_schema_version
        return merged

    def _load_category_layout(self, *, allow_missing: bool = False) -> dict[str, Any]:
        primary = self._merge_category_files(
            lambda category: self._read_database_file(
                self.category_path(category),
                allow_missing=allow_missing,
                category=category,
                allow_mastered=False,
            )
        )
        mastered = self._merge_category_files(
            lambda category: self._read_mastered_database_file(
                self.mastered_category_path(category),
                category,
            )
        )
        return self._merge_databases(primary, mastered)

    def _load_legacy_layout(self, *, allow_missing: bool = False) -> dict[str, Any]:
        primary = self._read_database_file(self.legacy_data_path, allow_missing=allow_missing)
        mastered = (
            self._read_mastered_database_file(self.legacy_mastered_path, "usage")
            if self.legacy_mastered_path.exists()
            else empty_database()
        )
        return self._merge_databases(primary, mastered)

    def _load(self, *, allow_missing: bool = False) -> dict[str, Any]:
        if self._uses_category_layout():
            return self._load_category_layout(allow_missing=allow_missing)
        return self._load_legacy_layout(allow_missing=allow_missing)

    def _read_unvalidated_file(self, path: Path, *, allow_missing: bool = False) -> Any:
        if not path.exists():
            if allow_missing:
                return empty_database()
            raise RecordError(f"record database does not exist: {path}")
        try:
            with path.open(encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordError(f"cannot read valid JSON from {path}: {exc}") from exc

    def _read_unvalidated_category_database(self, path: Path, category: str) -> dict[str, Any]:
        if not path.exists():
            return self._empty_category_database(category)
        database = self._read_unvalidated_file(path)
        if isinstance(database, dict):
            database.setdefault("category", category)
            return database
        return database

    def read_unvalidated(self) -> dict[str, Any]:
        if not self._uses_category_layout():
            primary = self._read_unvalidated_file(self.legacy_data_path)
            mastered = (
                self._read_mastered_database_file(self.legacy_mastered_path, "usage")
                if self.legacy_mastered_path.exists()
                else empty_database()
            )
            return self._merge_databases(primary, mastered)

        primary = self._merge_category_files(
            lambda category: self._read_unvalidated_category_database(
                self.category_path(category), category
            )
        )
        mastered = self._merge_category_files(
            lambda category: self._read_mastered_database_file(
                self.mastered_category_path(category), category
            )
        )
        merged = self._merge_databases(primary, mastered)
        if primary.get("schema_version") != SCHEMA_VERSION:
            merged["schema_version"] = primary.get("schema_version")
        elif mastered.get("schema_version") != SCHEMA_VERSION:
            merged["schema_version"] = mastered.get("schema_version")
        return merged

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

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    def _current_document(self, path: Path) -> Any | None:
        if not path.exists():
            return None
        return self._read_unvalidated_file(path)

    def _split_databases(
        self, database: dict[str, Any]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        revision = int(database["revision"])
        learning: dict[str, dict[str, Any]] = {}
        mastered: dict[str, list[dict[str, Any]]] = {}
        for category in CATEGORIES:
            learning_records = {
                identifier: record
                for identifier, record in database["records"].items()
                if record["category"] == category and record["status"] != "mastered"
            }
            mastered_records = {
                identifier: record
                for identifier, record in database["records"].items()
                if record["category"] == category and record["status"] == "mastered"
            }
            learning[category] = self._category_database(
                category,
                learning_records,
                revision,
            )
            mastered[category] = self._category_database(
                category,
                mastered_records,
                revision,
            )
        return learning, mastered

    def _write(self, database: dict[str, Any], *, force_all: bool = False) -> None:
        if os.environ.get("LEARN_ENGLISH_FAIL_BEFORE_REPLACE") == "1":
            raise RecordError("injected failure before atomic replace")

        learning, mastered = self._split_databases(database)
        writes: list[tuple[Path, Any, Callable[[Any], list[dict[str, Any]]]]] = []

        for category in CATEGORIES:
            learning_path = self.category_path(category)
            learning_document = learning[category]
            current_learning = self._current_document(learning_path)
            if force_all or self._canonical_json(current_learning) != self._canonical_json(
                learning_document
            ):
                writes.append(
                    (
                        learning_path,
                        learning_document,
                        lambda value, category=category: self._validate_category_database(
                            value, category, allow_mastered=False
                        ),
                    )
                )

            mastered_path = self.mastered_category_path(category)
            mastered_document = mastered[category]
            current_mastered = self._current_document(mastered_path)
            if force_all or current_mastered is not None or mastered_document["records"]:
                if self._canonical_json(current_mastered) != self._canonical_json(mastered_document):
                    writes.append(
                        (
                            mastered_path,
                            mastered_document,
                            lambda value, category=category: self._validate_category_database(
                                value, category, allow_mastered=True
                            ),
                        )
                    )

        for path, document, validator in writes:
            self._write_file(path, document, validate=validator)

    def initialize(
        self,
        database: dict[str, Any],
        *,
        before_write: Callable[[], None] | None = None,
        after_write: Callable[[], None] | None = None,
    ) -> None:
        self.learning_dir.mkdir(parents=True, exist_ok=True)
        self.mastered_dir.mkdir(parents=True, exist_ok=True)
        if self.exists():
            raise RecordError("record database already exists")
        if before_write:
            before_write()
        self._write(database, force_all=True)
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
            self.learning_dir.mkdir(parents=True, exist_ok=True)
            self.mastered_dir.mkdir(parents=True, exist_ok=True)
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
            self.learning_dir.mkdir(parents=True, exist_ok=True)
            self.mastered_dir.mkdir(parents=True, exist_ok=True)
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
            self.learning_dir.mkdir(parents=True, exist_ok=True)
            self.mastered_dir.mkdir(parents=True, exist_ok=True)
            if before_write:
                before_write()
            database["revision"] = int(database.get("revision", 0)) + 1
            database["records"] = dict(sorted(database["records"].items()))
            self._write(database, force_all=True)
            if after_write:
                after_write()
