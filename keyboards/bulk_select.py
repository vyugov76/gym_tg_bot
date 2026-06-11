"""
Назначение: inline-клавиатура мульти-выбора упражнений с чекбоксами.

Ключевые компоненты:
- _exercise_icon - иконка типа упражнения
- bulk_select_keyboard - список с галочками, подтверждение и отмена
"""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.exercise_types import EXERCISE_ICONS, normalize_exercise_type


def _exercise_icon(exercise: dict[str, Any]) -> str:
    """
    Эмодзи-иконка типа упражнения.

    Параметры:
        exercise: словарь упражнения с exercise_type или is_bodyweight.

    Возвращает:
        str: символ из EXERCISE_ICONS или значение по умолчанию.
    """
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
    Список упражнений с чекбоксами для массового добавления или удаления.

    Параметры:
        exercises: доступные упражнения с полями id, name и id_user.
        selected_ids: идентификаторы уже выбранных упражнений.
        mode: режим операции - cat_add, cat_rm, preset_add или preset_rm.
        context_id: id категории или шаблона, к которому применяется выбор.

    Возвращает:
        InlineKeyboardMarkup: переключатели, подтверждение и отмена.
    """
    selected = set(selected_ids)
    buttons: list[list[InlineKeyboardButton]] = []

    for exercise in exercises:
        ex_id = int(exercise["id"])
        check = "✅ " if ex_id in selected else ""
        icon = _exercise_icon(exercise)
        shared = "🌐 " if exercise.get("id_user") is None else ""
        buttons.append([InlineKeyboardButton(
            text=f"{check}{shared}{icon} {exercise['name']}",
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
