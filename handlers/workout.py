"""Логика записи тренировки: выбор упражнений и запись подходов."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database.requests as db
from keyboards.menu import (
    after_set_keyboard,
    exercise_type_keyboard,
    main_menu_keyboard,
    workout_exercises_keyboard,
)
from keyboards.workout_report import workout_report_keyboard
from states.workout_states import ExerciseStates, WorkoutStates
from utils.exercise_types import (
    EXERCISE_BODYWEIGHT,
    EXERCISE_TIMED,
    EXERCISE_WEIGHTED,
    normalize_exercise_type,
)
from utils.set_input import (
    INVALID_REPS_MSG,
    INVALID_TIME_MSG,
    INVALID_WEIGHTED_MSG,
    parse_bodyweight_reps,
    parse_time_input,
    parse_weighted_set,
)
from utils.text_helpers import format_exercise_time
from utils.workout_display import format_duration, format_finish_workout, to_local_datetime

router = Router(name="workout")
logger = logging.getLogger(__name__)


def _log_callback(callback: CallbackQuery) -> None:
    logger.info(
        "Inline-кнопка: user_id=%s callback_data=%s",
        callback.from_user.id,
        callback.data,
    )


async def _transition_state(state: FSMContext, user_id: int, new_state) -> None:
    previous = await state.get_state()
    await state.set_state(new_state)
    logger.info(
        "FSM user_id=%s: %s -> %s",
        user_id,
        previous or "None",
        new_state.state if new_state else "None",
    )


def _set_prompt(exercise_name: str, set_number: int, exercise_type: int) -> str:
    if exercise_type == EXERCISE_BODYWEIGHT:
        return (
            f"Упражнение: <b>{exercise_name}</b> (собственный вес)\n"
            f"Подход {set_number} — введите <b>количество повторений</b> "
            f"(например, 12):"
        )
    if exercise_type == EXERCISE_TIMED:
        return (
            f"Упражнение: <b>{exercise_name}</b> (на время)\n"
            f"Подход {set_number} — введите <b>время</b> "
            f"(например, 30 или 1:30):"
        )
    return (
        f"Упражнение: <b>{exercise_name}</b>\n"
        f"Подход {set_number} — введите <b>вес/повторения</b> "
        f"(например, 60/10):"
    )


def _merge_exercise_catalog(
    db_exercises: list[dict],
    session_exercises: list[dict],
) -> list[dict]:
    seen: set[tuple[str, int]] = set()
    catalog: list[dict] = []

    for ex in db_exercises:
        exercise_type = normalize_exercise_type(ex.get("exercise_type", ex.get("is_bodyweight")))
        key = (ex["name"], exercise_type)
        if key not in seen:
            seen.add(key)
            catalog.append({"name": ex["name"], "exercise_type": exercise_type})

    for ex in session_exercises:
        exercise_type = normalize_exercise_type(ex["exercise_type"])
        key = (ex["name"], exercise_type)
        if key not in seen:
            seen.add(key)
            catalog.append({"name": ex["name"], "exercise_type": exercise_type})

    return catalog


async def _require_user(message: Message) -> dict | None:
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        logger.warning(
            "Незарегистрированный пользователь user_id=%s пытается начать действие",
            message.from_user.id,
        )
        await message.answer("Сначала нажмите /start для регистрации.")
    return user


async def _show_workout_exercises(
    target: Message | CallbackQuery,
    state: FSMContext,
    db_user_id: int,
    telegram_id: int,
    *,
    edit: bool = False,
    header: str | None = None,
) -> None:
    data = await state.get_data()
    db_exercises = await db.get_exercises_by_user_id(db_user_id)
    session_exercises = data.get("session_exercises", [])
    catalog = _merge_exercise_catalog(db_exercises, session_exercises)
    await state.update_data(exercise_catalog=catalog)

    logger.info(
        f"Пользователь {telegram_id} запросил список упражнений. Найдено: {len(catalog)}"
    )

    text = header or "🏋️ Выберите упражнение для тренировки:"
    keyboard = workout_exercises_keyboard(catalog)

    if isinstance(target, CallbackQuery):
        if edit:
            await target.message.edit_text(text, reply_markup=keyboard)
        else:
            await target.message.answer(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)

    await _transition_state(state, telegram_id, WorkoutStates.choosing_exercise)


@router.message(F.text == "Начать тренировку")
async def start_workout(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    logger.info("Команда меню: user_id=%s text=%r", user_id, message.text)

    user = await _require_user(message)
    if not user:
        return

    try:
        workout_id = await db.create_workout(user["id"])
    except Exception:
        logger.exception(
            "Не удалось создать тренировку: user_id=%s db_user_id=%s",
            user_id,
            user["id"],
        )
        await message.answer("Не удалось начать тренировку. Попробуйте позже.")
        return

    await state.update_data(
        workout_id=workout_id,
        set_number=1,
        workout_exercise_id=None,
        exercise_name=None,
        exercise_type=EXERCISE_WEIGHTED,
        db_user_id=user["id"],
        session_exercises=[],
        exercise_catalog=[],
    )
    logger.info("Тренировка начата: user_id=%s workout_id=%s", user_id, workout_id)

    await message.answer(
        "🏋️ Тренировка начата!",
        reply_markup=main_menu_keyboard(),
    )
    await _show_workout_exercises(message, state, user["id"], user_id)


@router.callback_query(WorkoutStates.choosing_exercise, F.data == "ex:create")
async def create_exercise_start(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    user_id = callback.from_user.id
    await _transition_state(state, user_id, ExerciseStates.waiting_for_name)
    await callback.message.edit_text(
        "Введите <b>название</b> нового упражнения (например, Жим штанги лёжа):"
    )
    await callback.answer()


@router.message(ExerciseStates.waiting_for_name)
async def process_exercise_name(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    name = (message.text or "").strip()

    if not name or len(name) > 100:
        logger.warning(
            "Некорректное название упражнения: user_id=%s text=%r",
            user_id,
            message.text,
        )
        await message.answer("Введите название от 1 до 100 символов:")
        return

    logger.info(f"Пользователь {user_id} ввел название нового упражнения: '{name}'")
    await state.update_data(pending_exercise_name=name)
    await _transition_state(state, user_id, ExerciseStates.waiting_for_type)
    await message.answer(
        f"Упражнение: <b>{name}</b>\nВыберите тип:",
        reply_markup=exercise_type_keyboard(),
    )


@router.callback_query(ExerciseStates.waiting_for_type, F.data.startswith("ex:type:"))
async def process_exercise_type(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    user_id = callback.from_user.id
    exercise_type = int(callback.data.split(":")[-1])
    if exercise_type not in (EXERCISE_WEIGHTED, EXERCISE_BODYWEIGHT, EXERCISE_TIMED):
        await callback.answer("Неизвестный тип упражнения", show_alert=True)
        return

    data = await state.get_data()
    name = data.get("pending_exercise_name")
    db_user_id = data.get("db_user_id")

    if not name or not db_user_id:
        await callback.answer("Данные упражнения потеряны. Начните заново.", show_alert=True)
        return

    logger.info(
        f"Пользователь {user_id} установил тип упражнения '{name}': "
        f"exercise_type={exercise_type}"
    )

    session_exercises = data.get("session_exercises", [])
    session_exercises.append({"name": name, "exercise_type": exercise_type})
    await state.update_data(
        pending_exercise_name=None,
        session_exercises=session_exercises,
    )

    db_exercises = await db.get_exercises_by_user_id(db_user_id)
    catalog = _merge_exercise_catalog(db_exercises, session_exercises)
    await state.update_data(exercise_catalog=catalog)

    await callback.message.edit_text(
        f"✅ Упражнение <b>{name}</b> создано!\n\n"
        f"🏋️ Выберите упражнение для тренировки:",
        reply_markup=workout_exercises_keyboard(catalog),
    )
    await _transition_state(state, user_id, WorkoutStates.choosing_exercise)
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data.startswith("ex:select:"))
async def select_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    user_id = callback.from_user.id
    idx = int(callback.data.split(":")[-1])
    data = await state.get_data()
    catalog = data.get("exercise_catalog", [])
    db_user_id = data.get("db_user_id")

    if idx < 0 or idx >= len(catalog):
        await callback.answer("Упражнение не найдено", show_alert=True)
        return

    exercise = catalog[idx]
    exercise_name = exercise["name"]
    exercise_type = exercise["exercise_type"]

    try:
        workout_exercise_id = await db.add_workout_exercise(
            workout_id=data["workout_id"],
            user_id=db_user_id,
            exercise_name=exercise_name,
            exercise_type=exercise_type,
        )
    except Exception:
        logger.exception(
            "Не удалось выбрать упражнение: user_id=%s exercise_name=%s",
            user_id,
            exercise_name,
        )
        await callback.answer("Ошибка выбора упражнения", show_alert=True)
        return

    await state.update_data(
        workout_exercise_id=workout_exercise_id,
        exercise_name=exercise_name,
        exercise_type=exercise_type,
        set_number=1,
    )
    await _transition_state(state, user_id, WorkoutStates.entering_set)

    logger.info(
        "Выбрано упражнение: user_id=%s workout_exercise_id=%s name=%s exercise_type=%s",
        user_id,
        workout_exercise_id,
        exercise_name,
        exercise_type,
    )
    await callback.message.edit_text(
        _set_prompt(exercise_name, 1, exercise_type)
    )
    await callback.answer()


@router.callback_query(F.data == "set:next_ex")
async def next_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    data = await state.get_data()
    db_user_id = data.get("db_user_id")

    if not db_user_id:
        user = await db.get_user_by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("Сначала нажмите /start", show_alert=True)
            return
        db_user_id = user["id"]
        await state.update_data(db_user_id=db_user_id)

    await callback.message.edit_text("Выберите упражнение:")
    await _show_workout_exercises(callback, state, db_user_id, callback.from_user.id, edit=True)
    await callback.answer()


@router.callback_query(F.data == "set:more")
async def add_more_set(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    data = await state.get_data()
    set_number = data.get("set_number", 1)
    exercise_type = normalize_exercise_type(data.get("exercise_type"))

    await _transition_state(
        state,
        callback.from_user.id,
        WorkoutStates.entering_set,
    )
    await callback.message.answer(
        _set_prompt(data["exercise_name"], set_number, exercise_type)
    )
    await callback.answer()


@router.callback_query(F.data == "set:edit_last")
async def edit_last_set(callback: CallbackQuery, state: FSMContext) -> None:
    """Удаляет последний подход и предлагает ввести заново."""
    _log_callback(callback)
    user_id = callback.from_user.id
    data = await state.get_data()
    workout_exercise_id = data.get("workout_exercise_id")

    if not workout_exercise_id or data.get("set_number", 1) <= 1:
        await callback.answer("Нет подходов для исправления", show_alert=True)
        return

    try:
        deleted_set_number = await db.delete_last_set(workout_exercise_id)
    except Exception:
        logger.exception(
            "Не удалось удалить подход: user_id=%s workout_exercise_id=%s",
            user_id,
            workout_exercise_id,
        )
        await callback.answer("Ошибка при удалении подхода", show_alert=True)
        return

    if deleted_set_number is None:
        await callback.answer("Нет подходов для исправления", show_alert=True)
        return

    await state.update_data(set_number=deleted_set_number)
    await _transition_state(state, user_id, WorkoutStates.entering_set)

    exercise_type = normalize_exercise_type(data.get("exercise_type"))
    logger.info(
        "Исправление подхода: user_id=%s workout_exercise_id=%s set_number=%s",
        user_id,
        workout_exercise_id,
        deleted_set_number,
    )
    await callback.message.answer(
        f"Подход {deleted_set_number} удалён. Введите данные заново:\n\n"
        f"{_set_prompt(data['exercise_name'], deleted_set_number, exercise_type)}"
    )
    await callback.answer()


@router.message(WorkoutStates.entering_set)
async def process_set(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    data = await state.get_data()
    workout_exercise_id = data.get("workout_exercise_id")
    exercise_type = normalize_exercise_type(data.get("exercise_type"))
    set_number = data["set_number"]

    logger.info(
        f"Пользователь {user_id} записал подход для упражнения {workout_exercise_id} "
        f"(exercise_type={exercise_type}): {message.text}"
    )

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
        await db.add_set(
            workout_exercise_id=data["workout_exercise_id"],
            set_number=set_number,
            weight=weight,
            reps=reps,
        )
    except Exception:
        logger.exception(
            "Не удалось сохранить подход: user_id=%s workout_exercise_id=%s set_number=%s",
            user_id,
            data.get("workout_exercise_id"),
            set_number,
        )
        await message.answer("Не удалось сохранить подход. Попробуйте ещё раз.")
        return

    await state.update_data(set_number=set_number + 1)

    if exercise_type == EXERCISE_BODYWEIGHT:
        result_text = f"✅ Подход {set_number} записан: {reps} повторений (собственный вес)"
    elif exercise_type == EXERCISE_TIMED:
        result_text = f"✅ Подход {set_number} записан: {format_exercise_time(reps)}"
    else:
        result_text = f"✅ Подход {set_number} записан: {weight} кг × {reps}"

    logger.info(
        "Подход сохранён: user_id=%s workout_exercise_id=%s set_number=%s weight=%s reps=%s",
        user_id,
        workout_exercise_id,
        set_number,
        weight,
        reps,
    )
    await message.answer(
        f"{result_text}\n\nЧто дальше?",
        reply_markup=after_set_keyboard(),
    )


@router.callback_query(F.data == "set:finish")
async def finish_workout(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    user_id = callback.from_user.id
    data = await state.get_data()
    workout_id = data.get("workout_id")

    if not workout_id:
        logger.warning(
            "Завершение без активной тренировки: user_id=%s",
            user_id,
        )
        await callback.answer("Активная тренировка не найдена", show_alert=True)
        return

    try:
        await db.finish_workout(workout_id)
        rows = await db.get_workout_detail_by_id(workout_id)
    except Exception:
        logger.exception(
            "Не удалось завершить тренировку: user_id=%s workout_id=%s",
            user_id,
            workout_id,
        )
        await callback.answer("Ошибка при сохранении тренировки", show_alert=True)
        return

    await state.clear()

    if rows:
        first = rows[0]
        start_local = to_local_datetime(first["started_at"])
        finish_local = to_local_datetime(first.get("finished_at"))
        duration_str = format_duration(first["started_at"], first.get("finished_at"))
        duration_min = round(
            (finish_local - start_local).total_seconds() / 60
        ) if finish_local and start_local else 0
        logger.info(
            "Тренировка завершена: user_id=%s workout_id=%s "
            "started=%s finished=%s duration_min=%s duration_str=%s",
            user_id,
            workout_id,
            start_local,
            finish_local,
            duration_min,
            duration_str,
        )
        report = format_finish_workout(rows)
    else:
        logger.info(
            "Тренировка завершена без упражнений: user_id=%s workout_id=%s",
            user_id,
            workout_id,
        )
        report = "🎉 Тренировка завершена! Отличная работа!"

    await callback.message.edit_text(
        report,
        reply_markup=workout_report_keyboard(workout_id),
    )
    await callback.answer("Тренировка сохранена!")
