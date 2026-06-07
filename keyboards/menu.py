"""Клавиатуры бота: главное меню и выбор упражнений."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Категории и упражнения (можно расширить позже)
EXERCISE_CATEGORIES: dict[str, dict] = {
    "chest": {
        "name": "Грудь",
        "exercises": ["Жим штанги лёжа", "Жим гантелей", "Разводка", "Отжимания"],
    },
    "back": {
        "name": "Спина",
        "exercises": ["Подтягивания", "Тяга штанги", "Тяга блока", "Гиперэкстензия"],
    },
    "legs": {
        "name": "Ноги",
        "exercises": ["Приседания", "Жим ногами", "Выпады", "Сгибание ног"],
    },
    "shoulders": {
        "name": "Плечи",
        "exercises": ["Жим стоя", "Махи гантелей", "Тяга к подбородку"],
    },
    "arms": {
        "name": "Руки",
        "exercises": ["Подъём штанги на бицепс", "Молотки", "Французский жим"],
    },
}


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура главного меню."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Начать тренировку")],
            [
                KeyboardButton(text="Моя статистика"),
                KeyboardButton(text="Профиль"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие…",
    )


def category_keyboard() -> InlineKeyboardMarkup:
    """Inline-кнопки для выбора категории упражнений."""
    buttons = [
        [InlineKeyboardButton(text=data["name"], callback_data=f"cat:{cat_id}")]
        for cat_id, data in EXERCISE_CATEGORIES.items()
    ]
    buttons.append(
        [InlineKeyboardButton(text="✅ Завершить тренировку", callback_data="set:finish")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def exercises_keyboard(category_id: str) -> InlineKeyboardMarkup:
    """Inline-кнопки упражнений выбранной категории."""
    category = EXERCISE_CATEGORIES[category_id]
    buttons = [
        [InlineKeyboardButton(text=name, callback_data=f"ex:{category_id}:{idx}")]
        for idx, name in enumerate(category["exercises"])
    ]
    buttons.append([InlineKeyboardButton(text="◀️ К категориям", callback_data="cat:back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def after_set_keyboard() -> InlineKeyboardMarkup:
    """Действия после записи подхода."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Ещё подход", callback_data="set:more")],
            [InlineKeyboardButton(text="🔄 Другое упражнение", callback_data="set:next_ex")],
            [InlineKeyboardButton(text="✅ Завершить тренировку", callback_data="set:finish")],
        ]
    )