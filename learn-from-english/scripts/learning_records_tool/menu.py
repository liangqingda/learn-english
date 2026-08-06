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


def _option(
    id: str,
    icon: str,
    label: str,
    group: str,
    *,
    append_count: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    count = extra.get("count")
    available_count = extra.get("available_count")
    if append_count and isinstance(count, int):
        if extra.get("busy"):
            label = f"{label}（{count}，暂时无可用）"
        elif isinstance(available_count, int) and available_count != count:
            label = f"{label}（{count}，可用 {available_count}）"
        else:
            label = f"{label}（{count}）"
    return {"id": id, "icon": icon, "label": label, "group": group, **extra}


def _focus_label(focus: str | None) -> str:
    cleaned = (focus or "").strip()
    return cleaned or "当前英语"


def _follow_up_target(focus: str | None, *, initial: bool = False) -> str:
    if initial and not (focus or "").strip():
        return "本轮复习重点"
    return _focus_label(focus)


def _availability_fields(
    availability_counts: dict[str, Any] | None,
    *,
    status: str | None = None,
    categories: tuple[str, ...] | list[str] = (),
) -> dict[str, Any]:
    if availability_counts is None:
        return {}
    if status is not None:
        available = int(availability_counts.get("by_status", {}).get(status, 0))
        claimed = int(availability_counts.get("claimed_by_status", {}).get(status, 0))
    else:
        available = sum(
            int(availability_counts.get("by_category", {}).get(category, 0))
            for category in categories
        )
        claimed = sum(
            int(availability_counts.get("claimed_by_category", {}).get(category, 0))
            for category in categories
        )
    busy = available == 0 and claimed > 0
    return {
        "available_count": available,
        "claimed_count": claimed,
        "busy": busy,
        "disabled": busy,
    }


def _initial_focus(
    focus: str | None,
    active_paths: list[dict[str, Any]],
    counts: dict[str, Any],
) -> str:
    cleaned = (focus or "").strip()
    if cleaned:
        return cleaned
    if active_paths:
        return "；".join(path["label"].removeprefix("复习") for path in active_paths)
    statuses = []
    if counts["totals"]["familiar"]:
        statuses.append("已标熟")
    if counts["totals"]["mastered"]:
        statuses.append("已掌握")
    return "、".join(statuses) + "的知识点"


def _contextual_follow_ups(
    context: str,
    focus: str | None,
    *,
    count: int,
    initial: bool = False,
    excluded_icons: set[str] | None = None,
) -> list[dict[str, Any]]:
    target = _follow_up_target(focus, initial=initial)
    digest = hashlib.sha256(f"{context}:{target}".encode("utf-8")).digest()
    start = digest[0] % len(FOLLOW_UP_SUGGESTIONS)
    candidates = [
        FOLLOW_UP_SUGGESTIONS[(start + index) % len(FOLLOW_UP_SUGGESTIONS)]
        for index in range(len(FOLLOW_UP_SUGGESTIONS))
    ]
    selected = [
        suggestion
        for suggestion in candidates
        if suggestion[1] not in (excluded_icons or set())
    ][:count]
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
    target = _follow_up_target(focus, initial=initial)
    label = (
        "看一套在咖啡店与朋友讨论近况的完整场景对话"
        if initial and not (focus or "").strip()
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
    used_icons = {option["icon"] for option in options}
    used_icons.update(
        child["icon"]
        for option in options
        for child in option.get("children", [])
    )
    options.extend(
        _contextual_follow_ups(
            context,
            focus,
            count=2,
            initial=initial,
            excluded_icons=used_icons,
        )
    )
    options.append(_scenario_option(focus, initial=initial))
    return options


def _initial_options(
    counts: dict[str, Any],
    *,
    focus: str | None = None,
    availability_counts: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    learning_counts = counts["by_status"]["learning"]
    active = []
    for path in REVIEW_PATHS:
        count = sum(learning_counts[category] for category in path["categories"])
        if count:
            categories = list(path["categories"])
            active.append(
                {
                    **path,
                    "categories": categories,
                    "count": count,
                    **_availability_fields(
                        availability_counts, categories=path["categories"]
                    ),
                }
            )
    options: list[dict[str, Any]] = []
    if len(active) > 1:
        active = sorted(active, key=lambda item: (item["count"], item["id"]))
        mixed_id = "mixed+" + "+".join(item["id"] for item in active)
        mixed_categories = [
            category for item in active for category in item["categories"]
        ]
        children = [
            _option(
                group="other",
                kind="review-path",
                parent_id=mixed_id,
                action={"command": "next-review", "path": item["id"]},
                **item,
            )
            for item in active
        ]
        options.append(
            _option(
                mixed_id,
                "🎯",
                "综合复习低分知识点",
                "popular",
                kind="review-path",
                categories=mixed_categories,
                count=sum(item["count"] for item in active),
                children=children,
                action={"command": "next-review", "path": mixed_id},
                **_availability_fields(
                    availability_counts, categories=mixed_categories
                ),
            )
        )
    elif active:
        options.append(
            _option(
                group="popular",
                kind="review-path",
                action={"command": "next-review", "path": active[0]["id"]},
                **active[0],
            )
        )
    if counts["totals"]["familiar"]:
        options.append(
            _option(
                "familiar-review",
                "🔁",
                "复习已标熟的知识点",
                "popular",
                kind="familiar-review",
                count=counts["totals"]["familiar"],
                action={"command": "next-review", "status": "familiar"},
                **_availability_fields(availability_counts, status="familiar"),
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
                action={"command": "next-review", "status": "mastered", "random": True},
                **_availability_fields(availability_counts, status="mastered"),
            )
        )
    if counts["totals"]["mastered"]:
        options.append(
            _option(
                "mastered-cet-paper",
                "📝",
                f"基于 {counts['totals']['mastered']} 个已掌握知识点生成完整四六级套题（不含听力）",
                "popular",
                append_count=False,
                kind="mastered-cet-paper",
                count=counts["totals"]["mastered"],
                action={"command": "mastered-list"},
            )
        )
    options.append(
        _option(
            "learning-progress",
            "📊",
            "查看学习进度与复习统计",
            "other",
            kind="status",
            action={"command": "stats", "period": "30d"},
        )
    )
    error_count = sum(
        counts["by_status"][status]["errors"]
        for status in ("learning", "familiar", "mastered")
    )
    if error_count >= 2:
        options.append(
            _option(
                "error-clusters",
                "🗂️",
                f"同类错题专题复习（基于 {error_count} 条错题）",
                "other",
                append_count=False,
                kind="error-clusters",
                count=error_count,
                action={"command": "error-clusters", "minimum_size": 2},
            )
        )
    target = _initial_focus(focus, active, counts)
    return _with_dynamic_other_options(options, "initial", target, initial=True)


def _follow_up_options(
    counts: dict[str, Any],
    context: str,
    *,
    show_error_explanation: bool,
    focus: str | None,
    availability_counts: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    learning_count = counts["totals"]["learning"]
    familiar_count = counts["totals"]["familiar"]
    mastered_count = counts["totals"]["mastered"]
    options: list[dict[str, Any]] = []
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
    if learning_count:
        options.append(
            _option(
                "continue-review",
                "▶️",
                "继续复习，从复习库随机抽一道题",
                "popular",
                kind="continue-review",
                count=learning_count,
                action={"command": "next-review", "random": True},
                **_availability_fields(availability_counts, status="learning"),
            )
        )
    if familiar_count:
        options.append(
            _option(
                "familiar-review",
                "🔁",
                "复习已标熟的知识点",
                "popular",
                kind="familiar-review",
                count=familiar_count,
                action={"command": "next-review", "status": "familiar"},
                **_availability_fields(availability_counts, status="familiar"),
            )
        )
    if mastered_count:
        options.append(
            _option(
                "mastered-review",
                "🏆",
                "复习已掌握的知识点",
                "popular",
                kind="mastered-review",
                count=mastered_count,
                action={"command": "next-review", "status": "mastered", "random": True},
                **_availability_fields(availability_counts, status="mastered"),
            )
        )
    if mastered_count:
        options.append(
            _option(
                "mastered-cet-paper",
                "📝",
                f"基于 {mastered_count} 个已掌握知识点生成完整四六级套题（不含听力）",
                "popular",
                append_count=False,
                kind="mastered-cet-paper",
                count=mastered_count,
                action={"command": "mastered-list"},
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
    availability_counts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if context not in {"initial", "review-complete"}:
        raise RecordError(f"invalid menu context: {context}")
    counts = counts_for(records)
    if not records:
        options = _with_dynamic_other_options(
            [
                _option(
                    "status",
                    "📊",
                    "查看当前学习记录状态",
                    "popular",
                    kind="status",
                    action={
                        "command": "summary",
                        "include_familiar": True,
                        "include_mastered": True,
                    },
                )
            ],
            context,
            "咖啡店点单和日常寒暄",
        )
        options.insert(
            1,
            _option("starter-practice", "📝", "做一组日常英语基础练习", "other", kind="starter-practice"),
        )
        return {"state": "empty", "context": context, "counts": counts, "options": options}
    options = (
        _initial_options(
            counts, focus=focus, availability_counts=availability_counts
        )
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
            availability_counts=availability_counts,
        )
    )
    return {"state": "ready", "context": context, "counts": counts, "options": options}
