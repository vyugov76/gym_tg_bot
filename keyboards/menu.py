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
            [KeyboardButton(text="🏋️ Начать тренировку")],
            [KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие…",
    )


def settings_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню раздела настроек."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📂 Мои упражнения",
                callback_data="settings:categories",
            )],
            [InlineKeyboardButton(
                text="📋 Мои готовые тренировки",
                callback_data="settings:presets",
            )],
            [InlineKeyboardButton(
                text="👤 Профиль",
                callback_data="settings:profile",
            )],
        ]
    )


def categories_list_keyboard(categories: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Список категорий в настройках."""
    buttons = [
        [InlineKeyboardButton(
            text=f"📂 {cat['name']}",
            callback_data=f"cat:view:{cat['id']}",
        )]
        for cat in categories
    ]
    buttons.append([InlineKeyboardButton(
        text="📁 Несортированные",
        callback_data="cat:unsorted",
    )])
    buttons.append([InlineKeyboardButton(
        text="➕ Создать категорию",
        callback_data="cat:create",
    )])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад в настройки",
        callback_data="settings:back",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def category_detail_keyboard(category_id: int) -> InlineKeyboardMarkup:
    """Действия внутри категории."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="➕ Добавить упражнения",
                callback_data=f"cat:bulk_add:{category_id}",
            )],
            [InlineKeyboardButton(
                text="➖ Удалить упражнения",
                callback_data=f"cat:bulk_rm:{category_id}",
            )],
            [InlineKeyboardButton(
                text="❌ Удалить категорию",
                callback_data=f"cat:delete:{category_id}",
            )],
            [InlineKeyboardButton(
                text="◀️ К списку категорий",
                callback_data="settings:categories",
            )],
        ]
    )


def presets_list_keyboard(presets: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Список готовых тренировок в настройках."""
    buttons = [
        [InlineKeyboardButton(
            text=f"📋 {preset['name']}",
            callback_data=f"preset:view:{preset['id']}",
        )]
        for preset in presets
    ]
    if not buttons:
        buttons.append([InlineKeyboardButton(
            text="Пока нет готовых тренировок",
            callback_data="preset:noop",
        )])
    buttons.append([InlineKeyboardButton(
        text="➕ Создать шаблон",
        callback_data="preset:create",
    )])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад в настройки",
        callback_data="settings:back",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def preset_detail_keyboard(preset_id: int) -> InlineKeyboardMarkup:
    """Действия внутри готовой тренировки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="➕ Добавить упражнения",
                callback_data=f"preset:bulk_add:{preset_id}",
            )],
            [InlineKeyboardButton(
                text="➖ Удалить упражнения",
                callback_data=f"preset:bulk_rm:{preset_id}",
            )],
            [InlineKeyboardButton(
                text="❌ Удалить тренировку",
                callback_data=f"preset:delete:{preset_id}",
            )],
            [InlineKeyboardButton(
                text="◀️ К списку программ",
                callback_data="settings:presets",
            )],
        ]
    )


def workout_start_choice_keyboard() -> InlineKeyboardMarkup:
    """Выбор режима старта тренировки при наличии пресетов."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📝 Начать пустую тренировку",
                callback_data="workout:start:empty",
            )],
            [InlineKeyboardButton(
                text="📋 Выбрать готовую программу",
                callback_data="workout:start:preset_list",
            )],
        ]
    )


def workout_preset_list_keyboard(presets: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Список пресетов для старта тренировки."""
    buttons = [
        [InlineKeyboardButton(
            text=f"📋 {preset['name']}",
            callback_data=f"workout:start:preset:{preset['id']}",
        )]
        for preset in presets
    ]
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="workout:start:back",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _exercise_icon(exercise: dict[str, Any]) -> str:
    exercise_type = normalize_exercise_type(
        exercise.get("exercise_type", exercise.get("is_bodyweight", 0))
    )
    return EXERCISE_ICONS.get(exercise_type, "🏋️‍♂️")


def workout_categories_keyboard(categories: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Выбор категории при добавлении упражнения в тренировку."""
    buttons = [
        [InlineKeyboardButton(
            text=f"📂 {cat['name']}",
            callback_data=f"wex:cat:{cat['id']}",
        )]
        for cat in categories
    ]
    buttons.append([InlineKeyboardButton(
        text="📁 Несортированные",
        callback_data="wex:unsorted",
    )])
    buttons.append([InlineKeyboardButton(
        text="➕ Создать новое упражнение",
        callback_data="ex:create",
    )])
    buttons.append([InlineKeyboardButton(
        text="✅ Завершить тренировку",
        callback_data="set:finish",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def workout_exercises_keyboard(
    exercises: list[dict[str, Any]],
    *,
    back_callback: str = "wex:back_cats",
    show_finish: bool = True,
) -> InlineKeyboardMarkup:
    """Список упражнений внутри категории для тренировки."""
    buttons = []
    for idx, ex in enumerate(exercises):
        icon = _exercise_icon(ex)
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {ex['name']}",
            callback_data=f"ex:select:{idx}",
        )])
    if not exercises:
        buttons.append([InlineKeyboardButton(
            text="В этой категории пока нет упражнений",
            callback_data="ex:noop",
        )])
    buttons.append([InlineKeyboardButton(
        text="➕ Создать новое упражнение",
        callback_data="ex:create",
    )])
    buttons.append([InlineKeyboardButton(
        text="◀️ К категориям",
        callback_data=back_callback,
    )])
    if show_finish:
        buttons.append([InlineKeyboardButton(
            text="✅ Завершить тренировку",
            callback_data="set:finish",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def exercise_category_keyboard(categories: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Выбор категории при создании нового упражнения."""
    buttons = [
        [InlineKeyboardButton(
            text=f"📂 {cat['name']}",
            callback_data=f"ex:cat:{cat['id']}",
        )]
        for cat in categories
    ]
    buttons.append([InlineKeyboardButton(
        text="Оставить без категории (Несортированное)",
        callback_data="ex:cat:none",
    )])
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


def after_set_keyboard(*, preset_mode: bool = False) -> InlineKeyboardMarkup:
    """Действия после записи подхода."""
    next_ex_text = "➡️ Следующее упражнение" if preset_mode else "🔄 Другое упражнение"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✏️ Исправить последний подход",
                callback_data="set:edit_last",
            )],
            [InlineKeyboardButton(text="➕ Ещё подход", callback_data="set:more")],
            [InlineKeyboardButton(text=next_ex_text, callback_data="set:next_ex")],
            [InlineKeyboardButton(
                text="✅ Завершить тренировку",
                callback_data="set:finish",
            )],
        ]
    )


def my_exercises_keyboard(exercises: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Список упражнений пользователя в категории."""
    buttons = []
    for ex in exercises:
        icon = _exercise_icon(ex)
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {ex['name']}",
            callback_data=f"myex:view:{ex['id']}",
        )])
    if not buttons:
        buttons.append([InlineKeyboardButton(
            text="Упражнений в этой категории пока нет",
            callback_data="myex:noop",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def exercise_manage_keyboard(exercise: dict[str, Any]) -> InlineKeyboardMarkup:
    """Меню управления конкретным упражнением."""
    exercise_type = normalize_exercise_type(
        exercise.get("exercise_type", exercise.get("is_bodyweight", 0))
    )
    toggle_text = NEXT_TYPE_BUTTON[exercise_type]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✏️ Изменить название",
                callback_data=f"myex:rename:{exercise['id']}",
            )],
            [InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"myex:toggle:{exercise['id']}",
            )],
            [InlineKeyboardButton(
                text="◀️ Назад",
                callback_data="myex:back_ctx",
            )],
        ]
    )


def profile_keyboard() -> InlineKeyboardMarkup:
    """Кнопки редактирования профиля."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✏️ Изменить рост",
                callback_data="profile:edit_height",
            )],
            [InlineKeyboardButton(
                text="✏️ Изменить вес",
                callback_data="profile:edit_weight",
            )],
            [InlineKeyboardButton(
                text="◀️ Назад в настройки",
                callback_data="settings:back",
            )],
        ]
    )
