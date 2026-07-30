"""Atomic JSON persistence for learning records."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, TypeVar

from .models import RecordError, empty_database, validate_database


T = TypeVar("T")


class RecordStore:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        self.data_path = self.repo_root / "learning-records" / "records.json"

    def exists(self) -> bool:
        return self.data_path.exists()

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

    def _write(self, database: dict[str, Any]) -> None:
        import tempfile

        issues = validate_database(database)
        if issues:
            raise RecordError(f"refusing to write invalid records: {issues[0]['message']}")
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
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

    def transaction_unvalidated(
        self,
        operation: Callable[[dict[str, Any]], T],
        *,
        before_write: Callable[[], None] | None = None,
        after_write: Callable[[], None] | None = None,
    ) -> T:
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
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        if before_write:
            before_write()
        database["revision"] = int(database.get("revision", 0)) + 1
        database["records"] = dict(sorted(database["records"].items()))
        self._write(database)
        if after_write:
            after_write()
