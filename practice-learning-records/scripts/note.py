#!/usr/bin/env python3
"""复习笔记统一入口，把「写」和「校验」收进同一个 skill。

用法：
    python3 practice-learning-records/scripts/note.py append --file <note.md> --content-file - [--check]
    python3 practice-learning-records/scripts/note.py append-section --file <note.md> --heading "<# ...>" --content-file - [--check]
    python3 practice-learning-records/scripts/note.py replace --file <note.md> --heading "<# ...>" --content-file -
    python3 practice-learning-records/scripts/note.py sections --file <note.md> [--section "## <小节标题>"]
    python3 practice-learning-records/scripts/note.py check --all [--fix]

`append` / `replace` / `sections` 会转发到 learn-from-english 的 learning_records.py：
先看 `$LEARN_ENGLISH_CLI`，再看 `$LEARN_ENGLISH_REPO_ROOT` 与仓库内同级目录，
最后看 `~/.agents/skills/learn-from-english` 等安装位。找不到时明确报错，不静默降级。
`check` 始终使用本 skill 自带的 check_note.py，因此只安装 practice-learning-records 也能校验。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

COMMANDS = {
    "append": "note-append",
    "append-section": "note-append-section",
    "replace": "note-replace-block",
    "sections": "note-sections",
}

CHECK_COMMANDS = ("check", "validate")


def repo_root() -> Path:
    override = os.environ.get("LEARN_ENGLISH_REPO_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def cli_candidates() -> list[Path]:
    candidates: list[Path] = []
    override = os.environ.get("LEARN_ENGLISH_CLI")
    if override:
        candidates.append(Path(override).expanduser())
    candidates.append(repo_root() / "learn-from-english" / "scripts" / "learning_records.py")
    for root in (
        Path.home() / ".agents" / "skills",
        Path.home() / ".claude" / "skills",
        Path.home() / "Doubao" / "skills",
    ):
        candidates.append(root / "learn-from-english" / "scripts" / "learning_records.py")
    return candidates


def locate_cli() -> Path | None:
    for candidate in cli_candidates():
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def fail(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, indent=2))
    return 2


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        print(__doc__)
        return 2
    command = args[0]
    if command in CHECK_COMMANDS:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import check_note  # noqa: PLC0415 - 本目录内脚本，按需导入避免 --help 之外的依赖

        return check_note.main([argv[0]] + args[1:])
    target = COMMANDS.get(command)
    if target is None:
        return fail(f"unknown command: {command}; expected {', '.join([*COMMANDS, *CHECK_COMMANDS])}")
    cli = locate_cli()
    if cli is None:
        probed = [str(path) for path in cli_candidates()]
        return fail(
            "learning_records.py not found; install learn-from-english or set LEARN_ENGLISH_CLI "
            f"(probed: {', '.join(probed)})"
        )
    os.execv(sys.executable, [sys.executable, str(cli), target, *args[1:]])
    return 0  # pragma: no cover - execv replaces the process


if __name__ == "__main__":
    sys.exit(main(sys.argv))
