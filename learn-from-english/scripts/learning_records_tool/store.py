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
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        self.data_path = self.repo_root / "learning-records" / "records.json"
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

    def _load(self, *, allow_missing: bool = False) -> dict[str, Any]:
        if not self.data_path.exists():
            if allow_missing:
                return empty_database()
            raise RecordError(
                f"record database does not exist: {self.data_path}; run migrate-v2 first"
            )
        try:
            with self.data_path.open(encoding="utf-8") as handle:
                database = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordError(f"cannot read valid JSON from {self.data_path}: {exc}") from exc
        issues = validate_database(database)
        if issues:
            raise RecordError(f"record database is invalid: {issues[0]['message']}")
        return database

    def read_unvalidated(self) -> dict[str, Any]:
        if not self.data_path.exists():
            raise RecordError(f"record database does not exist: {self.data_path}")
        try:
            with self.data_path.open(encoding="utf-8") as handle:
                database = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordError(f"cannot read valid JSON from {self.data_path}: {exc}") from exc
        return database

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

    def _write(self, database: dict[str, Any]) -> None:
        import tempfile

        issues = validate_database(database)
        if issues:
            raise RecordError(f"refusing to write invalid records: {issues[0]['message']}")
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        file_mode = self.data_path.stat().st_mode & 0o777 if self.data_path.exists() else 0o644
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".records.", suffix=".tmp", dir=self.data_path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(database, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if os.environ.get("LEARN_ENGLISH_FAIL_BEFORE_REPLACE") == "1":
                raise RecordError("injected failure before atomic replace")
            os.chmod(temporary_name, file_mode)
            os.replace(temporary_name, self.data_path)
            directory_fd = os.open(self.data_path.parent, os.O_RDONLY)
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
