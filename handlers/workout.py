"""Логика записи тренировки: упражнения, подходы, расчёт тоннажа."""

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


async def _require_user(message: Message) -> dict | None:
    """Проверяет, что пользователь зарегистрирован."""
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start для регистрации.")
    return user


@router.message(F.text == "Начать тренировку")
async def start_workout(message: Message, state: FSMContext) -> None:
    """Создаёт запись тренировки и предлагает выбрать упражнение."""
    user = await _require_user(message)
    if not user:
        return

    workout_id = await db.create_workout(user["id"])
    await state.set_state(WorkoutStates.choosing_category)
    await state.update_data(
        workout_id=workout_id,
        set_number=1,
        workout_exercise_id=None,
    )

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
    cat_id = callback.data.split(":", 1)[1]

    if cat_id == "back":
        await callback.message.edit_text(
            "Выберите категорию упражнения:",
            reply_markup=category_keyboard(),
        )
        await state.set_state(WorkoutStates.choosing_category)
        await callback.answer()
        return

    if cat_id not in EXERCISE_CATEGORIES:
        await callback.answer("Неизвестная категория", show_alert=True)
        return

    await state.update_data(category_id=cat_id)
    await state.set_state(WorkoutStates.choosing_exercise)

    category_name = EXERCISE_CATEGORIES[cat_id]["name"]
    await callback.message.edit_text(
        f"Категория: <b>{category_name}</b>\nВыберите упражнение:",
        reply_markup=exercises_keyboard(cat_id),
    )
    await callback.answer()


@router.callback_query(WorkoutStates.choosing_exercise, F.data.startswith("ex:"))
async def choose_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор упражнения — создаёт запись в workout_exercises."""
    _, cat_id, idx_str = callback.data.split(":", 2)
    idx = int(idx_str)

    exercise_name = EXERCISE_CATEGORIES[cat_id]["exercises"][idx]
    data = await state.get_data()

    workout_exercise_id = await db.add_workout_exercise(
        workout_id=data["workout_id"],
        category=EXERCISE_CATEGORIES[cat_id]["name"],
        exercise_name=exercise_name,
    )

    await state.update_data(
        workout_exercise_id=workout_exercise_id,
        exercise_name=exercise_name,
        set_number=1,
    )
    await state.set_state(WorkoutStates.entering_weight)

    await callback.message.edit_text(
        f"Упражнение: <b>{exercise_name}</b>\n"
        f"Подход 1 — введите <b>вес</b> в кг (например, 60):"
    )
    await callback.answer()


@router.callback_query(F.data == "set:next_ex")
async def next_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    """Переход к выбору следующего упражнения."""
    await state.set_state(WorkoutStates.choosing_category)
    await callback.message.edit_text(
        "Выберите категорию упражнения:",
        reply_markup=category_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "set:more")
async def add_more_set(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрос веса для следующего подхода того же упражнения."""
    data = await state.get_data()
    set_number = data.get("set_number", 1)

    await state.set_state(WorkoutStates.entering_weight)
    await callback.message.edit_text(
        f"Упражнение: <b>{data['exercise_name']}</b>\n"
        f"Подход {set_number} — введите <b>вес</b> в кг:"
    )
    await callback.answer()


@router.message(WorkoutStates.entering_weight)
async def process_weight(message: Message, state: FSMContext) -> None:
    """Принимает вес подхода и запрашивает повторения."""
    try:
        weight = float(message.text.replace(",", "."))
        if weight < 0 or weight > 500:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Введите корректный вес числом (0–500 кг):")
        return

    await state.update_data(current_weight=weight)
    await state.set_state(WorkoutStates.entering_reps)
    await message.answer("Теперь введите <b>количество повторений</b> (например, 10):")


@router.message(WorkoutStates.entering_reps)
async def process_reps(message: Message, state: FSMContext) -> None:
    """Принимает повторения, сохраняет подход и предлагает следующие действия."""
    try:
        reps = int(message.text.strip())
        if reps <= 0 or reps > 100:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Введите целое число повторений от 1 до 100:")
        return

    data = await state.get_data()
    set_number = data["set_number"]

    await db.add_set(
        workout_exercise_id=data["workout_exercise_id"],
        set_number=set_number,
        weight=data["current_weight"],
        reps=reps,
    )

    tonnage = data["current_weight"] * reps
    await state.update_data(set_number=set_number + 1)

    await message.answer(
        f"✅ Подход {set_number} записан: "
        f"{data['current_weight']} кг × {reps} = {tonnage:.0f} кг\n\n"
        f"Что дальше?",
        reply_markup=after_set_keyboard(),
    )


@router.callback_query(F.data == "set:finish")
async def finish_workout(callback: CallbackQuery, state: FSMContext) -> None:
    """Завершает тренировку и показывает итоговый тоннаж."""
    data = await state.get_data()
    workout_id = data.get("workout_id")

    if not workout_id:
        await callback.answer("Активная тренировка не найдена", show_alert=True)
        return

    total_tonnage = await db.calculate_workout_tonnage(workout_id)
    await db.finish_workout(workout_id, total_tonnage)
    await state.clear()

    await callback.message.edit_text(
        f"🎉 Тренировка завершена!\n\n"
        f"Суммарный тоннаж: <b>{total_tonnage:.0f} кг</b>\n"
        f"Отличная работа!"
    )
    await callback.answer("Тренировка сохранена!")
