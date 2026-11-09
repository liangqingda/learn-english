"""追踪字段由记录推导：这部分属于记录域，留在 learn-from-english。"""

from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from learning_records_tool.service import RecordService  # noqa: E402


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

    def test_next_review_display_ignores_the_machine_timezone(self) -> None:
        """追踪表里的「下次复习」按记录自带偏移排版，换台机器也不能变成别的时间。"""
        record = {
            "id": "errors:out-west",
            "category": "errors",
            "title": "out west 不是 outwest",
            "status": "familiar",
            "review_count": 2,
            "next_review_at": "2026-11-20T20:54:00+08:00",
        }
        if not hasattr(time, "tzset"):
            self.skipTest("tzset() is POSIX-only")
        saved = os.environ.get("TZ")
        try:
            for zone in ("UTC", "America/New_York", "Asia/Shanghai"):
                os.environ["TZ"] = zone
                time.tzset()
                tracking = RecordService(self.StubStore({"errors:out-west": record})).note_context(
                    "errors:out-west"
                )["tracking"]
                self.assertEqual(tracking["下次复习"], "2026-11-20 20:54", f"TZ={zone}")
        finally:
            if saved is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = saved
            time.tzset()

    def test_unreviewed_record_uses_placeholder_values(self) -> None:
        record = {"id": "errors:new", "category": "errors", "title": "t", "status": "learning", "review_history": []}
        service = RecordService(self.StubStore({"errors:new": record}))
        tracking = service.note_context("errors:new")["tracking"]
        self.assertEqual(tracking["分类 · 状态变化"], "errors · 未评分")
        self.assertEqual(tracking["本轮得分"], "—")
        self.assertEqual(tracking["下次复习"], "—")


if __name__ == "__main__":
    unittest.main()
