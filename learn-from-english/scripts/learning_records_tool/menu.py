"""Centralized review-menu policy."""

from __future__ import annotations

import hashlib
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
        "icon": "🗣️",
        "label": "复习语气、自然度和场景选择",
        "categories": ("usage",),
    },
)

FOLLOW_UP_SUGGESTIONS = (
    (
        "follow-up-grammar",
        "🧩",
        "练习「{focus}」的关键语法结构",
        "follow-up-learning",
    ),
    (
        "follow-up-vocabulary",
        "📚",
        "扩展「{focus}」相关词汇和搭配",
        "follow-up-learning",
    ),
    (
        "follow-up-comparison",
        "🔄",
        "对比「{focus}」和相近表达",
        "follow-up-learning",
    ),
    (
        "follow-up-production",
        "✍️",
        "用「{focus}」做翻译和改写练习",
        "follow-up-learning",
    ),
    (
        "follow-up-pronunciation",
        "🎧",
        "辨析「{focus}」里的发音和重读",
        "follow-up-learning",
    ),
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


def _focus_label(focus: str | None) -> str:
    cleaned = (focus or "").strip()
    return cleaned or "当前英语"


def _follow_up_target(focus: str | None, *, initial: bool = False) -> str:
    if initial and not (focus or "").strip():
        return "日常英语寒暄和近况表达"
    return _focus_label(focus)


def _contextual_follow_ups(
    context: str,
    focus: str | None,
    *,
    count: int,
    initial: bool = False,
) -> list[dict[str, Any]]:
    target = _follow_up_target(focus, initial=initial)
    digest = hashlib.sha256(f"{context}:{target}".encode("utf-8")).digest()
    start = digest[0] % len(FOLLOW_UP_SUGGESTIONS)
    selected = [
        FOLLOW_UP_SUGGESTIONS[(start + index) % len(FOLLOW_UP_SUGGESTIONS)]
        for index in range(min(count, len(FOLLOW_UP_SUGGESTIONS)))
    ]
    return [
        _option(
            id,
            icon,
            label.format(focus=target),
            "other",
            kind=kind,
            focus=target,
        )
        for id, icon, label, kind in selected
    ]


def _scenario_option(focus: str | None, *, initial: bool = False) -> dict[str, Any]:
    target = _focus_label(focus)
    label = (
        "看一套在咖啡店与朋友讨论近况的完整场景对话"
        if initial and not focus
        else f"看一套围绕「{target}」的完整场景对话"
    )
    return _option(
        "scenario-dialogue",
        "🎭",
        label,
        "other",
        kind="scenario-dialogue",
        focus=target,
    )


def _with_dynamic_other_options(
    popular_options: list[dict[str, Any]],
    context: str,
    focus: str | None,
    *,
    initial: bool = False,
) -> list[dict[str, Any]]:
    options = list(popular_options)
    options.extend(_contextual_follow_ups(context, focus, count=2, initial=initial))
    options.append(_scenario_option(focus, initial=initial))
    return options


def _initial_options(
    counts: dict[str, Any],
    *,
    focus: str | None = None,
) -> list[dict[str, Any]]:
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
                "🎯",
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
                "popular",
                kind="mastered-cet-paper",
                count=counts["totals"]["mastered"],
            )
        )
    return _with_dynamic_other_options(options, "initial", focus, initial=True)


def _follow_up_options(
    counts: dict[str, Any],
    context: str,
    *,
    show_error_explanation: bool,
    focus: str | None,
) -> list[dict[str, Any]]:
    has_mastered = bool(counts["totals"]["mastered"])
    include_familiar = not has_mastered
    options = [
        _option(
            "continue-review",
            "▶️",
            "继续复习，从复习库随机抽一道题",
            "popular",
            kind="continue-review",
            count=counts["totals"]["learning"],
        ),
    ]
    if include_familiar:
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
    if has_mastered and not show_error_explanation:
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
    if show_error_explanation:
        options.append(
            _option(
                "explain-current-exercise",
                "🔍",
                "讲解错题",
                "popular",
                kind="explain-current-exercise",
            )
        )
    if has_mastered:
        options.append(
            _option(
                "mastered-cet-paper",
                "📝",
                "生成一套基于已掌握知识点的完整四六级套题（不含听力）",
                "popular",
                kind="mastered-cet-paper",
                count=counts["totals"]["mastered"],
            )
        )
    return _with_dynamic_other_options(options, context, focus)


def build_menu(
    records: dict[str, dict[str, Any]],
    context: str,
    *,
    focus: str | None = None,
    current_exercise_explained: bool = False,
    has_answer_errors: bool = False,
) -> dict[str, Any]:
    if context not in {"initial", "review-complete", "exercise-active"}:
        raise RecordError(f"invalid menu context: {context}")
    counts = counts_for(records)
    if not records:
        options = _with_dynamic_other_options(
            [_option("status", "📊", "查看当前学习记录状态", "popular", kind="status")],
            context,
            "咖啡店点单和日常寒暄",
        )
        options.insert(
            1,
            _option("starter-practice", "📝", "做一组日常英语基础练习", "other", kind="starter-practice"),
        )
        return {"state": "empty", "context": context, "counts": counts, "options": options}
    options = (
        _initial_options(counts, focus=focus)
        if context == "initial"
        else _follow_up_options(
            counts,
            context,
            show_error_explanation=(
                context == "review-complete"
                and has_answer_errors
                and not current_exercise_explained
            ),
            focus=focus,
        )
    )
    return {"state": "ready", "context": context, "counts": counts, "options": options}
