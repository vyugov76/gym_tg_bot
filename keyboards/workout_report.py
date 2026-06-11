"""
Назначение: inline-клавиатуры для отчёта о тренировке.

Ключевые компоненты:
- workout_report_keyboard - редактирование, удаление и сохранение как шаблон
- calendar_workout_report_keyboard - отчёт из календаря с возвратом
- delete_confirm_keyboard - подтверждение удаления тренировки
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def workout_report_keyboard(
    workout_id: int,
    *,
    show_save_preset: bool = False,
) -> InlineKeyboardMarkup:
    """
    Кнопки под отчётом завершённой тренировки.

    Параметры:
        workout_id: идентификатор тренировки.
        show_save_preset: показывать кнопку сохранения как готовую тренировку.

    Возвращает:
        InlineKeyboardMarkup: редактирование, удаление и опционально сохранение шаблона.
    """
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


def calendar_workout_report_keyboard(
    workout_id: int,
    year: int,
    month: int,
) -> InlineKeyboardMarkup:
    """
    Отчёт тренировки, открытый из календаря статистики.

    Параметры:
        workout_id: идентификатор тренировки.
        year: год календаря для возврата.
        month: месяц календаря для возврата.

    Возвращает:
        InlineKeyboardMarkup: стандартные действия отчёта и кнопка «Назад в календарь».
    """
    base = workout_report_keyboard(workout_id)
    rows = list(base.inline_keyboard)
    rows.append([InlineKeyboardButton(
        text="⬅️ Назад в календарь",
        callback_data=f"stats:back_calendar:{year}:{month}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm_keyboard(workout_id: int) -> InlineKeyboardMarkup:
    """
    Подтверждение удаления тренировки.

    Параметры:
        workout_id: идентификатор удаляемой тренировки.

    Возвращает:
        InlineKeyboardMarkup: подтверждение или отмена удаления.
    """
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
