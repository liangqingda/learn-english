"""Atomic JSON persistence for learning records."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, TypeVar

from .models import RecordError, empty_database, validate_database


T = TypeVar("T")


class RecordStore:
    MASTERED_SPILLOVER_THRESHOLD = 10

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
        mastered = (
            self._read_database_file(self.mastered_path)
            if self.mastered_path.exists()
            else empty_database()
        )
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
            self._read_unvalidated_file(self.mastered_path)
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

    def _write_file(self, path: Path, database: dict[str, Any], *, fail_before_replace: bool) -> None:
        import tempfile

        issues = validate_database(database)
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
            self._write_file(self.mastered_path, mastered, fail_before_replace=False)
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
