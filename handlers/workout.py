"""Логика записи тренировки: выбор упражнений и запись подходов."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database.requests as db
from keyboards.menu import (
    after_set_keyboard,
    exercise_category_keyboard,
    exercise_type_keyboard,
    main_menu_keyboard,
    preset_program_complete_keyboard,
    template_save_keyboard,
    workout_categories_keyboard,
    workout_exercises_keyboard,
    workout_preset_list_keyboard,
    workout_start_choice_keyboard,
)
from keyboards.workout_report import workout_report_keyboard
from states.workout_states import ExerciseStates, PresetSaveStates, WorkoutStates
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
from utils.workout_display import format_finish_workout

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


def _is_preset_workout(data: dict) -> bool:
    """Тренировка по шаблону определяется наличием preset_id (id_preset в БД)."""
    return data.get("preset_id") is not None


def _is_preset_sequence_active(data: dict) -> bool:
    """Идём по очереди шаблона — кнопка «Следующее упражнение»."""
    return (
        _is_preset_workout(data)
        and not data.get("preset_queue_exhausted")
        and not data.get("is_preset_modified")
    )


def _set_prompt(exercise_name: str, set_number: int, exercise_type: int) -> str:
    exercise_type = normalize_exercise_type(exercise_type)
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


def _parse_set_input(
    text: str | None,
    exercise_type: int,
) -> tuple[dict[str, float | int | None] | None, str | None]:
    """Единый парсинг ввода подхода для всех режимов тренировки."""
    exercise_type = normalize_exercise_type(exercise_type)
    if exercise_type == EXERCISE_BODYWEIGHT:
        reps = parse_bodyweight_reps(text)
        if reps is None:
            return None, INVALID_REPS_MSG
        return {"weight": None, "reps": reps, "duration_seconds": None}, None
    if exercise_type == EXERCISE_TIMED:
        duration_seconds = parse_time_input(text)
        if duration_seconds is None:
            return None, INVALID_TIME_MSG
        return {
            "weight": None,
            "reps": None,
            "duration_seconds": duration_seconds,
        }, None
    parsed = parse_weighted_set(text)
    if parsed is None:
        return None, INVALID_WEIGHTED_MSG
    weight, reps = parsed
    return {"weight": weight, "reps": reps, "duration_seconds": None}, None


async def _persist_set(data: dict, values: dict[str, float | int | None]) -> None:
    """INSERT нового подхода или UPDATE существующего (флаг is_new_set / set_id)."""
    workout_exercise_id = data["workout_exercise_id"]
    set_number = data["set_number"]
    set_id = data.get("set_id")
    is_new_set = bool(data.get("is_new_set"))

    if is_new_set or not set_id:
        await db.add_set(
            workout_exercise_id=workout_exercise_id,
            set_number=set_number,
            weight=values.get("weight"),  # type: ignore[arg-type]
            reps=values.get("reps"),  # type: ignore[arg-type]
            duration_seconds=values.get("duration_seconds"),  # type: ignore[arg-type]
        )
        return

    await db.update_set(
        int(set_id),
        weight=values.get("weight"),  # type: ignore[arg-type]
        reps=values.get("reps"),  # type: ignore[arg-type]
        duration_seconds=values.get("duration_seconds"),  # type: ignore[arg-type]
        distance_meters=None,
    )


def _format_set_recorded_message(
    set_number: int,
    exercise_type: int,
    values: dict[str, float | int | None],
) -> str:
    exercise_type = normalize_exercise_type(exercise_type)
    if exercise_type == EXERCISE_BODYWEIGHT:
        return (
            f"✅ Подход {set_number} записан: {values['reps']} повторений "
            f"(собственный вес)"
        )
    if exercise_type == EXERCISE_TIMED:
        return (
            f"✅ Подход {set_number} записан: "
            f"{format_exercise_time(int(values['duration_seconds']))}"
        )
    return f"✅ Подход {set_number} записан: {values['weight']} кг × {values['reps']}"


def _after_set_keyboard(data: dict):
    return after_set_keyboard(show_preset_next=_is_preset_sequence_active(data))


async def _require_user(message: Message) -> dict | None:
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        logger.warning(
            "Незарегистрированный пользователь user_id=%s пытается начать действие",
            message.from_user.id,
        )
        await message.answer("Сначала нажмите /start для регистрации.")
    return user


async def _init_workout_state(
    state: FSMContext,
    user: dict,
    *,
    preset_id: int | None = None,
    preset_queue: list[dict] | None = None,
) -> int:
    workout_id = await db.create_workout(user["id"], id_preset=preset_id)
    await state.update_data(
        workout_id=workout_id,
        set_number=1,
        workout_exercise_id=None,
        exercise_name=None,
        exercise_type=EXERCISE_WEIGHTED,
        db_user_id=user["id"],
        exercise_catalog=[],
        preset_id=preset_id,
        preset_queue=preset_queue or [],
        preset_index=0,
        preset_queue_exhausted=False,
        empty_workout=preset_id is None,
        browse_category_id=None,
        is_preset_modified=False,
        is_new_set=False,
        set_id=None,
    )
    return workout_id


def _preset_exercise_keys(preset_queue: list[dict]) -> set[tuple[str, int]]:
    return {(ex["name"], ex["exercise_type"]) for ex in preset_queue}


async def _mark_preset_modified_if_needed(
    state: FSMContext,
    exercise_name: str,
    exercise_type: int,
) -> None:
    """Взводит флаг, если упражнение не входило в исходный шаблон."""
    data = await state.get_data()
    preset_queue = data.get("preset_queue", [])
    if not data.get("preset_id") or not preset_queue:
        return
    if (exercise_name, exercise_type) not in _preset_exercise_keys(preset_queue):
        await state.update_data(is_preset_modified=True)


def _build_finish_report(workout_id: int, data: dict, rows: list[dict]) -> tuple[str, object]:
    """Формирует текст отчёта и клавиатуру после завершения тренировки."""
    show_save = bool(data.get("empty_workout")) and bool(rows)
    if rows:
        report = format_finish_workout(rows)
    else:
        report = "🎉 Тренировка завершена! Отличная работа!"
    return report, workout_report_keyboard(workout_id, show_save_preset=show_save)


async def _complete_workout_and_show_report(
    callback: CallbackQuery,
    state: FSMContext,
    workout_id: int,
    data: dict,
) -> None:
    """Завершает тренировку в БД и показывает отчёт."""
    try:
        await db.finish_workout(workout_id)
        rows = await db.get_workout_detail_by_id(workout_id)
    except Exception:
        logger.exception("Не удалось завершить тренировку: workout_id=%s", workout_id)
        await callback.answer("Ошибка при сохранении тренировки", show_alert=True)
        return

    report, keyboard = _build_finish_report(workout_id, data, rows)
    await state.clear()
    await callback.message.edit_text(report, reply_markup=keyboard)
    await callback.answer("Тренировка сохранена!")


async def _show_workout_categories(
    target: Message | CallbackQuery,
    state: FSMContext,
    db_user_id: int,
    telegram_id: int,
    *,
    edit: bool = False,
    header: str | None = None,
) -> None:
    categories = await db.get_categories_by_user_id(db_user_id)
    text = header or "🏋️ Выберите категорию упражнений:"
    keyboard = workout_categories_keyboard(categories)

    if isinstance(target, CallbackQuery):
        if edit:
            await target.message.edit_text(text, reply_markup=keyboard)
        else:
            await target.message.answer(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)

    await _transition_state(state, telegram_id, WorkoutStates.choosing_exercise)


async def _show_category_exercises(
    target: Message | CallbackQuery,
    state: FSMContext,
    db_user_id: int,
    telegram_id: int,
    *,
    category_id: int | None,
    edit: bool = False,
) -> None:
    if category_id is None:
        exercises = await db.get_unsorted_exercises(db_user_id)
        title = "📁 <b>Несортированные</b>"
    else:
        category = await db.get_category_by_id(category_id)
        exercises = await db.get_exercises_by_category(db_user_id, category_id)
        title = f"📂 <b>{category['name'] if category else 'Категория'}</b>"

    catalog = [
        {
            "id": ex["id"],
            "name": ex["name"],
            "exercise_type": ex["exercise_type"],
            "category_id": ex.get("category_id"),
        }
        for ex in exercises
    ]
    await state.update_data(
        exercise_catalog=catalog,
        browse_category_id=category_id,
    )

    text = f"{title}\n\nВыберите упражнение:"
    keyboard = workout_exercises_keyboard(catalog)

    if isinstance(target, CallbackQuery):
        if edit:
            await target.message.edit_text(text, reply_markup=keyboard)
        else:
            await target.message.answer(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)

    await _transition_state(state, telegram_id, WorkoutStates.choosing_exercise)


async def _start_workout_exercise(
    callback: CallbackQuery | Message,
    state: FSMContext,
    exercise_name: str,
    exercise_type: int,
    category_id: int | None = None,
) -> None:
    data = await state.get_data()
    telegram_id = (
        callback.from_user.id
        if isinstance(callback, CallbackQuery)
        else callback.from_user.id
    )

    workout_exercise_id = await db.add_workout_exercise(
        workout_id=data["workout_id"],
        user_id=data["db_user_id"],
        exercise_name=exercise_name,
        exercise_type=exercise_type,
        category_id=category_id,
    )

    await _mark_preset_modified_if_needed(state, exercise_name, exercise_type)

    await state.update_data(
        workout_exercise_id=workout_exercise_id,
        exercise_name=exercise_name,
        exercise_type=exercise_type,
        set_number=1,
        is_new_set=False,
        set_id=None,
    )
    await _transition_state(state, telegram_id, WorkoutStates.waiting_for_set_value)

    prompt = _set_prompt(exercise_name, 1, exercise_type)
    if isinstance(callback, CallbackQuery):
        await callback.message.edit_text(prompt)
    else:
        await callback.answer(prompt)


async def _resolve_db_user_id(
    callback: CallbackQuery,
    state: FSMContext,
) -> int | None:
    data = await state.get_data()
    db_user_id = data.get("db_user_id")
    if db_user_id:
        return db_user_id
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        return None
    await state.update_data(db_user_id=user["id"])
    return user["id"]


async def _go_to_exercise_picker(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    mark_preset_modified: bool = False,
) -> None:
    """Единый переход к выбору упражнения в свободном режиме."""
    db_user_id = await _resolve_db_user_id(callback, state)
    if db_user_id is None:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    updates: dict = {}
    if mark_preset_modified and _is_preset_workout(await state.get_data()):
        updates["is_preset_modified"] = True
    if updates:
        await state.update_data(**updates)

    data = await state.get_data()
    browse_category_id = data.get("browse_category_id")
    if browse_category_id is not None:
        await _show_category_exercises(
            callback,
            state,
            db_user_id,
            callback.from_user.id,
            category_id=browse_category_id,
            edit=True,
        )
    else:
        header = (
            "🏋️ Выберите категорию упражнений:"
            if mark_preset_modified
            else None
        )
        await _show_workout_categories(
            callback,
            state,
            db_user_id,
            callback.from_user.id,
            edit=True,
            header=header,
        )


async def _start_next_preset_exercise(
    callback: CallbackQuery,
    state: FSMContext,
) -> bool:
    """Запускает следующее упражнение из пресета. False — если упражнения закончились."""
    data = await state.get_data()
    preset_queue = data.get("preset_queue", [])
    preset_index = data.get("preset_index", 0)

    if preset_index >= len(preset_queue):
        await state.update_data(preset_queue_exhausted=True)
        await callback.message.edit_text(
            "✅ Все упражнения программы выполнены! "
            "Вы можете завершить тренировку или продолжить в свободном режиме.",
            reply_markup=preset_program_complete_keyboard(),
        )
        return False

    exercise = preset_queue[preset_index]
    await state.update_data(preset_index=preset_index + 1)
    await _start_workout_exercise(
        callback,
        state,
        exercise["name"],
        exercise["exercise_type"],
    )
    return True


@router.message(F.text == "🏋️ Начать тренировку")
async def start_workout(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = message.from_user.id
    logger.info("Команда меню: user_id=%s text=%r", user_id, message.text)

    user = await _require_user(message)
    if not user:
        return

    try:
        presets = await db.get_presets_by_user_id(user["id"])
    except Exception:
        logger.exception("Не удалось загрузить пресеты: user_id=%s", user_id)
        await message.answer("Не удалось начать тренировку. Попробуйте позже.")
        return

    if presets:
        await message.answer(
            "🏋️ Как хотите начать тренировку?",
            reply_markup=workout_start_choice_keyboard(),
        )
        return

    try:
        workout_id = await _init_workout_state(state, user)
    except Exception:
        logger.exception("Не удалось создать тренировку: user_id=%s", user_id)
        await message.answer("Не удалось начать тренировку. Попробуйте позже.")
        return

    logger.info("Пустая тренировка начата: user_id=%s workout_id=%s", user_id, workout_id)
    await message.answer("🏋️ Тренировка начата!", reply_markup=main_menu_keyboard())
    await _show_workout_categories(message, state, user["id"], user_id)


@router.callback_query(F.data == "workout:start:empty")
async def start_empty_workout(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    await state.clear()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    try:
        workout_id = await _init_workout_state(state, user)
    except Exception:
        logger.exception("Не удалось создать тренировку: user_id=%s", callback.from_user.id)
        await callback.answer("Ошибка старта тренировки", show_alert=True)
        return

    await callback.message.edit_text("🏋️ Пустая тренировка начата!")
    await _show_workout_categories(callback, state, user["id"], callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "workout:start:preset_list")
async def show_preset_list(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    presets = await db.get_presets_by_user_id(user["id"])
    await callback.message.edit_text(
        "📋 Выберите готовую программу:",
        reply_markup=workout_preset_list_keyboard(presets),
    )
    await callback.answer()


@router.callback_query(F.data == "workout:start:back")
async def workout_start_back(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    await callback.message.edit_text(
        "🏋️ Как хотите начать тренировку?",
        reply_markup=workout_start_choice_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("workout:start:preset:"))
async def start_preset_workout(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    await state.clear()
    preset_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    preset = await db.get_preset_by_id(preset_id)
    if not preset or preset["id_user"] != user["id"]:
        await callback.answer("Программа не найдена", show_alert=True)
        return

    exercises = await db.get_preset_exercises(preset_id)
    if not exercises:
        await callback.answer("В программе нет упражнений", show_alert=True)
        return

    preset_queue = [
        {"name": ex["name"], "exercise_type": ex["exercise_type"]}
        for ex in exercises
    ]

    try:
        workout_id = await _init_workout_state(
            state,
            user,
            preset_id=preset_id,
            preset_queue=preset_queue,
        )
    except Exception:
        logger.exception("Не удалось создать тренировку по пресету: preset_id=%s", preset_id)
        await callback.answer("Ошибка старта тренировки", show_alert=True)
        return

    await callback.message.edit_text(
        f"🏋️ Программа <b>{preset['name']}</b> начата!\n"
        f"Упражнений: {len(preset_queue)}"
    )
    await _start_next_preset_exercise(callback, state)
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data == "wex:back_cats")
async def back_to_categories(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    data = await state.get_data()
    await _show_workout_categories(
        callback,
        state,
        data["db_user_id"],
        callback.from_user.id,
        edit=True,
    )
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data.startswith("wex:cat:"))
async def open_workout_category(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    category_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    await _show_category_exercises(
        callback,
        state,
        data["db_user_id"],
        callback.from_user.id,
        category_id=category_id,
        edit=True,
    )
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data == "wex:unsorted")
async def open_unsorted_exercises(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    data = await state.get_data()
    await _show_category_exercises(
        callback,
        state,
        data["db_user_id"],
        callback.from_user.id,
        category_id=None,
        edit=True,
    )
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data == "ex:noop")
async def exercise_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data == "ex:create")
async def create_exercise_start(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    await _transition_state(state, callback.from_user.id, ExerciseStates.waiting_for_name)
    await callback.message.edit_text(
        "Введите <b>название</b> нового упражнения (например, Жим штанги лёжа):"
    )
    await callback.answer()


@router.message(ExerciseStates.waiting_for_name)
async def process_exercise_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 100:
        await message.answer("Введите название от 1 до 100 символов:")
        return

    await state.update_data(pending_exercise_name=name)
    await _transition_state(state, message.from_user.id, ExerciseStates.waiting_for_type)
    await message.answer(
        f"Упражнение: <b>{name}</b>\nВыберите тип:",
        reply_markup=exercise_type_keyboard(),
    )


@router.callback_query(ExerciseStates.waiting_for_type, F.data.startswith("ex:type:"))
async def process_exercise_type(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
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

    await state.update_data(pending_exercise_type=exercise_type)
    categories = await db.get_categories_by_user_id(db_user_id)
    await _transition_state(
        state,
        callback.from_user.id,
        ExerciseStates.waiting_for_category,
    )
    await callback.message.edit_text(
        f"Упражнение: <b>{name}</b>\nВыберите категорию:",
        reply_markup=exercise_category_keyboard(categories),
    )
    await callback.answer()


@router.callback_query(ExerciseStates.waiting_for_category, F.data.startswith("ex:cat:"))
async def process_exercise_category(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    raw = callback.data.split(":")[-1]
    category_id = None if raw == "none" else int(raw)

    data = await state.get_data()
    name = data.get("pending_exercise_name")
    exercise_type = data.get("pending_exercise_type")
    db_user_id = data.get("db_user_id")

    if not name or exercise_type is None or not db_user_id:
        await callback.answer("Данные упражнения потеряны", show_alert=True)
        return

    try:
        await db.add_global_exercise(
            user_id=db_user_id,
            exercise_name=name,
            exercise_type=exercise_type,
            category_id=category_id,
        )
    except Exception:
        logger.exception("Не удалось создать упражнение: user_id=%s", callback.from_user.id)
        await callback.answer("Ошибка создания упражнения", show_alert=True)
        return

    await state.update_data(
        pending_exercise_name=None,
        pending_exercise_type=None,
    )
    await callback.message.edit_text(f"✅ Упражнение <b>{name}</b> создано!")

    if category_id is None:
        await _show_category_exercises(
            callback,
            state,
            db_user_id,
            callback.from_user.id,
            category_id=None,
        )
    else:
        await _show_category_exercises(
            callback,
            state,
            db_user_id,
            callback.from_user.id,
            category_id=category_id,
        )
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data.startswith("ex:select:"))
async def select_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    idx = int(callback.data.split(":")[-1])
    data = await state.get_data()
    catalog = data.get("exercise_catalog", [])

    if idx < 0 or idx >= len(catalog):
        await callback.answer("Упражнение не найдено", show_alert=True)
        return

    exercise = catalog[idx]
    await _start_workout_exercise(
        callback,
        state,
        exercise["name"],
        exercise["exercise_type"],
        exercise.get("category_id"),
    )
    await callback.answer()


@router.callback_query(F.data == "set:next_ex")
async def next_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    """Следующее упражнение шаблона или выбор упражнения в свободном режиме."""
    _log_callback(callback)
    data = await state.get_data()

    if _is_preset_sequence_active(data):
        await _start_next_preset_exercise(callback, state)
        await callback.answer()
        return

    mark_modified = bool(
        _is_preset_workout(data) and data.get("preset_queue_exhausted")
    )
    await _go_to_exercise_picker(
        callback,
        state,
        mark_preset_modified=mark_modified,
    )
    await callback.answer()


@router.callback_query(F.data == "set:more")
async def add_more_set(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    data = await state.get_data()
    set_number = data.get("set_number", 1)
    exercise_type = normalize_exercise_type(data.get("exercise_type"))

    await state.update_data(is_new_set=False, set_id=None)
    await _transition_state(
        state,
        callback.from_user.id,
        WorkoutStates.waiting_for_set_value,
    )
    await callback.message.answer(
        _set_prompt(data["exercise_name"], set_number, exercise_type)
    )
    await callback.answer()


@router.callback_query(F.data == "set:edit_last")
async def edit_last_set(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    data = await state.get_data()
    workout_exercise_id = data.get("workout_exercise_id")

    if not workout_exercise_id or data.get("set_number", 1) <= 1:
        await callback.answer("Нет подходов для исправления", show_alert=True)
        return

    try:
        deleted_set_number = await db.delete_last_set(workout_exercise_id)
    except Exception:
        logger.exception(
            "Не удалось удалить подход: workout_exercise_id=%s",
            workout_exercise_id,
        )
        await callback.answer("Ошибка при удалении подхода", show_alert=True)
        return

    if deleted_set_number is None:
        await callback.answer("Нет подходов для исправления", show_alert=True)
        return

    await state.update_data(
        set_number=deleted_set_number,
        is_new_set=False,
        set_id=None,
    )
    await _transition_state(
        state,
        callback.from_user.id,
        WorkoutStates.waiting_for_set_value,
    )

    exercise_type = normalize_exercise_type(data.get("exercise_type"))
    await callback.message.answer(
        f"Подход {deleted_set_number} удалён. Введите данные заново:\n\n"
        f"{_set_prompt(data['exercise_name'], deleted_set_number, exercise_type)}"
    )
    await callback.answer()


@router.message(WorkoutStates.waiting_for_set_value)
async def process_set(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    exercise_type = normalize_exercise_type(data.get("exercise_type"))
    set_number = data["set_number"]

    values, error_msg = _parse_set_input(message.text, exercise_type)
    if values is None:
        await message.answer(error_msg or "Некорректный ввод. Попробуйте ещё раз.")
        return

    try:
        await _persist_set(data, values)
    except Exception:
        logger.exception("Не удалось сохранить подход: set_number=%s", set_number)
        await message.answer("Не удалось сохранить подход. Попробуйте ещё раз.")
        return

    await state.update_data(
        set_number=set_number + 1,
        is_new_set=False,
        set_id=None,
    )
    data = await state.get_data()

    result_text = _format_set_recorded_message(set_number, exercise_type, values)
    await message.answer(
        f"{result_text}\n\nЧто дальше?",
        reply_markup=_after_set_keyboard(data),
    )


@router.callback_query(F.data == "set:finish")
async def finish_workout(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    data = await state.get_data()
    workout_id = data.get("workout_id")

    if not workout_id:
        await callback.answer("Активная тренировка не найдена", show_alert=True)
        return

    if _is_preset_workout(data) and data.get("is_preset_modified"):
        await callback.message.edit_text(
            "Вы добавили новые упражнения в процессе тренировки. "
            "Хотите обновить шаблон?",
            reply_markup=template_save_keyboard(),
        )
        await callback.answer()
        return

    await _complete_workout_and_show_report(callback, state, workout_id, data)


@router.callback_query(F.data == "template:overwrite")
async def template_overwrite(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    data = await state.get_data()
    workout_id = data.get("workout_id")
    preset_id = data.get("preset_id")
    db_user_id = data.get("db_user_id")

    if not workout_id or not preset_id or not db_user_id:
        await callback.answer("Данные тренировки потеряны", show_alert=True)
        return

    try:
        count = await db.replace_preset_exercises_from_workout(
            preset_id, db_user_id, workout_id
        )
    except ValueError:
        await callback.answer("Шаблон не найден", show_alert=True)
        return
    except Exception:
        logger.exception(
            "Ошибка перезаписи шаблона: preset_id=%s workout_id=%s",
            preset_id,
            workout_id,
        )
        await callback.answer("Не удалось обновить шаблон", show_alert=True)
        return

    logger.info(
        "Шаблон перезаписан: preset_id=%s workout_id=%s exercises=%s",
        preset_id,
        workout_id,
        count,
    )
    await _complete_workout_and_show_report(callback, state, workout_id, data)


@router.callback_query(F.data == "template:save_new")
async def template_save_new_start(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    data = await state.get_data()
    if not data.get("workout_id"):
        await callback.answer("Данные тренировки потеряны", show_alert=True)
        return

    await _transition_state(
        state,
        callback.from_user.id,
        WorkoutStates.waiting_for_template_name,
    )
    await callback.message.edit_text(
        "Введите название для нового шаблона (например, День Ног):"
    )
    await callback.answer()


@router.callback_query(F.data == "template:skip")
async def template_skip(callback: CallbackQuery, state: FSMContext) -> None:
    _log_callback(callback)
    data = await state.get_data()
    workout_id = data.get("workout_id")

    if not workout_id:
        await callback.answer("Данные тренировки потеряны", show_alert=True)
        return

    await _complete_workout_and_show_report(callback, state, workout_id, data)


@router.message(WorkoutStates.waiting_for_template_name)
async def template_save_new_finish(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 100:
        await message.answer("Введите название от 1 до 100 символов:")
        return

    data = await state.get_data()
    workout_id = data.get("workout_id")
    db_user_id = data.get("db_user_id")

    if not workout_id or not db_user_id:
        await state.clear()
        await message.answer("Данные тренировки потеряны. Начните заново.")
        return

    try:
        preset_id = await db.create_preset_from_workout(db_user_id, name, workout_id)
        exercises = await db.get_preset_exercises(preset_id)
    except Exception:
        logger.exception(
            "Ошибка сохранения нового шаблона: user_id=%s workout_id=%s",
            message.from_user.id,
            workout_id,
        )
        await message.answer("Не удалось сохранить шаблон. Попробуйте позже.")
        return

    logger.info(
        "Новый шаблон из тренировки: preset_id=%s workout_id=%s name=%r",
        preset_id,
        workout_id,
        name,
    )

    try:
        await db.finish_workout(workout_id)
        rows = await db.get_workout_detail_by_id(workout_id)
    except Exception:
        logger.exception("Не удалось завершить тренировку: workout_id=%s", workout_id)
        await message.answer("Шаблон сохранён, но тренировка не завершена. Попробуйте позже.")
        return

    report, keyboard = _build_finish_report(workout_id, data, rows)
    await state.clear()
    await message.answer(
        f"✅ Шаблон <b>{name}</b> сохранён! Упражнений: {len(exercises)}\n\n{report}",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.regexp(r"^preset:save:\d+$"))
async def save_preset_start(callback: CallbackQuery, state: FSMContext) -> None:
    workout_id = int(callback.data.rsplit(":", maxsplit=1)[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    owner_id = await db.get_workout_user_id(workout_id)
    if owner_id != user["id"]:
        await callback.answer("Нет доступа к этой тренировке", show_alert=True)
        return

    await state.set_state(PresetSaveStates.waiting_for_name)
    await state.update_data(save_workout_id=workout_id)
    await callback.message.answer(
        "Введите название для этой тренировки (например, День Ног):"
    )
    await callback.answer()


@router.message(PresetSaveStates.waiting_for_name)
async def save_preset_finish(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 100:
        await message.answer("Введите название от 1 до 100 символов:")
        return

    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer("Сначала нажмите /start для регистрации.")
        return

    data = await state.get_data()
    workout_id = data.get("save_workout_id")
    if not workout_id:
        await state.clear()
        await message.answer("Данные тренировки потеряны. Попробуйте снова из статистики.")
        return

    try:
        preset_id = await db.create_preset_from_workout(user["id"], name, workout_id)
        exercises = await db.get_preset_exercises(preset_id)
    except Exception:
        logger.exception(
            "Ошибка сохранения пресета: user_id=%s workout_id=%s",
            message.from_user.id,
            workout_id,
        )
        await message.answer("Не удалось сохранить программу. Попробуйте позже.")
        return

    await state.clear()
    await message.answer(
        f"✅ Программа <b>{name}</b> сохранена!\n"
        f"Упражнений в шаблоне: {len(exercises)}"
    )
