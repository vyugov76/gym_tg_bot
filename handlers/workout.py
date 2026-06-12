"""
workout - логика записи тренировки

Выбор упражнений, запись подходов, работа с шаблонами (presets),
завершение тренировки и сохранение программ.

Ключевые обработчики:
- start_workout, start_empty_workout, start_preset_workout - старт тренировки
- select_exercise, process_set - выбор упражнения и запись подхода
- next_exercise, finish_workout - навигация и завершение
- template_overwrite, template_save_new_finish - обновление шаблона после тренировки
"""

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database.requests as db
from keyboards.menu import (
    after_set_keyboard,
    exercise_category_keyboard,
    exercise_type_keyboard,
    extra_set_confirm_keyboard,
    main_menu_keyboard,
    preset_after_set_keyboard,
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
from utils.workout_display import (
    format_finish_workout,
    format_weight,
    infer_user_utc_offset,
    utc_offset_from_seconds,
    utc_offset_to_seconds,
)
from utils.workout_progress import format_set_value_for_display
from utils.screen_message import show_screen_message, store_screen_message

router = Router(name="workout")
logger = logging.getLogger(__name__)


# --- Логирование и FSM ---


def _log_callback(callback: CallbackQuery) -> None:
    """
    Пишет в лог данные inline-кнопки для отладки.

    Параметры:
        callback: callback-запрос от inline-кнопки
    """
    logger.info(
        "Inline-кнопка: user_id=%s callback_data=%s",
        callback.from_user.id,
        callback.data,
    )


async def _transition_state(state: FSMContext, user_id: int, new_state) -> None:
    """
    Переводит FSM в новое состояние с записью в лог.

    Параметры:
        state: контекст FSM
        user_id: Telegram id пользователя для лога
        new_state: целевое состояние или None
    """
    previous = await state.get_state()
    await state.set_state(new_state)
    logger.info(
        "FSM user_id=%s: %s -> %s",
        user_id,
        previous or "None",
        new_state.state if new_state else "None",
    )


# --- Шаблон (preset) ---


def _is_preset_workout(data: dict) -> bool:
    """
    Проверяет, идёт ли тренировка по сохранённому шаблону.

    Параметры:
        data: данные FSM

    Возвращает:
        True, если в data есть preset_id
    """
    return data.get("preset_id") is not None


def _is_preset_sequence_active(data: dict) -> bool:
    """
    Проверяет, активна ли пошаговая очередь упражнений шаблона.

    Параметры:
        data: данные FSM

    Возвращает:
        True, если идём по очереди шаблона без отклонений
    """
    return (
        _is_preset_workout(data)
        and not data.get("preset_queue_exhausted")
        and not data.get("is_preset_modified")
    )


def _set_number_label(
    set_number: int,
    planned_sets: int,
    *,
    previous_hint: str | None = None,
) -> str:
    """
    Формирует подпись номера подхода для сообщений пользователю.

    Параметры:
        set_number: текущий номер подхода
        planned_sets: плановое число подходов из шаблона (0 - без плана)
        previous_hint: форматированный результат прошлого подхода или None

    Возвращает:
        Строка вида «Подход N» или «Подход N/M» с опциональной прошлой записью
    """
    if planned_sets > 0:
        label = f"Подход {set_number}/{planned_sets}"
    else:
        label = f"Подход {set_number}"
    if previous_hint:
        return f"{label}: (Прошлая: {previous_hint})"
    return label


def _example_suffix(previous_hint: str | None, default_example: str) -> str:
    """
    Возвращает пример формата ввода, если прошлый результат уже не показан.

    Параметры:
        previous_hint: форматированное значение прошлого подхода или None
        default_example: текст примера при отсутствии прошлых данных

    Возвращает:
        Строка-пример для подсказки в prompt
    """
    if previous_hint:
        return ""
    return default_example


def _queue_item_name(item: dict) -> str:
    """
    Извлекает имя упражнения из элемента очереди шаблона.

    Параметры:
        item: элемент preset_queue

    Возвращает:
        Название упражнения или пустая строка
    """
    return str(item.get("exercise_name") or item.get("name") or "").strip()


def _queue_item_type(item: dict) -> int:
    """
    Извлекает тип упражнения из элемента очереди шаблона.

    Параметры:
        item: элемент preset_queue

    Возвращает:
        Нормализованный код типа (EXERCISE_WEIGHTED и т.д.)
    """
    return normalize_exercise_type(
        item.get("exercise_type", item.get("is_bodyweight", EXERCISE_WEIGHTED))
    )


def _normalize_preset_queue_item(raw: dict) -> dict:
    """
    Приводит элемент очереди шаблона к единому формату для FSM.

    Параметры:
        raw: сырой словарь из БД или FSM

    Возвращает:
        Словарь с полями name, exercise_name, exercise_type, sets_count
    """
    name = _queue_item_name(raw)
    exercise_type = _queue_item_type(raw)
    return {
        "name": name,
        "exercise_name": name,
        "exercise_type": exercise_type,
        "is_bodyweight": exercise_type,
        "sets_count": int(raw.get("sets_count") or 0),
    }


def _build_preset_queue(exercises: list[dict]) -> list[dict]:
    """
    Строит нормализованную очередь упражнений шаблона.

    Параметры:
        exercises: упражнения шаблона из БД

    Возвращает:
        Список элементов preset_queue для FSM
    """
    return [
        _normalize_preset_queue_item({
            "name": ex.get("name") or ex.get("exercise_name"),
            "exercise_type": ex.get("exercise_type", ex.get("is_bodyweight")),
            "sets_count": ex.get("sets_count", 0),
        })
        for ex in exercises
    ]


def _get_preset_queue_from_state(data: dict) -> list[dict]:
    """
    Читает и нормализует preset_queue из данных FSM.

    Параметры:
        data: данные FSM

    Возвращает:
        Список нормализованных элементов очереди
    """
    raw_queue = data.get("preset_queue", [])
    if not isinstance(raw_queue, list):
        return []
    return [
        _normalize_preset_queue_item(item)
        for item in raw_queue
        if isinstance(item, dict)
    ]


def _previous_set_key(
    exercise_name: str,
    exercise_type: int,
    set_number: int,
) -> str:
    """
    Формирует ключ подхода прошлой тренировки для словаря FSM.

    Параметры:
        exercise_name: название упражнения
        exercise_type: тип упражнения
        set_number: номер подхода

    Возвращает:
        Строковый ключ вида «имя|тип|номер»
    """
    return f"{exercise_name}|{exercise_type}|{set_number}"


def _build_previous_sets_map_from_rows(rows: list[dict]) -> dict[str, dict]:
    """
    Строит словарь подходов прошлой тренировки для подсказок в FSM.

    Параметры:
        rows: строки детализации предыдущей тренировки по шаблону

    Возвращает:
        Словарь ключ - данные подхода (weight, reps, duration_seconds)
    """
    result: dict[str, dict] = {}
    for row in rows:
        if row.get("set_number") is None:
            continue
        exercise_name = row.get("exercise_name") or row.get("name")
        if not exercise_name:
            continue
        exercise_type = normalize_exercise_type(
            row.get("is_bodyweight", row.get("exercise_type"))
        )
        key = _previous_set_key(
            exercise_name,
            exercise_type,
            int(row["set_number"]),
        )
        result[key] = {
            "set_number": int(row["set_number"]),
            "weight": row.get("weight"),
            "reps": row.get("reps"),
            "duration_seconds": row.get("duration_seconds"),
            "distance_meters": row.get("distance_meters"),
        }
    return result


def _format_previous_hint_for_prompt(prev: dict, exercise_type: int) -> str:
    """
    Форматирует прошлый подход для подписи в prompt ввода.

    Параметры:
        prev: словарь подхода из прошлой тренировки
        exercise_type: тип упражнения

    Возвращает:
        Читаемая строка, например «80 кг x 10» или «12 повт.»
    """
    exercise_type = normalize_exercise_type(exercise_type)
    if exercise_type == EXERCISE_WEIGHTED:
        weight = prev.get("weight")
        reps = prev.get("reps")
        if weight is None or reps is None:
            return format_set_value_for_display(prev, exercise_type)
        weight_text = int(weight) if float(weight).is_integer() else weight
        return f"{weight_text} кг x {reps}"
    return format_set_value_for_display(prev, exercise_type)


def _previous_set_hint(data: dict, set_number: int) -> str | None:
    """
    Возвращает подсказку из прошлой тренировки для текущего подхода.

    Параметры:
        data: данные FSM с previous_workout_sets
        set_number: номер подхода

    Возвращает:
        Форматированное значение или None
    """
    exercise_name = data.get("exercise_name")
    exercise_type = normalize_exercise_type(data.get("exercise_type"))
    if not exercise_name:
        return None

    key = _previous_set_key(exercise_name, exercise_type, set_number)
    prev = data.get("previous_workout_sets", {}).get(key)
    if not prev:
        return None
    return _format_previous_hint_for_prompt(prev, exercise_type)


def _build_set_prompt(data: dict, set_number: int) -> str:
    """
    Формирует текст запроса ввода данных подхода.

    Прошлый результат показывается только в подписи подхода, без отдельной строки.

    Параметры:
        data: данные FSM с exercise_name и exercise_type
        set_number: номер записываемого подхода

    Возвращает:
        HTML-текст prompt для пользователя
    """
    exercise_name = data["exercise_name"]
    exercise_type = normalize_exercise_type(data.get("exercise_type"))
    planned_sets = int(data.get("planned_sets_count") or 0)
    prev_hint = _previous_set_hint(data, set_number)
    set_label = _set_number_label(
        set_number,
        planned_sets,
        previous_hint=prev_hint,
    )

    if exercise_type == EXERCISE_BODYWEIGHT:
        example = _example_suffix(prev_hint, "например, 12")
        suffix = f" {example}" if example else ""
        return (
            f"Упражнение: <b>{exercise_name}</b> (собственный вес)\n"
            f"{set_label}\n"
            f"Введите <b>количество повторений</b>{suffix}:"
        )
    if exercise_type == EXERCISE_TIMED:
        example = _example_suffix(prev_hint, "например, 30 или 1:30")
        suffix = f" {example}" if example else ""
        return (
            f"Упражнение: <b>{exercise_name}</b> (на время)\n"
            f"{set_label}\n"
            f"Введите <b>время</b>{suffix}:"
        )
    example = _example_suffix(prev_hint, "например, 60/10")
    suffix = f" {example}" if example else ""
    return (
        f"Упражнение: <b>{exercise_name}</b>\n"
        f"{set_label}\n"
        f"Введите <b>вес/повторения</b>{suffix}:"
    )


def _parse_set_input(
    text: str | None,
    exercise_type: int,
) -> tuple[dict[str, float | int | None] | None, str | None]:
    """
    Парсит ввод подхода в зависимости от типа упражнения.

    Параметры:
        text: текст от пользователя
        exercise_type: тип упражнения (с весом, BW, на время)

    Возвращает:
        Кортеж (values, error_msg): values при успехе, иначе error_msg
    """
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
    """
    Сохраняет подход в БД: INSERT нового или UPDATE существующего.

    Параметры:
        data: данные FSM с workout_exercise_id, set_number, set_id, is_new_set
        values: распарсенные weight, reps, duration_seconds
    """
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
    *,
    planned_sets: int = 0,
) -> str:
    """
    Формирует сообщение об успешной записи подхода.

    Параметры:
        set_number: номер записанного подхода
        exercise_type: тип упражнения
        values: сохранённые значения подхода
        planned_sets: плановое число подходов для подписи N/M

    Возвращает:
        Текст с галочкой и параметрами подхода
    """
    exercise_type = normalize_exercise_type(exercise_type)
    label = _set_number_label(set_number, planned_sets)
    if exercise_type == EXERCISE_BODYWEIGHT:
        return (
            f"✅ {label} записан: {values['reps']} повторений (собственный вес)"
        )
    if exercise_type == EXERCISE_TIMED:
        return (
            f"✅ {label} записан: "
            f"{format_exercise_time(int(values['duration_seconds']))}"
        )
    return (
        f"✅ {label} записан: "
        f"{format_weight(values['weight'])} кг x {values['reps']}"
    )


async def _mark_sets_deviation_if_needed(state: FSMContext) -> None:
    """
    Фиксирует отклонение от планового числа подходов в шаблоне.

    Параметры:
        state: контекст FSM с planned_sets_count и set_number
    """
    data = await state.get_data()
    planned = int(data.get("planned_sets_count") or 0)
    if planned <= 0 or not _is_preset_workout(data):
        return
    completed = int(data.get("set_number", 1)) - 1
    if completed != planned:
        await state.update_data(preset_sets_deviated=True)


def _completed_sets_count(data: dict) -> int:
    """
    Считает число уже записанных подходов текущего упражнения.

    Параметры:
        data: данные FSM с set_number (следующий ожидаемый)

    Возвращает:
        Количество завершённых подходов (set_number - 1)
    """
    return max(0, int(data.get("set_number", 1)) - 1)


def _after_set_keyboard(data: dict):
    """
    Выбирает клавиатуру после записи подхода (свободная или по шаблону).

    Параметры:
        data: данные FSM

    Возвращает:
        InlineKeyboardMarkup: after_set_keyboard или preset_after_set_keyboard
    """
    if not _is_preset_workout(data):
        return after_set_keyboard(show_preset_next=_is_preset_sequence_active(data))
    return preset_after_set_keyboard(
        show_extra_menu=bool(data.get("show_extra_menu")),
        completed_sets=_completed_sets_count(data),
        planned_sets=int(data.get("planned_sets_count") or 0),
        show_preset_next=_is_preset_sequence_active(data),
    )


async def _require_user(message: Message) -> dict | None:
    """
    Проверяет регистрацию пользователя перед началом тренировки.

    Параметры:
        message: входящее сообщение

    Возвращает:
        Словарь user из БД или None с отправкой подсказки /start
    """
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        logger.warning(
            "Незарегистрированный пользователь user_id=%s пытается начать действие",
            message.from_user.id,
        )
        await message.answer("Сначала нажмите /start для регистрации.")
    return user


async def _load_previous_workout_sets_for_fsm(
    user_id: int,
    preset_id: int | None,
    workout_id: int,
) -> dict[str, dict]:
    """
    Загружает подходы последней тренировки по шаблону для подсказок FSM.

    Параметры:
        user_id: внутренний id пользователя
        preset_id: id шаблона или None
        workout_id: id текущей тренировки (исключается из выборки)

    Возвращает:
        Словарь previous_workout_sets для FSM
    """
    if preset_id is None:
        return {}
    rows = await db.get_previous_workout_detail_for_preset(
        user_id,
        preset_id,
        exclude_workout_id=workout_id,
    )
    if not rows:
        return {}
    return _build_previous_sets_map_from_rows(rows)


async def _merge_previous_sets_for_exercise(
    state: FSMContext,
    exercise_name: str,
    exercise_type: int,
) -> None:
    """
    Дополняет FSM подходами упражнения из последней завершённой тренировки.

    Для шаблонной тренировки берёт прошлую сессию по шаблону, иначе - любую
    последнюю тренировку с этим упражнением.

    Параметры:
        state: контекст FSM с db_user_id и workout_id
        exercise_name: название текущего упражнения
        exercise_type: тип упражнения
    """
    data = await state.get_data()
    db_user_id = data.get("db_user_id")
    workout_id = data.get("workout_id")
    if not db_user_id or not exercise_name:
        return

    preset_id = data.get("preset_id")
    if preset_id:
        rows = await db.get_previous_workout_detail_for_preset(
            db_user_id,
            preset_id,
            exclude_workout_id=workout_id,
        )
    else:
        rows = await db.get_previous_workout_sets_for_exercise(
            db_user_id,
            exercise_name,
            exercise_type,
            exclude_workout_id=workout_id,
        )

    merged = dict(data.get("previous_workout_sets") or {})
    merged.update(_build_previous_sets_map_from_rows(rows))
    await state.update_data(previous_workout_sets=merged)


async def _init_workout_state(
    state: FSMContext,
    user: dict,
    *,
    preset_id: int | None = None,
    preset_queue: list[dict] | None = None,
    telegram_date: datetime | None = None,
) -> int:
    """
    Создаёт тренировку в БД и инициализирует данные FSM.

    Параметры:
        state: контекст FSM
        user: словарь пользователя из БД
        preset_id: id шаблона или None для пустой тренировки
        preset_queue: очередь упражнений шаблона
        telegram_date: дата сообщения для определения UTC-смещения

    Возвращает:
        id созданной тренировки
    """
    workout_id = await db.create_workout(user["id"], id_preset=preset_id)
    previous_workout_sets = await _load_previous_workout_sets_for_fsm(
        user["id"],
        preset_id,
        workout_id,
    )
    normalized_queue = _build_preset_queue(preset_queue) if preset_queue else []

    await state.update_data(
        workout_id=workout_id,
        set_number=1,
        workout_exercise_id=None,
        exercise_name=None,
        exercise_type=EXERCISE_WEIGHTED,
        db_user_id=user["id"],
        exercise_catalog=[],
        preset_id=preset_id,
        preset_queue=normalized_queue,
        preset_index=0,
        preset_queue_exhausted=False,
        empty_workout=preset_id is None,
        browse_category_id=None,
        is_preset_modified=False,
        preset_sets_deviated=False,
        planned_sets_count=0,
        previous_workout_sets=previous_workout_sets,
        show_extra_menu=False,
        user_utc_offset_seconds=utc_offset_to_seconds(
            infer_user_utc_offset(telegram_date)
        ),
        is_new_set=False,
        set_id=None,
    )
    return workout_id


def _preset_exercise_keys(preset_queue: list[dict]) -> set[tuple[str, int]]:
    """
    Собирает множество пар (имя, тип) упражнений исходного шаблона.

    Параметры:
        preset_queue: нормализованная очередь шаблона

    Возвращает:
        Множество кортежей для проверки отклонений от шаблона
    """
    return {
        (_queue_item_name(ex), _queue_item_type(ex))
        for ex in preset_queue
        if isinstance(ex, dict) and _queue_item_name(ex)
    }


async def _mark_preset_modified_if_needed(
    state: FSMContext,
    exercise_name: str,
    exercise_type: int,
) -> None:
    """
    Устанавливает флаг is_preset_modified при упражнении вне шаблона.

    Параметры:
        state: контекст FSM
        exercise_name: название добавленного упражнения
        exercise_type: тип упражнения
    """
    data = await state.get_data()
    preset_queue = _get_preset_queue_from_state(data)
    if not data.get("preset_id") or not preset_queue:
        return
    if (exercise_name, exercise_type) not in _preset_exercise_keys(preset_queue):
        await state.update_data(is_preset_modified=True)


async def _load_previous_workout_rows(
    data: dict,
    workout_id: int,
    current_rows: list[dict] | None = None,
) -> list[dict] | None:
    """
    Загружает строки предыдущей тренировки для сравнения в итоговом отчёте.

    Для шаблонной тренировки сравнивает с прошлой сессией по шаблону.
    Для свободной - собирает прошлые подходы по каждому упражнению отдельно.

    Параметры:
        data: данные FSM с preset_id и db_user_id
        workout_id: id текущей тренировки (исключается)
        current_rows: строки текущей тренировки для свободного режима

    Возвращает:
        Строки детализации или None, если сравнение невозможно
    """
    preset_id = data.get("preset_id")
    db_user_id = data.get("db_user_id")
    if not db_user_id:
        return None

    if preset_id:
        rows = await db.get_previous_workout_detail_for_preset(
            db_user_id,
            preset_id,
            exclude_workout_id=workout_id,
        )
        return rows or None

    if not current_rows:
        return None

    previous_rows: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for row in current_rows:
        if row.get("set_number") is None:
            continue
        exercise_name = row.get("exercise_name")
        exercise_type = normalize_exercise_type(row.get("is_bodyweight"))
        if not exercise_name:
            continue
        key = (exercise_name, exercise_type)
        if key in seen:
            continue
        seen.add(key)
        exercise_rows = await db.get_previous_workout_sets_for_exercise(
            db_user_id,
            exercise_name,
            exercise_type,
            exclude_workout_id=workout_id,
        )
        previous_rows.extend(exercise_rows)

    return previous_rows or None


async def _build_finish_report(
    workout_id: int,
    data: dict,
    rows: list[dict],
) -> tuple[str, object]:
    """
    Формирует текст отчёта и клавиатуру после завершения тренировки.

    Параметры:
        workout_id: id завершённой тренировки
        data: данные FSM (empty_workout, preset_id, utc offset)
        rows: строки детализации текущей тренировки

    Возвращает:
        Кортеж (report_text, reply_markup)
    """
    show_save = bool(data.get("empty_workout")) and bool(rows)
    previous_rows = await _load_previous_workout_rows(data, workout_id, rows)
    utc_offset = utc_offset_from_seconds(data.get("user_utc_offset_seconds"))
    if rows:
        report = format_finish_workout(
            rows,
            previous_rows=previous_rows,
            utc_offset=utc_offset,
        )
    else:
        report = "🎉 Тренировка завершена! Отличная работа!"
    return report, workout_report_keyboard(workout_id, show_save_preset=show_save)


async def _complete_workout_and_show_report(
    callback: CallbackQuery,
    state: FSMContext,
    workout_id: int,
    data: dict,
) -> None:
    """
    Завершает тренировку в БД и показывает отчёт пользователю.

    Параметры:
        callback: callback для edit_text и answer
        state: контекст FSM, очищается после успеха
        workout_id: id тренировки
        data: данные FSM для формирования отчёта
    """
    try:
        await db.finish_workout(workout_id)
        rows = await db.get_workout_detail_by_id(workout_id)
    except Exception:
        logger.exception("Не удалось завершить тренировку: workout_id=%s", workout_id)
        await callback.answer("Ошибка при сохранении тренировки", show_alert=True)
        return

    report, keyboard = await _build_finish_report(workout_id, data, rows)
    await state.clear()
    await callback.message.edit_text(report, reply_markup=keyboard)
    await callback.answer("Тренировка сохранена!")


async def _show_workout_categories(
    target: Message | CallbackQuery,
    state: FSMContext,
    db_user_id: int,
    telegram_id: int,
    *,
    header: str | None = None,
) -> None:
    """
    Показывает список категорий упражнений для выбора.

    Параметры:
        target: Message или CallbackQuery для ответа
        state: контекст FSM
        db_user_id: внутренний id пользователя
        telegram_id: Telegram id для лога FSM
        header: необязательный заголовок вместо стандартного
    """
    categories = await db.get_categories_by_user_id(db_user_id)
    text = header or "🏋️ Выберите категорию упражнений:"
    keyboard = workout_categories_keyboard(categories)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=keyboard)
        await store_screen_message(state, target.message)
    else:
        sent = await target.answer(text, reply_markup=keyboard)
        await store_screen_message(state, sent)

    await _transition_state(state, telegram_id, WorkoutStates.choosing_exercise)


async def _show_category_exercises(
    target: Message | CallbackQuery,
    state: FSMContext,
    db_user_id: int,
    telegram_id: int,
    *,
    category_id: int | None,
) -> None:
    """
    Показывает упражнения выбранной категории или несортированные.

    Параметры:
        target: Message или CallbackQuery для ответа
        state: контекст FSM, обновляет exercise_catalog
        db_user_id: внутренний id пользователя
        telegram_id: Telegram id для лога FSM
        category_id: id категории или None для несортированных
        edit: редактировать сообщение или отправить новое
    """
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
        await target.message.edit_text(text, reply_markup=keyboard)
        await store_screen_message(state, target.message)
    else:
        sent = await target.answer(text, reply_markup=keyboard)
        await store_screen_message(state, sent)

    await _transition_state(state, telegram_id, WorkoutStates.choosing_exercise)


async def _start_workout_exercise(
    callback: CallbackQuery | Message,
    state: FSMContext,
    exercise_name: str,
    exercise_type: int,
    category_id: int | None = None,
    *,
    planned_sets_count: int = 0,
) -> None:
    """
    Добавляет упражнение в тренировку и запрашивает первый подход.

    Параметры:
        callback: Message или CallbackQuery для ответа
        state: контекст FSM
        exercise_name: название упражнения
        exercise_type: тип упражнения
        category_id: id категории или None
        planned_sets_count: плановое число подходов из шаблона
    """
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
        planned_sets_count=planned_sets_count,
        set_number=1,
        show_extra_menu=False,
        is_new_set=False,
        set_id=None,
    )
    await _merge_previous_sets_for_exercise(state, exercise_name, exercise_type)
    await _transition_state(state, telegram_id, WorkoutStates.waiting_for_set_value)

    data = await state.get_data()
    prompt = _build_set_prompt(data, 1)
    if isinstance(callback, CallbackQuery):
        await callback.message.edit_text(prompt)
        await store_screen_message(state, callback.message)
    else:
        await show_screen_message(callback, state, prompt)


async def _resolve_db_user_id(
    callback: CallbackQuery,
    state: FSMContext,
) -> int | None:
    """
    Получает db_user_id из FSM или загружает пользователя из БД.

    Параметры:
        callback: callback для telegram_id
        state: контекст FSM

    Возвращает:
        Внутренний id пользователя или None, если не зарегистрирован
    """
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
    """
    Переводит к выбору упражнения в свободном режиме.

    Параметры:
        callback: callback для навигации
        state: контекст FSM
        mark_preset_modified: установить флаг изменения шаблона
    """
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
            header=header,
        )


async def _start_next_preset_exercise(
    callback: CallbackQuery,
    state: FSMContext,
) -> bool:
    """
    Запускает следующее упражнение из очереди шаблона.

    Параметры:
        callback: callback для edit_text
        state: контекст FSM с preset_queue и preset_index

    Возвращает:
        False, если упражнения в шаблоне закончились
    """
    data = await state.get_data()
    preset_queue = _get_preset_queue_from_state(data)
    preset_index = int(data.get("preset_index", 0))

    if preset_index >= len(preset_queue):
        await state.update_data(preset_queue_exhausted=True)
        await callback.message.edit_text(
            "✅ Все упражнения программы выполнены! "
            "Вы можете завершить тренировку или продолжить в свободном режиме.",
            reply_markup=preset_program_complete_keyboard(),
        )
        await store_screen_message(state, callback.message)
        return False

    exercise = preset_queue[preset_index]
    await state.update_data(
        preset_queue=preset_queue,
        preset_index=preset_index + 1,
    )
    await _start_workout_exercise(
        callback,
        state,
        exercise["exercise_name"],
        exercise["exercise_type"],
        planned_sets_count=exercise["sets_count"],
    )
    return True


# --- Старт тренировки ---


@router.message(F.text == "🏋️ Начать тренировку")
async def start_workout(message: Message, state: FSMContext) -> None:
    """
    Обрабатывает пункт меню «Начать тренировку».

    Параметры:
        message: входящее сообщение
        state: контекст FSM, сбрасывается при старте
    """
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
        workout_id = await _init_workout_state(
            state,
            user,
            telegram_date=message.date,
        )
    except Exception:
        logger.exception("Не удалось создать тренировку: user_id=%s", user_id)
        await message.answer("Не удалось начать тренировку. Попробуйте позже.")
        return

    logger.info("Пустая тренировка начата: user_id=%s workout_id=%s", user_id, workout_id)
    await _show_workout_categories(
        message,
        state,
        user["id"],
        user_id,
        header="🏋️ Тренировка начата!\n\nВыберите категорию упражнений:",
    )


@router.callback_query(F.data == "workout:start:empty")
async def start_empty_workout(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начинает пустую тренировку без шаблона.

    Параметры:
        callback: inline-кнопка workout:start:empty
        state: контекст FSM, сбрасывается
    """
    _log_callback(callback)
    await state.clear()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    try:
        workout_id = await _init_workout_state(
            state,
            user,
            telegram_date=callback.message.date if callback.message else None,
        )
    except Exception:
        logger.exception("Не удалось создать тренировку: user_id=%s", callback.from_user.id)
        await callback.answer("Ошибка старта тренировки", show_alert=True)
        return

    await _show_workout_categories(
        callback,
        state,
        user["id"],
        callback.from_user.id,
        header="🏋️ Тренировка начата!\n\nВыберите категорию упражнений:",
    )
    await callback.answer()


@router.callback_query(F.data == "workout:start:preset_list")
async def show_preset_list(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Показывает список сохранённых программ для старта тренировки.

    Параметры:
        callback: inline-кнопка workout:start:preset_list
        state: контекст FSM (не сбрасывается)
    """
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
    """
    Возвращает к выбору способа начала тренировки.

    Параметры:
        callback: inline-кнопка workout:start:back
        state: контекст FSM
    """
    _log_callback(callback)
    await callback.message.edit_text(
        "🏋️ Как хотите начать тренировку?",
        reply_markup=workout_start_choice_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("workout:start:preset:"))
async def start_preset_workout(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начинает тренировку по выбранному шаблону.

    Параметры:
        callback: inline-кнопка workout:start:preset:{preset_id}
        state: контекст FSM, сбрасывается и инициализируется очередь
    """
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

    preset_queue = _build_preset_queue(exercises)

    try:
        workout_id = await _init_workout_state(
            state,
            user,
            preset_id=preset_id,
            preset_queue=preset_queue,
            telegram_date=callback.message.date if callback.message else None,
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


# --- Выбор упражнения ---


@router.callback_query(WorkoutStates.choosing_exercise, F.data == "wex:back_cats")
async def back_to_categories(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Возвращает к списку категорий упражнений.

    Параметры:
        callback: inline-кнопка wex:back_cats
        state: контекст FSM в choosing_exercise
    """
    _log_callback(callback)
    data = await state.get_data()
    await _show_workout_categories(
        callback,
        state,
        data["db_user_id"],
        callback.from_user.id,
    )
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data.startswith("wex:cat:"))
async def open_workout_category(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Открывает упражнения выбранной категории.

    Параметры:
        callback: inline-кнопка wex:cat:{category_id}
        state: контекст FSM в choosing_exercise
    """
    _log_callback(callback)
    category_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    await _show_category_exercises(
        callback,
        state,
        data["db_user_id"],
        callback.from_user.id,
        category_id=category_id,
    )
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data == "wex:unsorted")
async def open_unsorted_exercises(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Показывает несортированные упражнения для выбора.

    Параметры:
        callback: inline-кнопка wex:unsorted
        state: контекст FSM в choosing_exercise
    """
    _log_callback(callback)
    data = await state.get_data()
    await _show_category_exercises(
        callback,
        state,
        data["db_user_id"],
        callback.from_user.id,
        category_id=None,
    )
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data == "ex:noop")
async def exercise_noop(callback: CallbackQuery) -> None:
    """
    Заглушка для неактивных кнопок в списке упражнений.

    Параметры:
        callback: inline-кнопка ex:noop
    """
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data == "ex:create")
async def create_exercise_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начинает создание нового упражнения прямо во время тренировки.

    Параметры:
        callback: inline-кнопка ex:create
        state: переводится в ExerciseStates.waiting_for_name
    """
    _log_callback(callback)
    await _transition_state(state, callback.from_user.id, ExerciseStates.waiting_for_name)
    await callback.message.edit_text(
        "Введите <b>название</b> нового упражнения (например, Жим штанги лёжа):"
    )
    await callback.answer()


@router.message(ExerciseStates.waiting_for_name)
async def process_exercise_name(message: Message, state: FSMContext) -> None:
    """
    Принимает название нового упражнения и запрашивает тип.

    Параметры:
        message: текстовое сообщение с названием
        state: контекст FSM создания упражнения
    """
    data = await state.get_data()
    if data.get("settings_shortcut_create"):
        return

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
    """
    Принимает тип упражнения и запрашивает категорию.

    Параметры:
        callback: inline-кнопка ex:type:{exercise_type}
        state: контекст FSM с pending_exercise_name
    """
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
    """
    Сохраняет упражнение в каталог и возвращает к списку упражнений.

    Параметры:
        callback: inline-кнопка ex:cat:{category_id|none}
        state: контекст FSM с pending_exercise_name и pending_exercise_type
    """
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
    """
    Выбирает упражнение из каталога и начинает запись подходов.

    Параметры:
        callback: inline-кнопка ex:select:{index}
        state: контекст FSM с exercise_catalog
    """
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


# --- Запись подходов ---


@router.callback_query(F.data == "set:next_ex")
async def next_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Переходит к следующему упражнению шаблона или к выбору упражнения.

    Параметры:
        callback: inline-кнопка set:next_ex
        state: контекст FSM тренировки
    """
    _log_callback(callback)
    data = await state.get_data()

    if _is_preset_sequence_active(data):
        await _mark_sets_deviation_if_needed(state)
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


async def _prompt_next_set(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Запрашивает ввод следующего подхода через edit/answer сообщения.

    Параметры:
        callback: callback с message для ответа
        state: контекст FSM
    """
    await _send_next_set_prompt(callback.from_user.id, callback.message, state)


async def _send_next_set_prompt(
    telegram_id: int,
    message: Message,
    state: FSMContext,
) -> None:
    """
    Отправляет prompt для ввода подхода и переводит FSM в waiting_for_set_value.

    Параметры:
        telegram_id: Telegram id для лога FSM
        message: сообщение для answer
        state: контекст FSM
    """
    data = await state.get_data()
    set_number = data.get("set_number", 1)

    await state.update_data(
        is_new_set=False,
        set_id=None,
        show_extra_menu=False,
    )
    await _transition_state(
        state,
        telegram_id,
        WorkoutStates.waiting_for_set_value,
    )
    prompt = _build_set_prompt(data, set_number)
    await message.edit_text(prompt)
    await store_screen_message(state, message)


@router.callback_query(F.data == "set:next_set_step")
async def next_set_step(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Показывает prompt текущего подхода (режим шаблона, без increment).

    Параметры:
        callback: inline-кнопка set:next_set_step
        state: контекст FSM тренировки по шаблону
    """
    _log_callback(callback)
    data = await state.get_data()
    if not _is_preset_workout(data):
        await callback.answer()
        return

    set_number = int(data.get("set_number", 1))
    await state.update_data(
        is_new_set=False,
        set_id=None,
        show_extra_menu=False,
    )
    await _transition_state(
        state,
        callback.from_user.id,
        WorkoutStates.waiting_for_set_value,
    )
    prompt = _build_set_prompt(data, set_number)
    await callback.message.edit_text(prompt)
    await callback.answer()


@router.callback_query(F.data == "set:toggle_extra")
async def toggle_extra_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Переключает расширенное меню после подхода в режиме шаблона.

    Параметры:
        callback: inline-кнопка set:toggle_extra
        state: контекст FSM с show_extra_menu
    """
    _log_callback(callback)
    data = await state.get_data()
    if not _is_preset_workout(data):
        await callback.answer()
        return

    await state.update_data(show_extra_menu=not bool(data.get("show_extra_menu")))
    data = await state.get_data()
    await callback.message.edit_reply_markup(reply_markup=_after_set_keyboard(data))
    await callback.answer()


@router.callback_query(F.data == "set:more")
async def add_more_set(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Запрашивает дополнительный подход сверх плана шаблона.

    Параметры:
        callback: inline-кнопка set:more
        state: контекст FSM с set_number и planned_sets_count
    """
    _log_callback(callback)
    data = await state.get_data()
    set_number = data.get("set_number", 1)
    planned = int(data.get("planned_sets_count") or 0)

    if planned > 0 and set_number > planned:
        await callback.message.edit_text(
            "Вы уверены, что хотите отойти от программы?",
            reply_markup=extra_set_confirm_keyboard(),
        )
        await store_screen_message(state, callback.message)
        await callback.answer()
        return

    await _prompt_next_set(callback, state)
    await callback.answer()


@router.callback_query(F.data == "set:more:confirm")
async def add_more_set_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Подтверждает дополнительный подход и фиксирует отклонение от шаблона.

    Параметры:
        callback: inline-кнопка set:more:confirm
        state: контекст FSM, устанавливает preset_sets_deviated
    """
    _log_callback(callback)
    await state.update_data(preset_sets_deviated=True)
    await _prompt_next_set(callback, state)
    await callback.answer()


@router.callback_query(F.data == "set:more:cancel")
async def add_more_set_cancel(callback: CallbackQuery) -> None:
    """
    Отменяет добавление дополнительного подхода.

    Параметры:
        callback: inline-кнопка set:more:cancel
    """
    _log_callback(callback)
    await callback.answer("Дополнительный подход не добавлен")


@router.callback_query(F.data == "set:edit_last")
async def edit_last_set(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Удаляет последний подход и запрашивает ввод заново.

    Параметры:
        callback: inline-кнопка set:edit_last
        state: контекст FSM с workout_exercise_id
    """
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

    data = await state.get_data()
    prompt = _build_set_prompt(data, deleted_set_number)
    await callback.message.edit_text(
        f"Подход {deleted_set_number} удалён. Введите данные заново:\n\n{prompt}"
    )
    await store_screen_message(state, callback.message)
    await callback.answer()


@router.message(WorkoutStates.waiting_for_set_value)
async def process_set(message: Message, state: FSMContext) -> None:
    """
    Принимает и сохраняет данные подхода, показывает меню «Что дальше».

    Параметры:
        message: текстовое сообщение с весом/повторами или временем
        state: контекст FSM в waiting_for_set_value
    """
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

    planned_sets = int(data.get("planned_sets_count") or 0)
    result_text = _format_set_recorded_message(
        set_number,
        exercise_type,
        values,
        planned_sets=planned_sets,
    )
    await show_screen_message(
        message,
        state,
        f"{result_text}\n\nЧто дальше?",
        _after_set_keyboard(data),
    )


# --- Завершение тренировки и шаблоны ---


@router.callback_query(F.data == "set:finish")
async def finish_workout(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Завершает тренировку или предлагает обновить шаблон при отклонениях.

    Параметры:
        callback: inline-кнопка set:finish
        state: контекст FSM с workout_id и флагами шаблона
    """
    _log_callback(callback)
    data = await state.get_data()
    workout_id = data.get("workout_id")

    if not workout_id:
        await callback.answer("Активная тренировка не найдена", show_alert=True)
        return

    await _mark_sets_deviation_if_needed(state)
    data = await state.get_data()

    if _is_preset_workout(data) and (
        data.get("is_preset_modified") or data.get("preset_sets_deviated")
    ):
        await callback.message.edit_text(
            "Тренировка отличается от шаблона. Хотите обновить программу?",
            reply_markup=template_save_keyboard(),
        )
        await callback.answer()
        return

    await _complete_workout_and_show_report(callback, state, workout_id, data)


@router.callback_query(F.data == "template:overwrite")
async def template_overwrite(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Перезаписывает шаблон упражнениями текущей тренировки и завершает её.

    Параметры:
        callback: inline-кнопка template:overwrite
        state: контекст FSM с preset_id и workout_id
    """
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
    """
    Запрашивает название нового шаблона на основе текущей тренировки.

    Параметры:
        callback: inline-кнопка template:save_new
        state: переводится в waiting_for_template_name
    """
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
    """
    Завершает тренировку без изменения шаблона.

    Параметры:
        callback: inline-кнопка template:skip
        state: контекст FSM с workout_id
    """
    _log_callback(callback)
    data = await state.get_data()
    workout_id = data.get("workout_id")

    if not workout_id:
        await callback.answer("Данные тренировки потеряны", show_alert=True)
        return

    await _complete_workout_and_show_report(callback, state, workout_id, data)


@router.message(WorkoutStates.waiting_for_template_name)
async def template_save_new_finish(message: Message, state: FSMContext) -> None:
    """
    Создаёт новый шаблон из тренировки, завершает её и показывает отчёт.

    Параметры:
        message: текстовое сообщение с названием шаблона
        state: контекст FSM с workout_id
    """
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

    report, keyboard = await _build_finish_report(workout_id, data, rows)
    await state.clear()
    await show_screen_message(
        message,
        state,
        f"✅ Шаблон <b>{name}</b> сохранён! Упражнений: {len(exercises)}\n\n{report}",
        keyboard,
    )


@router.callback_query(F.data.regexp(r"^preset:save:\d+$"))
async def save_preset_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начинает сохранение завершённой тренировки как шаблона из отчёта.

    Параметры:
        callback: inline-кнопка preset:save:{workout_id}
        state: переводится в PresetSaveStates.waiting_for_name
    """
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
    await callback.message.edit_text(
        "Введите название для этой тренировки (например, День Ног):"
    )
    await store_screen_message(state, callback.message)
    await callback.answer()


@router.message(PresetSaveStates.waiting_for_name)
async def save_preset_finish(message: Message, state: FSMContext) -> None:
    """
    Сохраняет программу из завершённой тренировки (из экрана статистики).

    Параметры:
        message: текстовое сообщение с названием программы
        state: контекст FSM с save_workout_id
    """
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
    await show_screen_message(
        message,
        state,
        f"✅ Программа <b>{name}</b> сохранена!\n"
        f"Упражнений в шаблоне: {len(exercises)}",
    )
