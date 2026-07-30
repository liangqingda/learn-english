"""Scoped Git commits for record mutations."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .models import RecordError


def ensure_paths_clean(repo_root: Path, paths: Iterable[Path], *, enabled: bool) -> None:
    if not enabled or not (repo_root / ".git").exists():
        return
    relative_paths = [str(path.resolve().relative_to(repo_root.resolve())) for path in paths]
    import subprocess

    try:
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "--", *relative_paths],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RecordError(f"Git status failed before record update: {exc}") from exc
    if status.stdout.strip():
        raise RecordError(
            "record database has uncommitted changes; commit them or set "
            "LEARN_ENGLISH_AUTO_COMMIT=0 before updating"
        )


def commit_paths(repo_root: Path, reason: str, paths: Iterable[Path], *, enabled: bool) -> None:
    if not enabled or not (repo_root / ".git").exists():
        return
    relative_paths = []
    for path in dict.fromkeys(paths):
        try:
            relative_paths.append(str(path.resolve().relative_to(repo_root.resolve())))
        except ValueError as exc:
            raise RecordError(f"record path is outside the repository: {path}") from exc
    if not relative_paths:
        return
    import subprocess

    try:
        status = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "--", *relative_paths],
            check=True,
            capture_output=True,
            text=True,
        )
        if not status.stdout.strip():
            return
        subprocess.run(
            ["git", "-C", str(repo_root), "add", "--", *relative_paths],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "commit",
                "--only",
                "-m",
                f"[records]: {reason}",
                "--",
                *relative_paths,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise RecordError(
            f"records were saved, but automatic Git commit failed: {detail or exc}"
        ) from exc
