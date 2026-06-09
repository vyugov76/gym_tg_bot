"""Статистика тренировок с интерактивным календарём."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram_calendar import SimpleCalendarCallback
from aiogram_calendar.schemas import SimpleCalAct

import database.requests as db
from keyboards.workout_calendar import WorkoutCalendar
from keyboards.workout_report import delete_confirm_keyboard, workout_report_keyboard
from states.workout_states import WorkoutEditStates
from utils.exercise_types import EXERCISE_BODYWEIGHT, EXERCISE_TIMED
from utils.set_input import (
    INVALID_REPS_MSG,
    INVALID_TIME_MSG,
    INVALID_WEIGHTED_MSG,
    parse_bodyweight_reps,
    parse_time_input,
    parse_weighted_set,
)
from utils.workout_display import (
    format_calendar_workout,
    format_finish_workout,
    get_exercises_from_rows,
    to_local_datetime,
)

router = Router(name="statistics")
logger = logging.getLogger(__name__)

CALENDAR_LOCALE = "ru_RU"

def _parse_positive_int(text: str | None) -> int | None:
    if not text or not text.strip().isdigit():
        return None
    value = int(text.strip())
    return value if value > 0 else None


async def _verify_workout_access(
    telegram_id: int,
    workout_id: int,
) -> tuple[dict | None, str | None]:
    user = await db.get_user_by_telegram_id(telegram_id)
    if not user:
        return None, "Сначала нажмите /start"
    owner_id = await db.get_workout_user_id(workout_id)
    if owner_id is None:
        return user, "Тренировка не найдена"
    if owner_id != user["id"]:
        return user, "Нет доступа к этой тренировке"
    return user, None


def _detect_report_style(message_text: str | None) -> str:
    if message_text and message_text.startswith("📅"):
        return "calendar"
    return "finish"


def _format_workout_report(
    rows: list[dict],
    report_style: str,
    calendar_date: date | None = None,
) -> str:
    if report_style == "calendar" and calendar_date:
        return format_calendar_workout(rows, calendar_date)
    return format_finish_workout(rows)


def _calendar_open_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="[ 📅 Открыть календарь тренировок ]",
                callback_data="stats:calendar",
            )]
        ]
    )


@router.message(F.text == "📊 Статистика")
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

    for w_rows in workouts_data.values():
        first = w_rows[0]
        workout_id = first["id_workout"]
        start_local = to_local_datetime(first["started_at"])
        finish_local = to_local_datetime(first.get("finished_at"))
        duration_min = round(
            (finish_local - start_local).total_seconds() / 60
        ) if finish_local and start_local else 0
        logger.info(
            "Детали тренировки: workout_id=%s started=%s finished=%s duration_min=%s",
            workout_id,
            start_local,
            finish_local,
            duration_min,
        )
        await callback.message.answer(
            format_calendar_workout(w_rows, selected_day),
            reply_markup=workout_report_keyboard(workout_id),
        )

    await callback.answer()


# --- Удаление тренировки ---


@router.callback_query(F.data.regexp(r"^workout:delete:\d+$"))
async def request_delete_workout(callback: CallbackQuery) -> None:
    workout_id = int(callback.data.rsplit(":", maxsplit=1)[-1])
    _, error = await _verify_workout_access(callback.from_user.id, workout_id)
    if error:
        await callback.answer(error, show_alert=True)
        return

    await callback.message.answer(
        "Вы уверены, что хотите полностью удалить эту тренировку "
        "и все её подходы? ⚠️",
        reply_markup=delete_confirm_keyboard(workout_id),
    )
    await callback.answer()


@router.callback_query(F.data == "workout:delete_cancel")
async def cancel_delete_workout(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Удаление отменено.")
    await callback.answer()


@router.callback_query(F.data.regexp(r"^workout:delete_confirm:\d+$"))
async def confirm_delete_workout(callback: CallbackQuery) -> None:
    workout_id = int(callback.data.rsplit(":", maxsplit=1)[-1])
    _, error = await _verify_workout_access(callback.from_user.id, workout_id)
    if error:
        await callback.answer(error, show_alert=True)
        return

    try:
        await db.delete_workout(workout_id)
    except Exception:
        logger.exception(
            "Ошибка удаления тренировки: telegram_id=%s workout_id=%s",
            callback.from_user.id,
            workout_id,
        )
        await callback.answer("Не удалось удалить тренировку", show_alert=True)
        return

    await callback.message.edit_text("Тренировка успешно удалена 🗑️")
    await callback.answer()


# --- Редактирование тренировки ---


@router.callback_query(F.data.regexp(r"^workout:edit:\d+$"))
async def start_edit_workout(callback: CallbackQuery, state: FSMContext) -> None:
    workout_id = int(callback.data.rsplit(":", maxsplit=1)[-1])
    _, error = await _verify_workout_access(callback.from_user.id, workout_id)
    if error:
        await callback.answer(error, show_alert=True)
        return

    try:
        rows = await db.get_workout_detail_by_id(workout_id)
    except Exception:
        logger.exception(
            "Ошибка загрузки тренировки для редактирования: workout_id=%s",
            workout_id,
        )
        await callback.answer("Не удалось загрузить тренировку", show_alert=True)
        return

    exercises = get_exercises_from_rows(rows)
    if not exercises:
        await callback.answer(
            "В этой тренировке нет подходов для редактирования",
            show_alert=True,
        )
        return

    report_style = _detect_report_style(callback.message.text)
    calendar_date = None
    if rows:
        calendar_date = to_local_datetime(rows[0]["started_at"]).date()

    await state.update_data(
        workout_id=workout_id,
        report_style=report_style,
        calendar_date=calendar_date.isoformat() if calendar_date else None,
    )
    await state.set_state(WorkoutEditStates.waiting_for_exercise_number)

    await callback.message.answer(
        "Введите порядковый номер упражнения, которое хотите отредактировать "
        "(например, 1):"
    )
    await callback.answer()


@router.message(WorkoutEditStates.waiting_for_exercise_number)
async def edit_workout_exercise_number(message: Message, state: FSMContext) -> None:
    exercise_number = _parse_positive_int(message.text)
    data = await state.get_data()
    workout_id = data["workout_id"]

    try:
        rows = await db.get_workout_detail_by_id(workout_id)
    except Exception:
        logger.exception(
            "Ошибка загрузки упражнений: workout_id=%s",
            workout_id,
        )
        await message.answer("Не удалось загрузить данные. Попробуйте позже.")
        return

    exercises = get_exercises_from_rows(rows)
    if exercise_number is None or exercise_number > len(exercises):
        await message.answer(
            f"Упражнение с номером {message.text!r} не найдено.\n"
            f"Введите число от 1 до {len(exercises)}:"
        )
        return

    exercise = exercises[exercise_number - 1]
    await state.update_data(
        workout_exercise_id=exercise["id"],
        exercise_type=exercise["exercise_type"],
        exercise_name=exercise["name"],
    )
    await state.set_state(WorkoutEditStates.waiting_for_set_number)
    await message.answer(
        f"В упражнении «{exercise['name']}» введите номер подхода, "
        f"который хотите изменить (например, 2):"
    )


@router.message(WorkoutEditStates.waiting_for_set_number)
async def edit_workout_set_number(message: Message, state: FSMContext) -> None:
    set_number = _parse_positive_int(message.text)
    data = await state.get_data()
    workout_exercise_id = data["workout_exercise_id"]
    exercise_type = data["exercise_type"]

    try:
        set_row = await db.get_set_by_number(workout_exercise_id, set_number or -1)
    except Exception:
        logger.exception(
            "Ошибка загрузки подхода: workout_exercise_id=%s set_number=%s",
            workout_exercise_id,
            set_number,
        )
        await message.answer("Не удалось загрузить подход. Попробуйте позже.")
        return

    if set_number is None or set_row is None:
        await message.answer(
            f"Подход с номером {message.text!r} не найден.\n"
            "Введите существующий номер подхода:"
        )
        return

    await state.update_data(set_id=set_row["id"], set_number=set_number)
    await state.set_state(WorkoutEditStates.waiting_for_new_value)

    if exercise_type == EXERCISE_BODYWEIGHT:
        prompt = "Введите новое количество повторений (например, 12):"
    elif exercise_type == EXERCISE_TIMED:
        prompt = "Введите новое время выполнения (например, 45 или 1:15):"
    else:
        prompt = "Введите новое значение в формате вес/повторения (например, 75/10):"
    await message.answer(prompt)


@router.message(WorkoutEditStates.waiting_for_new_value)
async def edit_workout_new_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    exercise_type = data["exercise_type"]
    set_id = data["set_id"]
    workout_id = data["workout_id"]

    weight: float | None = None
    reps: int | None = None

    if exercise_type == EXERCISE_BODYWEIGHT:
        reps = parse_bodyweight_reps(message.text)
        if reps is None:
            await message.answer(INVALID_REPS_MSG)
            return
    elif exercise_type == EXERCISE_TIMED:
        reps = parse_time_input(message.text)
        if reps is None:
            await message.answer(INVALID_TIME_MSG)
            return
        weight = None
    else:
        parsed = parse_weighted_set(message.text)
        if parsed is None:
            await message.answer(INVALID_WEIGHTED_MSG)
            return
        weight, reps = parsed

    try:
        await db.update_set(set_id, reps=reps, weight=weight)
        rows = await db.get_workout_detail_by_id(workout_id)
    except Exception:
        logger.exception(
            "Ошибка обновления подхода: set_id=%s workout_id=%s",
            set_id,
            workout_id,
        )
        await message.answer("Не удалось сохранить изменения. Попробуйте ещё раз.")
        return

    calendar_date = None
    if data.get("calendar_date"):
        calendar_date = date.fromisoformat(data["calendar_date"])

    report = _format_workout_report(
        rows,
        data.get("report_style", "finish"),
        calendar_date,
    )
    await state.clear()

    await message.answer(
        f"Подход успешно изменён!\n\nОбновлённая статистика:\n\n{report}",
        reply_markup=workout_report_keyboard(workout_id),
    )
