"""Centralized review-menu policy."""

from __future__ import annotations

from typing import Any

from .models import CATEGORIES, RecordError


REVIEW_PATHS = (
    {
        "id": "errors-grammar",
        "icon": "🧩",
        "label": "复习错题、语法和句型",
        "categories": ("errors", "grammar"),
    },
    {
        "id": "vocabulary-phrases",
        "icon": "📚",
        "label": "复习词汇、搭配和固定表达",
        "categories": ("vocabulary", "phrases"),
    },
    {
        "id": "usage",
        "icon": "🌍",
        "label": "复习语气、自然度和场景选择",
        "categories": ("usage",),
    },
)


def counts_for(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    category_counts = {
        status: {category: 0 for category in CATEGORIES}
        for status in ("learning", "familiar", "mastered")
    }
    for record in records.values():
        category_counts[record["status"]][record["category"]] += 1
    totals = {
        status: sum(category_counts[status].values())
        for status in ("learning", "familiar", "mastered")
    }
    return {"by_status": category_counts, "totals": totals}


def _option(id: str, icon: str, label: str, group: str, **extra: Any) -> dict[str, Any]:
    count = extra.get("count")
    if isinstance(count, int):
        label = f"{label}（{count}）"
    return {"id": id, "icon": icon, "label": label, "group": group, **extra}


def _initial_options(counts: dict[str, Any]) -> list[dict[str, Any]]:
    learning_counts = counts["by_status"]["learning"]
    active = []
    for path in REVIEW_PATHS:
        count = sum(learning_counts[category] for category in path["categories"])
        if count:
            active.append({**path, "categories": list(path["categories"]), "count": count})
    options: list[dict[str, Any]] = []
    if len(active) > 1:
        active = sorted(active, key=lambda item: (item["count"], item["id"]))
        options.append(
            _option(
                "mixed+" + "+".join(item["id"] for item in active),
                active[0]["icon"],
                "综合复习低分知识点",
                "popular",
                kind="review-path",
                categories=[category for item in active for category in item["categories"]],
                count=sum(item["count"] for item in active),
            )
        )
    elif active:
        options.append(_option(group="popular", kind="review-path", **active[0]))
    if counts["totals"]["familiar"]:
        options.append(
            _option(
                "familiar-review",
                "🔁",
                "复习已标熟的知识点",
                "popular",
                kind="familiar-review",
                count=counts["totals"]["familiar"],
            )
        )
    if counts["totals"]["mastered"]:
        options.append(
            _option(
                "mastered-review",
                "🏆",
                "复习已掌握的知识点",
                "popular",
                kind="mastered-review",
                count=counts["totals"]["mastered"],
            )
        )
    if counts["totals"]["mastered"]:
        options.append(
            _option(
                "mastered-cet-paper",
                "📝",
                "生成一套基于已掌握知识点的完整四六级套题（不含听力）",
                "other",
                kind="mastered-cet-paper",
                count=counts["totals"]["mastered"],
            )
        )
    else:
        options.append(
            _option(
                "cet-practice",
                "🧪",
                "做一道 CET-4 仔细阅读单选题",
                "other",
                kind="cet-practice",
            )
        )
    options.append(
        _option(
            "scenario-dialogue",
            "🎭",
            "开始一段在咖啡店与朋友讨论近况的场景对话",
            "other",
            kind="scenario-dialogue",
        )
    )
    return options[:5]


def _follow_up_options(
    counts: dict[str, Any], *, exercise_active: bool, focus: str | None
) -> list[dict[str, Any]]:
    cet_label = "做一道四六级规格纯文本习题"
    scenario_label = "开始一段日常沟通的场景对话"
    options = [
        _option(
            "continue-review",
            "▶️",
            "继续复习，从复习库随机抽一道题",
            "popular",
            kind="continue-review",
            count=counts["totals"]["learning"],
        ),
        _option(
            "familiar-review",
            "🔁",
            "复习已标熟的知识点",
            "popular",
            kind="familiar-review",
            count=counts["totals"]["familiar"],
        ),
    ]
    if counts["totals"]["mastered"] and not exercise_active:
        options.append(
            _option(
                "mastered-review",
                "🏆",
                "复习已掌握的知识点",
                "popular",
                kind="mastered-review",
                count=counts["totals"]["mastered"],
            )
        )
    if exercise_active:
        options.append(
            _option(
                "explain-current-exercise",
                "🔍",
                "讲解当前习题",
                "popular",
                kind="explain-current-exercise",
            )
        )
    options.append(
        _option(
            "cet-practice",
            "🧪",
            cet_label,
            "other",
            kind="cet-practice",
        )
    )
    options.append(
        _option(
            "scenario-dialogue",
            "🎭",
            scenario_label,
            "other",
            kind="scenario-dialogue",
        )
    )
    if not exercise_active and counts["totals"]["mastered"]:
        options.append(
            _option(
                "mastered-cet-paper",
                "📝",
                "生成一套基于已掌握知识点的完整四六级套题（不含听力）",
                "other",
                kind="mastered-cet-paper",
                count=counts["totals"]["mastered"],
            )
        )
    return options[:5]


def build_menu(
    records: dict[str, dict[str, Any]], context: str, *, focus: str | None = None
) -> dict[str, Any]:
    if context not in {"initial", "review-complete", "exercise-active"}:
        raise RecordError(f"invalid menu context: {context}")
    counts = counts_for(records)
    if not records:
        options = [
            _option("status", "📊", "查看当前学习记录状态", "popular", kind="status"),
            _option("cet-practice", "🧪", "做一道 CET-4 仔细阅读单选题", "other", kind="cet-practice"),
            _option("scenario-dialogue", "🎭", "开始一段咖啡店点单的场景对话", "other", kind="scenario-dialogue"),
        ]
        return {"state": "empty", "context": context, "counts": counts, "options": options}
    options = (
        _initial_options(counts)
        if context == "initial"
        else _follow_up_options(
            counts, exercise_active=context == "exercise-active", focus=focus
        )
    )
    return {"state": "ready", "context": context, "counts": counts, "options": options}
