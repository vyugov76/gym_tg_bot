"""Статистика тренировок с интерактивным календарём."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram_calendar import SimpleCalendarCallback
from aiogram_calendar.schemas import SimpleCalAct

import database.requests as db
from keyboards.workout_calendar import WorkoutCalendar
from utils.workout_display import format_calendar_workout, format_duration, to_local_datetime

router = Router(name="statistics")
logger = logging.getLogger(__name__)

CALENDAR_LOCALE = "ru_RU"


def _calendar_open_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="[ 📅 Открыть календарь тренировок ]",
                callback_data="stats:calendar",
            )]
        ]
    )


@router.message(F.text == "Статистика")
async def show_statistics(message: Message) -> None:
    """Главное меню статистики."""
    telegram_id = message.from_user.id
    logger.info("Запрос статистики: telegram_id=%s", telegram_id)

    try:
        user = await db.get_user_by_telegram_id(telegram_id)
        if not user:
            await message.answer("Сначала нажмите /start для регистрации.")
            return

        total_count = await db.get_total_workouts_for_current_month(user["id"])
        logger.info(
            "Статистика за месяц: telegram_id=%s db_user_id=%s count=%s",
            telegram_id,
            user["id"],
            total_count,
        )
    except Exception:
        logger.exception(
            "Ошибка при загрузке статистики: telegram_id=%s",
            telegram_id,
        )
        await message.answer("Не удалось загрузить статистику. Попробуйте позже.")
        return

    await message.answer(
        "📊 Ваша статистика\n"
        f"🔥 Тренировок за этот месяц: {total_count}\n\n"
        "Нажмите на кнопку ниже, чтобы открыть календарь "
        "и посмотреть детальную историю по дням:",
        reply_markup=_calendar_open_keyboard(),
    )


@router.callback_query(F.data == "stats:calendar")
async def open_calendar(callback: CallbackQuery) -> None:
    """Открывает календарь с подсветкой дней тренировок."""
    telegram_id = callback.from_user.id
    logger.info("Открытие календаря: telegram_id=%s", telegram_id)

    try:
        user = await db.get_user_by_telegram_id(telegram_id)
        if not user:
            await callback.answer("Сначала нажмите /start", show_alert=True)
            return

        workout_calendar = WorkoutCalendar(user_id=user["id"], locale=CALENDAR_LOCALE)
        markup = await workout_calendar.start_calendar()
    except Exception:
        logger.exception(
            "Ошибка при открытии календаря: telegram_id=%s",
            telegram_id,
        )
        await callback.answer("Не удалось открыть календарь", show_alert=True)
        return

    await callback.message.edit_text(
        "📅 Выберите день, чтобы посмотреть детали тренировки:",
        reply_markup=markup,
    )
    await callback.answer()


@router.callback_query(SimpleCalendarCallback.filter())
async def process_calendar_selection(
    callback: CallbackQuery,
    callback_data: SimpleCalendarCallback,
) -> None:
    """Обработка навигации и выбора даты в календаре."""
    telegram_id = callback.from_user.id

    if callback_data.act == SimpleCalAct.cancel:
        logger.info("Календарь закрыт: telegram_id=%s", telegram_id)
        await callback.message.edit_text("Календарь закрыт.")
        await callback.answer()
        return

    try:
        user = await db.get_user_by_telegram_id(telegram_id)
        if not user:
            await callback.answer("Сначала нажмите /start", show_alert=True)
            return

        workout_calendar = WorkoutCalendar(user_id=user["id"], locale=CALENDAR_LOCALE)
        selected, selected_date = await workout_calendar.process_selection(
            callback, callback_data
        )

        if not selected:
            return

        if not isinstance(selected_date, datetime):
            return

        selected_day = selected_date.date()
        logger.info(
            "Выбрана дата в календаре: telegram_id=%s db_user_id=%s date=%s",
            telegram_id,
            user["id"],
            selected_day,
        )

        rows = await db.get_detailed_workouts_by_date(user["id"], selected_day)
        logger.info(
            "Загружено строк детализации: telegram_id=%s date=%s rows=%s",
            telegram_id,
            selected_day,
            len(rows),
        )
    except Exception:
        logger.exception(
            "Ошибка при обработке календаря: telegram_id=%s",
            telegram_id,
        )
        await callback.answer("Ошибка загрузки данных", show_alert=True)
        return

    if not rows:
        await callback.message.answer("В этот день вы отдыхали 🛋️")
        await callback.answer()
        return

    workouts_data: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        workouts_data[row["id_workout"]].append(row)

    messages = []
    for w_rows in workouts_data.values():
        first = w_rows[0]
        start_local = to_local_datetime(first["started_at"])
        finish_local = to_local_datetime(first.get("finished_at"))
        duration_min = round(
            (finish_local - start_local).total_seconds() / 60
        ) if finish_local and start_local else 0
        logger.info(
            "Детали тренировки: workout_id=%s started=%s finished=%s duration_min=%s",
            first["id_workout"],
            start_local,
            finish_local,
            duration_min,
        )
        messages.append(format_calendar_workout(w_rows, selected_day))

    await callback.message.answer("\n\n".join(messages))
    await callback.answer()
