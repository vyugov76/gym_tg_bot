"""Клавиатуры бота: главное меню, упражнения и тренировки."""

from typing import Any

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from utils.exercise_types import EXERCISE_ICONS, NEXT_TYPE_BUTTON, normalize_exercise_type


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура главного меню."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Начать тренировку")],
            [
                KeyboardButton(text="Статистика"),
                KeyboardButton(text="Мои упражнения"),
            ],
            [KeyboardButton(text="Профиль")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие…",
    )


def _exercise_icon(exercise: dict[str, Any]) -> str:
    exercise_type = normalize_exercise_type(
        exercise.get("exercise_type", exercise.get("is_bodyweight", 0))
    )
    return EXERCISE_ICONS.get(exercise_type, "🏋️‍♂️")


def workout_exercises_keyboard(exercises: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Список упражнений пользователя для тренировки."""
    buttons = [
        [InlineKeyboardButton(text="➕ Создать новое упражнение", callback_data="ex:create")]
    ]
    for idx, ex in enumerate(exercises):
        icon = _exercise_icon(ex)
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {ex['name']}",
                callback_data=f"ex:select:{idx}",
            )
        ])
    buttons.append([
        InlineKeyboardButton(text="✅ Завершить тренировку", callback_data="set:finish")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def exercise_type_keyboard() -> InlineKeyboardMarkup:
    """Выбор типа упражнения при создании."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏋️‍♂️ С отягощением", callback_data="ex:type:0")],
            [InlineKeyboardButton(text="🤸‍♂️ С собственным весом", callback_data="ex:type:1")],
            [InlineKeyboardButton(text="⏱️ На время", callback_data="ex:type:2")],
        ]
    )


def after_set_keyboard() -> InlineKeyboardMarkup:
    """Действия после записи подхода."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Исправить последний подход", callback_data="set:edit_last")],
            [InlineKeyboardButton(text="➕ Ещё подход", callback_data="set:more")],
            [InlineKeyboardButton(text="🔄 Другое упражнение", callback_data="set:next_ex")],
            [InlineKeyboardButton(text="✅ Завершить тренировку", callback_data="set:finish")],
        ]
    )


def my_exercises_keyboard(exercises: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Список упражнений пользователя в разделе профиля."""
    buttons = []
    for ex in exercises:
        icon = _exercise_icon(ex)
        buttons.append([
            InlineKeyboardButton(
                text=f"{icon} {ex['name']}",
                callback_data=f"myex:view:{ex['id']}",
            )
        ])
    if not buttons:
        buttons.append([
            InlineKeyboardButton(text="У вас пока нет упражнений", callback_data="myex:noop")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def exercise_manage_keyboard(exercise: dict[str, Any]) -> InlineKeyboardMarkup:
    """Меню управления конкретным упражнением."""
    exercise_type = normalize_exercise_type(
        exercise.get("exercise_type", exercise.get("is_bodyweight", 0))
    )
    toggle_text = NEXT_TYPE_BUTTON[exercise_type]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"myex:rename:{exercise['id']}")],
            [InlineKeyboardButton(text=toggle_text, callback_data=f"myex:toggle:{exercise['id']}")],
            [InlineKeyboardButton(text="◀️ К списку упражнений", callback_data="myex:back")],
        ]
    )


def profile_keyboard() -> InlineKeyboardMarkup:
    """Кнопки редактирования профиля."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить рост", callback_data="profile:edit_height")],
            [InlineKeyboardButton(text="✏️ Изменить вес", callback_data="profile:edit_weight")],
        ]
    )
