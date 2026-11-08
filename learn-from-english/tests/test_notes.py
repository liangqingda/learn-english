from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from learning_records_tool.models import RecordError  # noqa: E402
from learning_records_tool.notes import NoteStore, _normalize_block  # noqa: E402
from learning_records_tool.service import RecordService  # noqa: E402


SCRIPT = SCRIPT_DIR / "learning_records.py"


def round_block(stamp: str = "2026-11-07 21:00", kind: str = "复习", body: str = "第 1 轮") -> str:
    return (
        f"# {stamp} · {kind}\n"
        '<table style="border-collapse:collapse;width:auto">\n'
        "<colgroup><col width=\"150\"><col></colgroup>\n"
        f"<tr><td>目标知识点</td><td>{body}</td></tr>\n"
        "</table>\n"
    )


class NoteAppendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repo = Path(self.directory.name)
        self.store = NoteStore(self.repo)
        self.note = self.repo / "learning-record-notes" / "errors-out-west.md"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_first_append_creates_block_without_file_level_heading(self) -> None:
        result = self.store.append(self.note, round_block())
        self.assertTrue(result["appended"])
        self.assertEqual(result["blocks"], 1)
        text = self.note.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# 2026-11-07 21:00 · 复习\n"))
        self.assertEqual(text.count("\n---\n"), 0)

    def test_second_append_adds_single_divider_between_blocks(self) -> None:
        self.store.append(self.note, round_block("2026-11-07 21:00"))
        self.store.append(self.note, round_block("2026-11-08 09:30"))
        text = self.note.read_text(encoding="utf-8")
        self.assertEqual(text.count("\n---\n"), 1)
        self.assertEqual(
            result_order(text), ["2026-11-07 21:00", "2026-11-08 09:30"]
        )

    def test_duplicate_heading_is_idempotent(self) -> None:
        self.store.append(self.note, round_block())
        before = self.note.read_bytes()
        result = self.store.append(self.note, round_block())
        self.assertFalse(result["appended"])
        self.assertTrue(result["duplicate"])
        self.assertEqual(self.note.read_bytes(), before)

    def test_duplicate_heading_with_changed_body_keeps_both_rounds(self) -> None:
        self.store.append(self.note, round_block())
        result = self.store.append(self.note, round_block(body="改过的内容"))
        self.assertTrue(result["appended"])
        self.assertTrue(result["heading_adjusted"])
        self.assertEqual(result["requested_heading"], "# 2026-11-07 21:00 · 复习")
        self.assertNotEqual(result["heading"], result["requested_heading"])
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("改过的内容", text)
        self.assertIn("第 1 轮", text)
        self.assertEqual(result["blocks"], 2)
        self.assertLess(
            text.index("# 2026-11-07 21:00 · 复习"),
            text.index(result["heading"]),
        )

    def test_identical_content_with_same_heading_is_a_duplicate(self) -> None:
        self.store.append(self.note, round_block())
        result = self.store.append(self.note, round_block())
        self.assertFalse(result["appended"])
        self.assertTrue(result["duplicate"])
        self.assertEqual(result["blocks"], 1)

    def test_retry_inside_a_multi_block_file_is_still_a_duplicate(self) -> None:
        # 文件里已有两个区块时，第一块后面会带 `---` 分隔符；重试同一轮不能被判成新内容
        self.store.append(self.note, round_block("2026-11-07 21:00"))
        self.store.append(self.note, round_block("2026-11-07 21:05", body="第 2 轮"))
        before = self.note.read_text(encoding="utf-8")
        result = self.store.append(self.note, round_block("2026-11-07 21:00"))
        self.assertTrue(result["duplicate"])
        self.assertFalse(result["appended"])
        self.assertEqual(self.note.read_text(encoding="utf-8"), before)

    def test_relative_and_bare_paths_resolve_to_notes_dir(self) -> None:
        result = self.store.append("errors-out-west.md", round_block())
        self.assertEqual(result["file"], "learning-record-notes/errors-out-west.md")
        self.assertTrue(self.note.exists())

    def test_legacy_file_without_dividers_is_appended_not_reformatted(self) -> None:
        legacy = round_block("2026-11-04 10:00") + round_block("2026-11-05 10:00")
        self.note.parent.mkdir(parents=True, exist_ok=True)
        self.note.write_text(legacy, encoding="utf-8")
        self.store.append(self.note, round_block("2026-11-06 10:00"))
        text = self.note.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(legacy))
        self.assertEqual(text.count("\n---\n"), 1)

    def test_block_must_start_with_a_round_heading(self) -> None:
        for content in ("", "no heading here\n", "## 本轮习题\n", "\n\n"):
            with self.assertRaises(RecordError):
                _normalize_block(content)

    def test_append_rejects_two_rounds_in_one_block(self) -> None:
        with self.assertRaises(RecordError):
            _normalize_block(round_block() + "\n" + round_block("2026-11-08 10:00"))

    def test_path_must_stay_inside_notes_dir(self) -> None:
        outside = self.repo / "learning-record-notes" / "nested" / "x.md"
        with self.assertRaises(RecordError):
            self.store.append(str(outside), round_block())
        with self.assertRaises(RecordError):
            self.store.append("../escape.md", round_block())

    def test_file_name_must_match_slug_convention(self) -> None:
        for name in ("Errors-Out.md", "errors out.md", "errors.md.bak", "notes.txt"):
            with self.assertRaises(RecordError):
                self.store.append(name, round_block())

    def test_symlink_target_is_rejected(self) -> None:
        self.repo.joinpath("learning-record-notes").mkdir(parents=True)
        target = self.repo / "victim.md"
        target.write_text("# 2026-11-07 21:00 · 复习\n", encoding="utf-8")
        link = self.repo / "learning-record-notes" / "errors-victim.md"
        os.symlink(target, link)
        with self.assertRaises(RecordError):
            self.store.append(str(link), round_block())

    def test_lock_file_exists_after_first_write(self) -> None:
        self.store.append(self.note, round_block())
        self.assertTrue((self.repo / "learning-record-notes" / ".notes.lock").exists())

    def test_replace_block_keeps_other_rounds_intact(self) -> None:
        self.store.append(self.note, round_block("2026-11-07 21:00", body="第 1 轮"))
        self.store.append(self.note, round_block("2026-11-08 09:30", body="第 2 轮"))
        self.store.append(self.note, round_block("2026-11-09 09:30", body="第 3 轮"))
        result = self.store.replace_block(
            self.note, "# 2026-11-08 09:30 · 复习", round_block("2026-11-08 09:30", body="修正后")
        )
        self.assertTrue(result["replaced"])
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("修正后", text)
        self.assertNotIn("第 2 轮", text)
        self.assertIn("第 1 轮", text)
        self.assertIn("第 3 轮", text)
        self.assertEqual(
            result_order(text),
            ["2026-11-07 21:00", "2026-11-08 09:30", "2026-11-09 09:30"],
        )

    def test_replace_block_rejects_unknown_or_changed_heading(self) -> None:
        self.store.append(self.note, round_block())
        with self.assertRaises(RecordError):
            self.store.replace_block(self.note, "# 2026-11-10 10:00 · 复习", round_block())
        with self.assertRaises(RecordError):
            self.store.replace_block(
                self.note, "# 2026-11-07 21:00 · 复习", round_block("2026-11-07 22:00")
            )

    def test_replace_block_refuses_ambiguous_heading(self) -> None:
        self.store.append(self.note, round_block())
        self.note.write_text(
            self.note.read_text(encoding="utf-8") + "\n" + round_block(), encoding="utf-8"
        )
        with self.assertRaises(RecordError):
            self.store.replace_block(
                self.note, "# 2026-11-07 21:00 · 复习", round_block()
            )

    def test_check_reports_validator_issues(self) -> None:
        self.store.append(self.note, "# 2026-11-07 21:00 · 复习\n")
        report = self.store.check(self.note)
        self.assertFalse(report["ok"])
        self.assertTrue(report["issues"])

    def test_concurrent_appends_all_survive(self) -> None:
        total = 16
        contents = []
        for index in range(total):
            path = self.repo / f"block-{index}.md"
            # 每轮内容是独立的，避免把不同轮次误判成同一次重试
            path.write_text(
                round_block(f"2026-11-07 21:{index:02d}", body=f"第 {index} 轮"),
                encoding="utf-8",
            )
            contents.append(path)
        environment = dict(os.environ, LEARN_ENGLISH_REPO_ROOT=str(self.repo))
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    str(SCRIPT),
                    "note-append",
                    "--file",
                    "learning-record-notes/errors-out-west.md",
                    "--content-file",
                    str(path),
                ],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for path in contents
        ]
        failures = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=90)
            if process.returncode != 0:
                failures.append(stderr.strip() or stdout.strip())
        self.assertEqual(failures, [])
        text = self.note.read_text(encoding="utf-8")
        stamps = result_order(text)
        self.assertEqual(len(stamps), total)
        self.assertEqual(len(set(stamps)), total)
        self.assertEqual(text.count("\n---\n"), total - 1)
        self.assertFalse(text.startswith("\n"))
        for part in text.split("\n---\n"):
            self.assertTrue(part.lstrip("\n").startswith("# 2026-11-07"))


VALID_BLOCK = """# {heading}
## 基础信息

<details>
<summary>追踪信息</summary>

<table style="border-collapse:collapse;width:auto">
<colgroup><col width="150"><col></colgroup>
<tr><td>记录 ID / 试卷 ID</td><td>errors:out-west</td></tr>
<tr><td>分类 · 状态变化</td><td>errors · learning → familiar</td></tr>
<tr><td>本轮得分</td><td>10 / 10</td></tr>
<tr><td>题量与错题数</td><td>1 题 / 0 处错误</td></tr>
<tr><td>目标知识点</td><td>out west 不是 outwest</td></tr>
<tr><td>累计复习次数</td><td>2</td></tr>
<tr><td>下次复习</td><td>2026-11-23 09:00</td></tr>
<tr><td>笔记生成时间</td><td>2026-11-09 09:05</td></tr>
<tr><td>笔记更新时间</td><td>2026-11-09 09:05</td></tr>
</table>
</details>

## 本轮习题

### 1. 填空

**题目**：He drove out ___.

**我的答案**：{answer}

**判定**：✅ 正确

<details>
<summary>知识点讲解</summary>

1. **本题知识点**：out west 是固定搭配
2. **规则与机制**：方位副词连用，不合并成一个词
3. **英语的表达逻辑**：英语用两个独立方位词表示方向
4. **可迁移表达**：They headed out east.
</details>
"""


class NoteCliTest(unittest.TestCase):
    """命令级用例：校验退出码、stdin 输入、块级替换。"""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)
        self.note = self.repo / "learning-record-notes" / "errors-out-west.md"

    def run_cli(self, args: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
        environment = dict(os.environ, LEARN_ENGLISH_REPO_ROOT=str(self.repo))
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=stdin_text,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )

    def test_cli_accepts_stdin_and_passes_check(self) -> None:
        completed = self.run_cli(
            [
                "note-append",
                "--file",
                "learning-record-notes/errors-out-west.md",
                "--content-file",
                "-",
                "--check",
            ],
            VALID_BLOCK.format(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(self.note.exists())
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["appended"])
        self.assertTrue(payload["check"]["ok"])

    def test_cli_auto_fixes_safe_issues_before_reporting(self) -> None:
        completed = self.run_cli(
            [
                "note-append",
                "--file",
                "learning-record-notes/errors-out-west.md",
                "--content-file",
                "-",
                "--check",
            ],
            VALID_BLOCK.format(heading="2026-11-09 09:00 · 复习", answer="1. west"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["note_status"], "valid")
        self.assertIn("去掉 `我的答案` 的题号前缀", payload["auto_fixed"][0]["fixes"])
        self.assertNotIn("1. west", self.note.read_text(encoding="utf-8"))

    def test_cli_check_failure_sets_nonzero_exit_code(self) -> None:
        completed = self.run_cli(
            [
                "note-append",
                "--file",
                "learning-record-notes/errors-out-west.md",
                "--content-file",
                "-",
                "--check",
            ],
            "# 2026-11-09 09:00 · 复习\n",
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["appended"])
        self.assertEqual(payload["note_status"], "invalid")
        self.assertFalse(payload["check_ok"])
        self.assertFalse(payload["check"]["ok"])
        self.assertTrue(payload["check"]["issues"])

    def test_cli_reports_valid_note_status(self) -> None:
        completed = self.run_cli(
            [
                "note-append",
                "--file",
                "learning-record-notes/errors-out-west.md",
                "--content-file",
                "-",
                "--check",
            ],
            VALID_BLOCK.format(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["note_status"], "valid")
        self.assertTrue(payload["check_ok"])

    def test_new_file_for_a_record_that_already_has_one_is_refused(self) -> None:
        self.run_cli(
            [
                "note-append",
                "--file",
                "learning-record-notes/errors-out-west.md",
                "--content-file",
                "-",
            ],
            VALID_BLOCK.format(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        refused = self.run_cli(
            [
                "note-append",
                "--file",
                "learning-record-notes/errors-out-west-again.md",
                "--content-file",
                "-",
            ],
            VALID_BLOCK.format(heading="2026-11-10 09:00 · 复习", answer="west"),
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("already has a note at learning-record-notes/errors-out-west.md", refused.stderr)
        self.assertFalse((self.repo / "learning-record-notes" / "errors-out-west-again.md").exists())

    def test_cli_replace_block_rewrites_only_that_round(self) -> None:
        for heading in ("2026-11-09 09:00 · 复习", "2026-11-10 09:00 · 复习"):
            completed = self.run_cli(
                [
                    "note-append",
                    "--file",
                    "learning-record-notes/errors-out-west.md",
                    "--content-file",
                    "-",
                ],
                VALID_BLOCK.format(heading=heading, answer="west"),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
        completed = self.run_cli(
            [
                "note-replace-block",
                "--file",
                "learning-record-notes/errors-out-west.md",
                "--heading",
                "# 2026-11-09 09:00 · 复习",
                "--content-file",
                "-",
            ],
            VALID_BLOCK.format(heading="2026-11-09 09:00 · 复习", answer="westward"),
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        text = self.note.read_text(encoding="utf-8")
        self.assertIn("westward", text)
        self.assertIn("2026-11-10 09:00", text)
        self.assertEqual(result_order(text), ["2026-11-09 09:00", "2026-11-10 09:00"])


def result_order(text: str) -> list[str]:
    return [
        line[2:].split(" · ")[0]
        for line in text.split("\n")
        if line.startswith("# 2026-")
    ]


    def test_tracking_rows_are_checked_against_the_record(self) -> None:
        import learning_records_tool.cli as cli_module

        class StubService:
            def note_context(self, identifier: str) -> dict:
                return {
                    "tracking": {
                        "记录 ID / 试卷 ID": "errors:out-west",
                        "分类 · 状态变化": "errors · learning → familiar",
                        "本轮得分": "10 / 10",
                        "目标知识点": "out west 不是 outwest",
                        "累计复习次数": "2",
                        "下次复习": "2026-11-23 09:00",
                        "笔记生成时间": "2026-11-09 09:05",
                        "笔记更新时间": "2026-11-09 09:05",
                    }
                }

        self.run_cli(
            [
                "note-append",
                "--file",
                "learning-record-notes/errors-out-west.md",
                "--content-file",
                "-",
            ],
            VALID_BLOCK.format(heading="2026-11-09 09:00 · 复习", answer="west"),
        )
        original = cli_module.service
        cli_module.service = lambda: StubService()
        try:
            result = cli_module.verify_tracking(
                NoteStore(self.repo), "learning-record-notes/errors-out-west.md", "# 2026-11-09 09:00 · 复习"
            )
        finally:
            cli_module.service = original
        self.assertEqual(result, {})


class NoteContextTest(unittest.TestCase):
    """追踪字段由记录推导，模型不再手抄。"""

    class StubStore:
        def __init__(self, records: dict) -> None:
            self.records_payload = records

        def read(self) -> dict:
            return {"records": self.records_payload}

    def test_tracking_rows_come_from_the_record(self) -> None:
        record = {
            "id": "errors:out-west",
            "category": "errors",
            "title": "out west 不是 outwest",
            "status": "familiar",
            "review_count": 2,
            "next_review_at": "2026-11-20T20:54:00+08:00",
            "review_history": [
                {"score": 9.0, "previous_status": "learning", "new_status": "familiar"}
            ],
        }
        service = RecordService(self.StubStore({"errors:out-west": record}))
        result = service.note_context("errors:out-west")
        self.assertEqual(result["note_file"], "learning-record-notes/errors-out-west.md")
        tracking = result["tracking"]
        self.assertEqual(tracking["分类 · 状态变化"], "errors · learning → familiar")
        self.assertEqual(tracking["本轮得分"], "9 / 10")
        self.assertEqual(tracking["累计复习次数"], "2")
        self.assertEqual(tracking["下次复习"], "2026-11-20 20:54")
        self.assertEqual(tracking["目标知识点"], "out west 不是 outwest")

    def test_unreviewed_record_uses_placeholder_values(self) -> None:
        record = {"id": "errors:new", "category": "errors", "title": "t", "status": "learning", "review_history": []}
        service = RecordService(self.StubStore({"errors:new": record}))
        tracking = service.note_context("errors:new")["tracking"]
        self.assertEqual(tracking["分类 · 状态变化"], "errors · 未评分")
        self.assertEqual(tracking["本轮得分"], "—")
        self.assertEqual(tracking["下次复习"], "—")

if __name__ == "__main__":
    unittest.main()
