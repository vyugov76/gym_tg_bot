"""Inline-клавиатуры для отчёта о тренировке."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def workout_report_keyboard(
    workout_id: int,
    *,
    show_save_preset: bool = False,
) -> InlineKeyboardMarkup:
    """Кнопки под отчётом тренировки."""
    rows = [
        [
            InlineKeyboardButton(
                text="✏️ Редактировать тренировку",
                callback_data=f"workout:edit:{workout_id}",
            ),
            InlineKeyboardButton(
                text="❌ Удалить тренировку",
                callback_data=f"workout:delete:{workout_id}",
            ),
        ],
    ]
    if show_save_preset:
        rows.append([InlineKeyboardButton(
            text="💾 Сохранить как готовую тренировку",
            callback_data=f"preset:save:{workout_id}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm_keyboard(workout_id: int) -> InlineKeyboardMarkup:
    """Подтверждение удаления тренировки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👍 Да, удалить",
                    callback_data=f"workout:delete_confirm:{workout_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="workout:delete_cancel",
                ),
            ]
        ]
    )
