"""Логика записи тренировки: упражнения, подходы, расчёт тоннажа."""

import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database.requests as db
from keyboards.menu import (
    EXERCISE_CATEGORIES,
    after_set_keyboard,
    category_keyboard,
    exercises_keyboard,
    main_menu_keyboard,
)
from states.workout_states import WorkoutStates

router = Router(name="workout")
logger = logging.getLogger(__name__)

SET_INPUT_PATTERN = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*/\s*(\d+)\s*$")

INVALID_FORMAT_MSG = (
    "Некорректный формат. Пожалуйста, введите данные в формате "
    "ВЕС/ПОВТОРЕНИЯ (например, 80/10):"
)


def _log_callback(callback: CallbackQuery) -> None:
    """Логирует нажатие inline-кнопки."""
    logger.info(
        "Inline-кнопка: user_id=%s callback_data=%s",
        callback.from_user.id,
        callback.data,
    )


async def _transition_state(
    state: FSMContext,
    user_id: int,
    new_state,
) -> None:
    """Переводит FSM в новое состояние и логирует переход."""
    previous = await state.get_state()
    await state.set_state(new_state)
    logger.info(
        "FSM user_id=%s: %s -> %s",
        user_id,
        previous or "None",
        new_state.state if new_state else "None",
    )


def _set_prompt(exercise_name: str, set_number: int) -> str:
    """Текст запроса подхода в едином формате вес/повторения."""
    return (
        f"Упражнение: <b>{exercise_name}</b>\n"
        f"Подход {set_number} — введите <b>вес/повторения</b> "
        f"(например, 60/10):"
    )


def parse_set_input(text: str | None) -> tuple[float, int] | None:
    """Парсит строку «вес/повторения». Возвращает None при некорректном вводе."""
    if not text:
        return None

    match = SET_INPUT_PATTERN.match(text)
    if not match:
        return None

    weight = float(match.group(1).replace(",", "."))
    reps = int(match.group(2))

    if weight < 0 or weight > 500 or reps <= 0 or reps > 100:
        return None

    return weight, reps


async def _require_user(message: Message) -> dict | None:
    """Проверяет, что пользователь зарегистрирован."""
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        logger.warning(
            "Незарегистрированный пользователь user_id=%s пытается начать действие",
            message.from_user.id,
        )
        await message.answer("Сначала нажмите /start для регистрации.")
    return user


@router.message(F.text == "Начать тренировку")
async def start_workout(message: Message, state: FSMContext) -> None:
    """Создаёт запись тренировки и предлагает выбрать упражнение."""
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

    await _transition_state(state, user_id, WorkoutStates.choosing_category)
    await state.update_data(
        workout_id=workout_id,
        set_number=1,
        workout_exercise_id=None,
    )
    logger.info("Тренировка начата: user_id=%s workout_id=%s", user_id, workout_id)

    await message.answer(
        "🏋️ Тренировка начата!\nВыберите категорию упражнения:",
        reply_markup=main_menu_keyboard(),
    )
    await message.answer(
        "Категории:",
        reply_markup=category_keyboard(),
    )


@router.callback_query(WorkoutStates.choosing_category, F.data.startswith("cat:"))
async def choose_category(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка выбора категории упражнений."""
    _log_callback(callback)
    user_id = callback.from_user.id
    cat_id = callback.data.split(":", 1)[1]

    if cat_id == "back":
        await _transition_state(state, user_id, WorkoutStates.choosing_category)
        await callback.message.edit_text(
            "Выберите категорию упражнения:",
            reply_markup=category_keyboard(),
        )
        await callback.answer()
        return

    if cat_id not in EXERCISE_CATEGORIES:
        logger.warning(
            "Неизвестная категория: user_id=%s cat_id=%s",
            user_id,
            cat_id,
        )
        await callback.answer("Неизвестная категория", show_alert=True)
        return

    await state.update_data(category_id=cat_id)
    await _transition_state(state, user_id, WorkoutStates.choosing_exercise)

    category_name = EXERCISE_CATEGORIES[cat_id]["name"]
    logger.info(
        "Выбрана категория: user_id=%s category=%s",
        user_id,
        category_name,
    )
    await callback.message.edit_text(
        f"Категория: <b>{category_name}</b>\nВыберите упражнение:",
        reply_markup=exercises_keyboard(cat_id),
    )
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data.startswith("ex:"))
async def choose_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор упражнения — создаёт запись в workout_exercises."""
    _log_callback(callback)
    user_id = callback.from_user.id
    _, cat_id, idx_str = callback.data.split(":", 2)
    idx = int(idx_str)

    exercise_name = EXERCISE_CATEGORIES[cat_id]["exercises"][idx]
    data = await state.get_data()

    try:
        workout_exercise_id = await db.add_workout_exercise(
            workout_id=data["workout_id"],
            category=EXERCISE_CATEGORIES[cat_id]["name"],
            exercise_name=exercise_name,
        )
    except Exception:
        logger.exception(
            "Не удалось добавить упражнение: user_id=%s workout_id=%s exercise=%s",
            user_id,
            data.get("workout_id"),
            exercise_name,
        )
        await callback.answer("Ошибка сохранения упражнения", show_alert=True)
        return

    await state.update_data(
        workout_exercise_id=workout_exercise_id,
        exercise_name=exercise_name,
        set_number=1,
    )
    await _transition_state(state, user_id, WorkoutStates.entering_set)

    logger.info(
        "Выбрано упражнение: user_id=%s exercise=%s workout_exercise_id=%s",
        user_id,
        exercise_name,
        workout_exercise_id,
    )
    await callback.message.edit_text(_set_prompt(exercise_name, 1))
    await callback.answer()


@router.callback_query(F.data == "set:next_ex")
async def next_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    """Переход к выбору следующего упражнения."""
    _log_callback(callback)
    await _transition_state(
        state,
        callback.from_user.id,
        WorkoutStates.choosing_category,
    )
    await callback.message.edit_text(
        "Выберите категорию упражнения:",
        reply_markup=category_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "set:more")
async def add_more_set(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрос следующего подхода того же упражнения."""
    _log_callback(callback)
    data = await state.get_data()
    set_number = data.get("set_number", 1)

    await _transition_state(
        state,
        callback.from_user.id,
        WorkoutStates.entering_set,
    )
    await callback.message.answer(_set_prompt(data["exercise_name"], set_number))
    await callback.answer()


@router.message(WorkoutStates.entering_set)
async def process_set(message: Message, state: FSMContext) -> None:
    """Принимает подход в формате вес/повторения и сохраняет его в БД."""
    user_id = message.from_user.id
    logger.info(
        "Пользователь %s ввел данные тренировки: %s",
        user_id,
        message.text,
    )

    parsed = parse_set_input(message.text)
    if parsed is None:
        logger.warning(
            "Некорректный формат подхода: user_id=%s text=%r",
            user_id,
            message.text,
        )
        await message.answer(INVALID_FORMAT_MSG)
        return

    weight, reps = parsed
    data = await state.get_data()
    set_number = data["set_number"]

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

    tonnage = weight * reps
    await state.update_data(set_number=set_number + 1)

    logger.info(
        "Подход записан: user_id=%s set_number=%s weight=%s reps=%s tonnage=%s",
        user_id,
        set_number,
        weight,
        reps,
        tonnage,
    )
    await message.answer(
        f"✅ Подход {set_number} записан: "
        f"{weight} кг × {reps} = {tonnage:.0f} кг\n\n"
        f"Что дальше?",
        reply_markup=after_set_keyboard(),
    )


@router.callback_query(F.data == "set:finish")
async def finish_workout(callback: CallbackQuery, state: FSMContext) -> None:
    """Завершает тренировку и показывает итоговый тоннаж."""
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
        total_tonnage = await db.calculate_workout_tonnage(workout_id)
        await db.finish_workout(workout_id, total_tonnage)
    except Exception:
        logger.exception(
            "Не удалось завершить тренировку: user_id=%s workout_id=%s",
            user_id,
            workout_id,
        )
        await callback.answer("Ошибка при сохранении тренировки", show_alert=True)
        return

    await state.clear()
    logger.info(
        "Тренировка завершена: user_id=%s workout_id=%s total_tonnage=%s",
        user_id,
        workout_id,
        total_tonnage,
    )

    await callback.message.edit_text(
        f"🎉 Тренировка завершена!\n\n"
        f"Суммарный тоннаж: <b>{total_tonnage:.0f} кг</b>\n"
        f"Отличная работа!"
    )
    await callback.answer("Тренировка сохранена!")
