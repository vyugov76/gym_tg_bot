"""Управление кастомными упражнениями в профиле."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database.requests as db
from keyboards.menu import exercise_manage_keyboard, my_exercises_keyboard
from states.workout_states import EditExerciseStates

router = Router(name="exercises")
logger = logging.getLogger(__name__)


def _log_callback(callback: CallbackQuery) -> None:
    logger.info(
        "Inline-кнопка: user_id=%s callback_data=%s",
        callback.from_user.id,
        callback.data,
    )


async def _show_exercises_list(
    callback: CallbackQuery,
    db_user_id: int,
    telegram_id: int,
) -> None:
    exercises = await db.get_exercises_by_user_id(db_user_id)
    logger.info(
        f"Пользователь {telegram_id} открыл список упражнений. Найдено: {len(exercises)}"
    )

    if exercises:
        text = "📋 <b>Мои упражнения</b>\n\nВыберите упражнение для управления:"
    else:
        text = (
            "📋 <b>Мои упражнения</b>\n\n"
            "У вас пока нет упражнений.\n"
            "Создайте первое во время тренировки — кнопка «Создать новое упражнение»."
        )

    await callback.message.edit_text(
        text,
        reply_markup=my_exercises_keyboard(exercises),
    )


@router.message(F.text == "Мои упражнения")
async def show_my_exercises(message: Message, state: FSMContext) -> None:
    """Показывает список упражнений пользователя."""
    await state.clear()
    user_id = message.from_user.id
    user = await db.get_user_by_telegram_id(user_id)

    if not user:
        logger.warning("Незарегистрированный user_id=%s запросил «Мои упражнения»", user_id)
        await message.answer("Сначала нажмите /start для регистрации.")
        return

    exercises = await db.get_exercises_by_user_id(user["id"])
    logger.info(
        f"Пользователь {user_id} открыл список упражнений. Найдено: {len(exercises)}"
    )

    if exercises:
        text = "📋 <b>Мои упражнения</b>\n\nВыберите упражнение для управления:"
    else:
        text = (
            "📋 <b>Мои упражнения</b>\n\n"
            "У вас пока нет упражнений.\n"
            "Создайте первое во время тренировки — кнопка «Создать новое упражнение»."
        )

    await message.answer(text, reply_markup=my_exercises_keyboard(exercises))


@router.callback_query(F.data == "myex:noop")
async def noop_callback(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "myex:back")
async def back_to_exercises_list(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат к списку упражнений."""
    _log_callback(callback)
    await state.clear()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    await _show_exercises_list(callback, user["id"], callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("myex:view:"))
async def view_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    """Меню управления упражнением."""
    _log_callback(callback)
    exercise_id = int(callback.data.split(":")[-1])

    try:
        exercise = await db.get_exercise_by_id(exercise_id)
    except Exception:
        logger.exception(
            "Ошибка загрузки упражнения: user_id=%s exercise_id=%s",
            callback.from_user.id,
            exercise_id,
        )
        await callback.answer("Ошибка загрузки упражнения", show_alert=True)
        return

    if not exercise:
        await callback.answer("Упражнение не найдено", show_alert=True)
        return

    type_label = "собственный вес" if exercise["is_bodyweight"] else "с весом"
    await callback.message.edit_text(
        f"🏋️ <b>{exercise['name']}</b>\n"
        f"Тип: {type_label}\n\n"
        f"Выберите действие:",
        reply_markup=exercise_manage_keyboard(exercise),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("myex:rename:"))
async def rename_exercise_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Запуск переименования упражнения."""
    _log_callback(callback)
    exercise_id = int(callback.data.split(":")[-1])
    await state.set_state(EditExerciseStates.waiting_for_new_name)
    await state.update_data(editing_exercise_id=exercise_id)
    logger.info(
        "FSM user_id=%s: переименование упражнения exercise_id=%s",
        callback.from_user.id,
        exercise_id,
    )
    await callback.message.edit_text(
        "Введите <b>новое название</b> упражнения:"
    )
    await callback.answer()


@router.message(EditExerciseStates.waiting_for_new_name)
async def rename_exercise_finish(message: Message, state: FSMContext) -> None:
    """Сохраняет новое название упражнения."""
    user_id = message.from_user.id
    new_name = (message.text or "").strip()
    data = await state.get_data()
    exercise_id = data.get("editing_exercise_id")

    if not new_name or len(new_name) > 100:
        logger.warning(
            "Некорректное новое название: user_id=%s text=%r",
            user_id,
            message.text,
        )
        await message.answer("Введите название от 1 до 100 символов:")
        return

    try:
        await db.update_exercise_name(exercise_id, new_name)
        exercise = await db.get_exercise_by_id(exercise_id)
    except Exception:
        logger.exception(
            "Не удалось переименовать упражнение: user_id=%s exercise_id=%s",
            user_id,
            exercise_id,
        )
        await message.answer("Не удалось обновить название. Попробуйте позже.")
        return

    await state.clear()
    logger.info(
        f"Пользователь {user_id} изменил название упражнения {exercise_id} на '{new_name}'"
    )

    type_label = "собственный вес" if exercise["is_bodyweight"] else "с весом"
    await message.answer(
        f"✅ Название обновлено!\n\n"
        f"🏋️ <b>{exercise['name']}</b>\n"
        f"Тип: {type_label}\n\n"
        f"Выберите действие:",
        reply_markup=exercise_manage_keyboard(exercise),
    )


@router.callback_query(F.data.startswith("myex:toggle:"))
async def toggle_exercise_type(callback: CallbackQuery, state: FSMContext) -> None:
    """Переключает тип упражнения (с весом / собственный вес)."""
    _log_callback(callback)
    user_id = callback.from_user.id
    exercise_id = int(callback.data.split(":")[-1])

    try:
        new_status = await db.toggle_exercise_bodyweight(exercise_id)
        exercise = await db.get_exercise_by_id(exercise_id)
    except Exception:
        logger.exception(
            "Не удалось переключить тип упражнения: user_id=%s exercise_id=%s",
            user_id,
            exercise_id,
        )
        await callback.answer("Ошибка обновления типа", show_alert=True)
        return

    logger.info(
        f"Пользователь {user_id} переключил тип упражнения {exercise_id}: "
        f"новое значение is_bodyweight={int(new_status)}"
    )

    type_label = "собственный вес" if exercise["is_bodyweight"] else "с весом"
    await callback.message.edit_text(
        f"🏋️ <b>{exercise['name']}</b>\n"
        f"Тип: {type_label}\n\n"
        f"Выберите действие:",
        reply_markup=exercise_manage_keyboard(exercise),
    )
    await callback.answer("Тип упражнения обновлён")
