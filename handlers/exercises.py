"""
exercises - управление каталогом упражнений

Просмотр карточки упражнения, переименование, мягкое удаление и смена типа.
Работает в контексте настроек: категория или несортированные упражнения.

Ключевые обработчики:
- _type_label, _show_exercises_context - вспомогательные функции
- noop_callback, back_to_exercises_context - навигация по списку
- view_exercise - карточка упражнения
- delete_exercise - удаление из каталога
- rename_exercise_start, rename_exercise_finish - переименование
- toggle_exercise_type - циклическая смена типа
"""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database.requests as db
from keyboards.menu import (
    category_detail_keyboard,
    exercise_manage_keyboard,
    my_exercises_keyboard,
)
from states.workout_states import EditExerciseStates
from utils.exercise_types import EXERCISE_TYPE_LABELS, normalize_exercise_type

router = Router(name="exercises")
logger = logging.getLogger(__name__)


def _type_label(exercise: dict) -> str:
    """
    Возвращает читаемую подпись типа упражнения.

    Параметры:
        exercise: словарь упражнения с полями exercise_type или is_bodyweight

    Возвращает:
        Русскоязычная метка типа или «неизвестно»
    """
    exercise_type = normalize_exercise_type(
        exercise.get("exercise_type", exercise.get("is_bodyweight"))
    )
    return EXERCISE_TYPE_LABELS.get(exercise_type, "неизвестно")


async def _show_exercises_context(
    callback: CallbackQuery,
    state: FSMContext,
    db_user_id: int,
) -> None:
    """
    Показывает список упражнений в текущем контексте настроек.

    Берёт category_id из FSM: None - несортированные, иначе - упражнения категории.
    Для категории дополнительно отправляет клавиатуру действий с категорией.

    Параметры:
        callback: callback-запрос с сообщением для редактирования
        state: контекст FSM с settings_category_id и settings_category_name
        db_user_id: внутренний id пользователя в БД
    """
    data = await state.get_data()
    category_id = data.get("settings_category_id")

    if category_id is None:
        exercises = await db.get_unsorted_exercises(db_user_id)
        title = "📁 <b>Несортированные</b>"
    else:
        category_name = data.get("settings_category_name", "Категория")
        exercises = await db.get_exercises_by_category(db_user_id, category_id)
        title = f"📂 <b>{category_name}</b>"

    await callback.message.edit_text(
        f"{title}\n\nУпражнения ({len(exercises)}):",
        reply_markup=my_exercises_keyboard(exercises),
    )
    if category_id is not None:
        await callback.message.answer(
            "Действия с категорией:",
            reply_markup=category_detail_keyboard(category_id),
        )


@router.callback_query(F.data == "myex:noop")
async def noop_callback(callback: CallbackQuery) -> None:
    """
    Заглушка для неактивных кнопок в списке упражнений.

    Параметры:
        callback: callback-запрос без побочных действий
    """
    await callback.answer()


@router.callback_query(F.data == "myex:back_ctx")
async def back_to_exercises_context(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Возвращает к списку упражнений в категории или несортированных.

    Параметры:
        callback: callback-запрос с кнопкой «назад»
        state: контекст FSM с выбранной категорией настроек
    """
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return
    await _show_exercises_context(callback, state, user["id"])
    await callback.answer()


@router.callback_query(F.data.startswith("myex:view:"))
async def view_exercise(callback: CallbackQuery) -> None:
    """
    Показывает карточку упражнения с доступными действиями.

    Параметры:
        callback: callback-запрос с id упражнения в data
    """
    exercise_id = int(callback.data.split(":")[-1])

    try:
        exercise = await db.get_exercise_by_id(exercise_id)
    except Exception:
        logger.exception("Ошибка загрузки упражнения: exercise_id=%s", exercise_id)
        await callback.answer("Ошибка загрузки упражнения", show_alert=True)
        return

    if not exercise or exercise.get("workout_id") is not None:
        await callback.answer("Упражнение не найдено", show_alert=True)
        return

    is_admin = exercise.get("id_user") is None
    header = f"🏋️ <b>{exercise['name']}</b>\nТип: {_type_label(exercise)}"
    if is_admin:
        header += "\n\n🌐 Общее упражнение (доступно всем пользователям)"
    else:
        header += "\n\nВыберите действие:"

    await callback.message.edit_text(
        header,
        reply_markup=exercise_manage_keyboard(exercise),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("myex:delete:"))
async def delete_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Мягко удаляет пользовательское упражнение из каталога.

    Доступно только владельцу упражнения. После удаления возвращает
    к списку упражнений в текущем контексте настроек.

    Параметры:
        callback: callback-запрос с id упражнения в data
        state: контекст FSM с выбранной категорией настроек
    """
    exercise_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    exercise = await db.get_exercise_by_id(exercise_id)
    if not exercise or exercise.get("id_user") != user["id"]:
        await callback.answer("Нельзя удалить это упражнение", show_alert=True)
        return

    try:
        await db.soft_delete_global_exercise(exercise_id, user["id"])
    except Exception:
        logger.exception("Ошибка удаления упражнения: exercise_id=%s", exercise_id)
        await callback.answer("Не удалось удалить упражнение", show_alert=True)
        return

    await _show_exercises_context(callback, state, user["id"])
    await callback.answer("Упражнение удалено из каталога")


@router.callback_query(F.data.startswith("myex:rename:"))
async def rename_exercise_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начинает переименование пользовательского упражнения.

    Общие (админские) упражнения переименовывать нельзя.

    Параметры:
        callback: callback-запрос с id упражнения в data
        state: контекст FSM для ввода нового названия
    """
    exercise_id = int(callback.data.split(":")[-1])
    exercise = await db.get_exercise_by_id(exercise_id)
    if not exercise or exercise.get("id_user") is None:
        await callback.answer("Общие упражнения нельзя переименовывать", show_alert=True)
        return
    await state.set_state(EditExerciseStates.waiting_for_new_name)
    await state.update_data(editing_exercise_id=exercise_id)
    await callback.message.edit_text("Введите <b>новое название</b> упражнения:")
    await callback.answer()


@router.message(EditExerciseStates.waiting_for_new_name)
async def rename_exercise_finish(message: Message, state: FSMContext) -> None:
    """
    Сохраняет новое название упражнения и показывает обновлённую карточку.

    Параметры:
        message: текстовое сообщение с новым названием
        state: контекст FSM с editing_exercise_id
    """
    new_name = (message.text or "").strip()
    data = await state.get_data()
    exercise_id = data.get("editing_exercise_id")

    if not new_name or len(new_name) > 100:
        await message.answer("Введите название от 1 до 100 символов:")
        return

    user = await db.get_user_by_telegram_id(message.from_user.id)
    exercise = await db.get_exercise_by_id(exercise_id)
    if not user or not exercise or exercise.get("id_user") != user["id"]:
        await message.answer("Нельзя переименовать это упражнение.")
        return

    try:
        await db.update_exercise_name(exercise_id, new_name)
        exercise = await db.get_exercise_by_id(exercise_id)
    except Exception:
        logger.exception("Не удалось переименовать упражнение: exercise_id=%s", exercise_id)
        await message.answer("Не удалось обновить название. Попробуйте позже.")
        return

    await state.set_state(None)
    await message.answer(
        f"✅ Название обновлено!\n\n"
        f"🏋️ <b>{exercise['name']}</b>\n"
        f"Тип: {_type_label(exercise)}\n\n"
        f"Выберите действие:",
        reply_markup=exercise_manage_keyboard(exercise),
    )


@router.callback_query(F.data.startswith("myex:toggle:"))
async def toggle_exercise_type(callback: CallbackQuery) -> None:
    """
    Циклически переключает тип пользовательского упражнения.

    Общие (админские) упражнения изменять нельзя.

    Параметры:
        callback: callback-запрос с id упражнения в data
    """
    exercise_id = int(callback.data.split(":")[-1])
    exercise = await db.get_exercise_by_id(exercise_id)
    if not exercise or exercise.get("id_user") is None:
        await callback.answer("Общие упражнения нельзя изменять", show_alert=True)
        return

    try:
        await db.cycle_exercise_type(exercise_id)
        exercise = await db.get_exercise_by_id(exercise_id)
    except Exception:
        logger.exception("Не удалось переключить тип: exercise_id=%s", exercise_id)
        await callback.answer("Ошибка обновления типа", show_alert=True)
        return

    await callback.message.edit_text(
        f"🏋️ <b>{exercise['name']}</b>\n"
        f"Тип: {_type_label(exercise)}\n\n"
        f"Выберите действие:",
        reply_markup=exercise_manage_keyboard(exercise),
    )
    await callback.answer("Тип упражнения обновлён")
