"""Inline-клавиатура мульти-выбора упражнений с галочками."""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.exercise_types import EXERCISE_ICONS, normalize_exercise_type


def _exercise_icon(exercise: dict[str, Any]) -> str:
    exercise_type = normalize_exercise_type(
        exercise.get("exercise_type", exercise.get("is_bodyweight", 0))
    )
    return EXERCISE_ICONS.get(exercise_type, "🏋️‍♂️")


def bulk_select_keyboard(
    exercises: list[dict[str, Any]],
    selected_ids: set[int] | list[int],
    mode: str,
    context_id: int,
) -> InlineKeyboardMarkup:
    """
    Список упражнений с чекбоксами.
    mode: cat_add | cat_rm | preset_add | preset_rm
    """
    selected = set(selected_ids)
    buttons: list[list[InlineKeyboardButton]] = []

    for exercise in exercises:
        ex_id = int(exercise["id"])
        check = "✅ " if ex_id in selected else ""
        icon = _exercise_icon(exercise)
        buttons.append([InlineKeyboardButton(
            text=f"{check}{icon} {exercise['name']}",
            callback_data=f"bulk:toggle:{mode}:{context_id}:{ex_id}",
        )])

    if not exercises:
        buttons.append([InlineKeyboardButton(
            text="Нет доступных упражнений",
            callback_data="bulk:noop",
        )])

    buttons.append([InlineKeyboardButton(
        text="✅ Подтвердить выбор",
        callback_data=f"bulk:confirm:{mode}:{context_id}",
    )])
    buttons.append([InlineKeyboardButton(
        text="❌ Отмена",
        callback_data=f"bulk:cancel:{mode}:{context_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
