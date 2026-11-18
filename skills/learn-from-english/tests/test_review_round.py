"""一个调用完成一轮复习：record + 笔记 + 校验 + 菜单。

这些用例只验证 `review-round` 组合出的写入与单独命令一致，以及失败时能
分清「记录已写、笔记未写」，不重复测 note.py 的格式规则。

The composite runs the note writer as a subprocess, so the temporary repo
points `LEARN_ENGLISH_NOTE_CLI` at the real script while `LEARN_ENGLISH_REPO_ROOT`
stays on the temp directory.
"""

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

from learning_records_tool.models import empty_database  # noqa: E402
from learning_records_tool.round_flow import note_check  # noqa: E402
from learning_records_tool.store import RecordStore  # noqa: E402


def _repo_root() -> Path:
    """向上找 ``contract.json``：测试不跟着技能目录的深度走。"""
    for parent in SCRIPT_DIR.parents:
        if (parent / "contract.json").is_file():
            return parent
    raise RuntimeError("contract.json not found above the scripts directory")


REPO_ROOT = _repo_root()
SCRIPT = SCRIPT_DIR / "learning_records.py"
NOTE_CLI = REPO_ROOT / "skills" / "take-english-study-notes" / "scripts" / "note.py"

NOTE_FILE = "learning-record-notes/errors/errors-out-west.md"

EXPLAIN = """## 基础信息

<table style="border-collapse:collapse;width:auto">
<colgroup><col width="150"><col></colgroup>
<tr><td>记录 ID / 试卷 ID</td><td>errors:out-west</td></tr>
<tr><td>目标知识点</td><td>out west 不是 outwest</td></tr>
<tr><td>累计复习次数</td><td>2</td></tr>
<tr><td>下次复习</td><td>2026-11-23 09:00</td></tr>
<tr><td>笔记生成时间</td><td>2026-11-09 09:05</td></tr>
<tr><td>笔记更新时间</td><td>2026-11-09 09:05</td></tr>
</table>

## 讲解

**错误机制**：out west 是「方位副词 + 方位副词」的固定搭配，英语把两个方位词各自当成独立单位，写成一个词就破坏了这件事。

**正确表达**：They drove out west last spring.（他们去年春天往西开去了）
"""

BODY = """## 本轮习题

<table style="border-collapse:collapse;width:auto">
<colgroup><col width="150"><col></colgroup>
<tr><td>生成时间</td><td>2026-11-16 21:30</td></tr>
<tr><td>分类 · 状态变化</td><td>errors · learning → familiar</td></tr>
<tr><td>本轮得分</td><td>10 / 10</td></tr>
<tr><td>题量与错题数</td><td>1 题 / 0 处错误</td></tr>
</table>

### 1. 填空

**题目**：He drove out ___.

**我的答案**：west

**判定**：✅ 正确

<details>
<summary>知识点讲解</summary>

1. **本题知识点**：out west 是固定搭配
2. **规则与机制**：方位副词连用，不合并成一个词
3. **英语的表达逻辑**：英语用两个独立方位词表示方向
4. **可迁移表达**：They headed out east.
</details>
"""


COMPARE_SECTION = {
    "title": "## 对比 out west 与 west",
    "content": (
        "## 对比 out west 与 west\n\n"
        "**讲解要点**：\n\n"
        "- 目标表达\n  - They drove out west.（他们往西开去了）\n"
    ),
}


def body_at(stamp: str) -> str:
    """Same round body, with its `生成时间` stamp moved so it reads as another round."""
    return BODY.replace("2026-11-16 21:30", stamp)


def record_payload(key: str = "out-west") -> dict[str, object]:
    return {
        "category": "errors",
        "key": key,
        "title": "out west 不是 outwest",
        "explanation": "方位副词连用，写成一个词是拼写错误。",
        "source": "They drove out west last spring.",
        "example": "We headed out west after lunch.",
        "tags": ["preposition"],
    }


class ReviewRoundTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)
        RecordStore(self.repo).initialize(empty_database())

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "LEARN_ENGLISH_REPO_ROOT": str(self.repo),
            "LEARN_ENGLISH_NOTE_CLI": str(NOTE_CLI),
        }

    def cli(self, args: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            input=stdin_text,
            capture_output=True,
            text=True,
            env=self.env(),
            check=False,
        )

    def review_round(self, payload: dict[str, object]) -> subprocess.CompletedProcess:
        return self.cli(["review-round", "--input", "-"], json.dumps(payload))

    def seed_record(self) -> None:
        self.cli(["upsert", "--category", "errors", "--key", "out-west",
                  "--title", "out west 不是 outwest",
                  "--explanation", "方位副词连用，写成一个词是拼写错误。",
                  "--source", "They drove out west last spring.",
                  "--example", "We headed out west after lunch.",
                  "--tag", "preposition"])

    def round_payload(self, **note_overrides: object) -> dict[str, object]:
        note = {
            "file": NOTE_FILE,
            "date": "2026-11-16",
            "time": "21:30",
            "kind": "复习",
            "body": BODY,
            "explain": {"content": EXPLAIN},
        }
        note.update(note_overrides)
        return {
            "review": {"id": "errors:out-west", "score": 10, "errors": []},
            "note": note,
            "menu": {"context": "review-complete", "focus": "out west"},
        }

    # ---- 正常路径 -------------------------------------------------

    def test_one_call_writes_record_note_and_menu(self) -> None:
        self.seed_record()
        completed = self.review_round(self.round_payload())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["steps"], ["review", "note", "menu"])
        self.assertEqual(payload["review"]["review_count"], 1)
        self.assertEqual(
            payload["note"]["block"]["heading"], "# 2026-11-16 21:30 · 复习"
        )
        self.assertTrue(payload["note"]["explain_written"])
        self.assertTrue(payload["check_ok"])
        note = (self.repo / NOTE_FILE).read_text(encoding="utf-8")
        self.assertIn("## 讲解", note)
        self.assertIn("## 本轮习题", note)
        self.assertTrue(payload["menu"]["options"])

    def test_repeating_the_same_round_is_reported_as_duplicate(self) -> None:
        self.seed_record()
        first = self.review_round(self.round_payload())
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.review_round(self.round_payload())
        self.assertEqual(second.returncode, 0, second.stderr)
        payload = json.loads(second.stdout)
        self.assertTrue(payload["note"]["block"]["duplicate"])
        note = (self.repo / NOTE_FILE).read_text(encoding="utf-8")
        self.assertEqual(note.count("# 2026-11-16 21:30 · 复习"), 1)

    def test_retrying_the_same_payload_skips_the_explanation_writes(self) -> None:
        self.seed_record()
        payload = self.round_payload(explain_sections=[COMPARE_SECTION])
        first = self.review_round(payload)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.review_round(payload)
        self.assertEqual(second.returncode, 0, second.stderr)
        answer = json.loads(second.stdout)
        self.assertTrue(answer["note"]["already_saved"])
        self.assertTrue(answer["note"]["skipped_explain"])
        note = (self.repo / NOTE_FILE).read_text(encoding="utf-8")
        self.assertEqual(
            note.count("They drove out west.（他们往西开去了）"), 1,
            "原样重试不能把同一段讲解再加一遍",
        )

    def test_a_repeated_section_is_not_recorded_twice(self) -> None:
        self.seed_record()
        first = self.review_round(self.round_payload(explain_sections=[COMPARE_SECTION]))
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.review_round(
            self.round_payload(
                time="21:31", body=body_at("2026-11-16 21:31"),
                explain_sections=[COMPARE_SECTION],
            )
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        answer = json.loads(second.stdout)
        self.assertTrue(answer["note"]["explain_sections"][0]["duplicate"])
        note = (self.repo / NOTE_FILE).read_text(encoding="utf-8")
        self.assertEqual(note.count("## 对比 out west 与 west"), 1)
        self.assertEqual(
            note.count("They drove out west.（他们往西开去了）"), 1,
            "讲解要点只能有一份，重复选中不追加",
        )

    def test_another_story_block_goes_in_through_explain_parts(self) -> None:
        self.seed_record()
        first = self.review_round(self.round_payload(explain_sections=[COMPARE_SECTION]))
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.review_round(
            self.round_payload(
                time="21:31", body=body_at("2026-11-16 21:31"),
                explain_parts=[{
                    "title": "## 对比 out west 与 west",
                    "content": "- 另一段\n  - We headed out west.（我们往西出发了）",
                }],
            )
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        answer = json.loads(second.stdout)
        self.assertEqual(answer["note"]["explain_parts"][0]["title"], "## 对比 out west 与 west")
        note = (self.repo / NOTE_FILE).read_text(encoding="utf-8")
        self.assertEqual(note.count("## 对比 out west 与 west"), 1)
        self.assertIn("We headed out west.（我们往西出发了）", note)

    def test_explain_parts_refuses_a_fragment_that_carries_a_heading(self) -> None:
        self.seed_record()
        first = self.review_round(self.round_payload(explain_sections=[COMPARE_SECTION]))
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.review_round(
            self.round_payload(
                time="21:31", body=body_at("2026-11-16 21:31"),
                explain_parts=[{
                    "title": "## 对比 out west 与 west",
                    "content": "## 又一节\n\n正文",
                }],
            )
        )
        self.assertEqual(second.returncode, 1, "补段只能给正文，带标题要拒")
        self.assertEqual(json.loads(second.stdout)["failed_step"], "note")

    # ---- 失败路径 -------------------------------------------------

    def test_note_without_explanation_needs_explain_content(self) -> None:
        self.seed_record()
        payload = self.round_payload()
        payload["note"].pop("explain")  # type: ignore[union-attr]
        completed = self.review_round(payload)
        self.assertEqual(completed.returncode, 1)
        answer = json.loads(completed.stdout)
        self.assertFalse(answer["ok"])
        self.assertEqual(answer["failed_step"], "note")
        self.assertIn("## 讲解", answer["error"])
        self.assertIn("review", answer["steps"], "记录已经写进去了，必须如实报告")
        self.assertTrue(answer["menu"]["options"], "笔记失败也要给出下一步菜单")
        self.assertFalse((self.repo / NOTE_FILE).exists())

    def test_a_broken_index_is_auto_fixed_before_reporting(self) -> None:
        self.seed_record()
        first = self.review_round(self.round_payload())
        self.assertEqual(first.returncode, 0, first.stderr)
        target = self.repo / NOTE_FILE
        broken = target.read_text(encoding="utf-8").replace("复习历史：", "复习历史（手改坏了）：", 1)
        target.write_text(broken, encoding="utf-8")
        report = note_check(NOTE_CLI, NOTE_FILE, self.repo)
        self.assertTrue(report["ok"], report)
        self.assertIn("auto_fixed", report, "派生索引坏了要先修再报")
        self.assertIn("复习历史：", target.read_text(encoding="utf-8"))

    def test_missing_body_is_refused_before_any_write(self) -> None:
        self.seed_record()
        completed = self.review_round(self.round_payload(body="   "))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("note.body is required", completed.stderr)

    def test_unknown_kind_is_refused(self) -> None:
        self.seed_record()
        completed = self.review_round(self.round_payload(kind="复盘"))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("note.kind must be one of", completed.stderr)

    def test_record_only_round_skips_the_note(self) -> None:
        self.seed_record()
        completed = self.review_round({"review": {"id": "errors:out-west", "score": 8}})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["steps"], ["review"])
        self.assertNotIn("note", payload)


if __name__ == "__main__":
    unittest.main()
