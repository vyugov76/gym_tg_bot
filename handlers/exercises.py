"""
exercises - управление каталогом упражнений

Просмотр карточки упражнения, переименование, мягкое удаление, смена типа
и быстрое создание упражнения из просмотра категории в настройках.

Ключевые обработчики:
- _show_exercises_context, _reply_exercises_list - список упражнений категории
- shortcut_add_ex_start, settings_shortcut_exercise_name - создание из категории
- view_exercise, delete_exercise, rename, toggle - карточка упражнения
"""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

import database.requests as db
from keyboards.menu import (
    exercise_manage_keyboard,
    my_exercises_keyboard,
)
from states.workout_states import EditExerciseStates, ExerciseStates
from utils.exercise_types import (
    EXERCISE_TYPE_LABELS,
    EXERCISE_WEIGHTED,
    normalize_exercise_type,
)
from utils.screen_message import (
    show_screen_callback,
    show_screen_message,
    store_screen_message,
)

router = Router(name="exercises")
logger = logging.getLogger(__name__)


def _category_token(category_id: int | None) -> str:
    """
    Формирует токен категории для callback_data клавиатуры.

    Параметры:
        category_id: id категории или None для несортированных

    Возвращает:
        Строка id категории или none
    """
    return "none" if category_id is None else str(category_id)


def _parse_shortcut_category_id(raw: str) -> int | None:
    """
    Разбирает category_id из callback_data shortcut_add_ex.

    Параметры:
        raw: часть callback после shortcut_add_ex:

    Возвращает:
        id категории или None для несортированных
    """
    return None if raw == "none" else int(raw)


async def _settings_shortcut_create_filter(
    _: Message,
    state: FSMContext,
) -> bool:
    """
    Фильтр FSM: создание упражнения из просмотра категории в настройках.

    Параметры:
        _: сообщение пользователя (не используется)
        state: контекст FSM

    Возвращает:
        True, если активен сценарий shortcut_add_ex
    """
    data = await state.get_data()
    return bool(data.get("settings_shortcut_create"))


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


def _exercise_card_text(exercise: dict) -> str:
    """
    Формирует текст карточки упражнения.

    Параметры:
        exercise: словарь упражнения из БД

    Возвращает:
        HTML-текст карточки с типом и подсказкой
    """
    is_admin = exercise.get("id_user") is None
    header = f"🏋️ <b>{exercise['name']}</b>\nТип: {_type_label(exercise)}"
    if is_admin:
        header += "\n\n🌐 Общее упражнение (доступно всем пользователям)"
    else:
        header += "\n\nВыберите действие:"
    return header


def build_exercises_view_content(
    category_id: int | None,
    category_name: str | None,
    exercises: list[dict],
    *,
    notice: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Формирует текст и клавиатуру списка упражнений в настройках.

    Параметры:
        category_id: id категории или None для несортированных
        category_name: название категории из FSM
        exercises: список упражнений
        notice: необязательное сообщение над заголовком

    Возвращает:
        Кортеж (текст сообщения, клавиатура)
    """
    if category_id is None:
        title = "📁 <b>Несортированные</b>"
        count_label = "Упражнения"
    else:
        title = f"📂 <b>{category_name or 'Категория'}</b>"
        count_label = "Упражнения в категории"

    text = f"{title}\n\n{count_label} ({len(exercises)}):"
    if notice:
        text = f"{notice}\n\n{text}"

    markup = my_exercises_keyboard(
        exercises,
        category_token=_category_token(category_id),
    )
    return text, markup


async def _show_exercises_context(
    callback: CallbackQuery,
    state: FSMContext,
    db_user_id: int,
    *,
    notice: str | None = None,
) -> None:
    """
    Показывает список упражнений в текущем контексте настроек.

    Берёт category_id из FSM: None - несортированные, иначе - упражнения категории.

    Параметры:
        callback: callback-запрос с сообщением для редактирования
        state: контекст FSM с settings_category_id и settings_category_name
        db_user_id: внутренний id пользователя в БД
        notice: необязательное сообщение над заголовком списка
    """
    data = await state.get_data()
    category_id = data.get("settings_category_id")

    if category_id is None:
        exercises = await db.get_unsorted_exercises(db_user_id)
    else:
        exercises = await db.get_exercises_by_category(db_user_id, category_id)

    text, markup = build_exercises_view_content(
        category_id,
        data.get("settings_category_name"),
        exercises,
        notice=notice,
    )

    await show_screen_callback(callback, state, text, markup)


async def _reply_exercises_list(
    message: Message,
    state: FSMContext,
    db_user_id: int,
    *,
    notice: str | None = None,
) -> None:
    """
    Обновляет список упражнений после ввода текста в FSM.

    Редактирует сохранённое сообщение категории, чтобы не плодить новые экраны.

    Параметры:
        message: сообщение пользователя после FSM
        state: контекст FSM с settings_category_id
        db_user_id: внутренний id пользователя в БД
        notice: необязательное сообщение об успешном действии
    """
    data = await state.get_data()
    category_id = data.get("settings_category_id")

    if category_id is None:
        exercises = await db.get_unsorted_exercises(db_user_id)
    else:
        exercises = await db.get_exercises_by_category(db_user_id, category_id)

    text, markup = build_exercises_view_content(
        category_id,
        data.get("settings_category_name"),
        exercises,
        notice=notice,
    )

    await show_screen_message(message, state, text, markup)


@router.callback_query(F.data.startswith("shortcut_add_ex:"))
async def shortcut_add_ex_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начинает создание упражнения в текущей категории из настроек.

    Сохраняет category_id в FSM и переводит в ожидание названия.

    Параметры:
        callback: inline-кнопка shortcut_add_ex:{category_id|none}
        state: контекст FSM настроек
    """
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    raw_category = callback.data.split(":")[-1]
    category_id = _parse_shortcut_category_id(raw_category)

    if category_id is not None:
        category = await db.get_category_by_id(category_id)
        if not category or category["id_user"] != user["id"]:
            await callback.answer("Категория не найдена", show_alert=True)
            return
        category_name = category["name"]
    else:
        category_name = None

    await state.update_data(
        settings_category_id=category_id,
        settings_category_name=category_name,
        settings_shortcut_create=True,
        pending_shortcut_category_id=category_id,
    )
    await state.set_state(ExerciseStates.waiting_for_name)

    scope = category_name or "Несортированные"
    await callback.message.edit_text(
        f"📂 Категория: <b>{scope}</b>\n\n"
        "Введите <b>название</b> нового упражнения (например, Жим штанги лёжа):"
    )
    await callback.answer()


@router.message(ExerciseStates.waiting_for_name, _settings_shortcut_create_filter)
async def settings_shortcut_exercise_name(
    message: Message,
    state: FSMContext,
) -> None:
    """
    Принимает название и создаёт упражнение в выбранной категории настроек.

    Проверяет уникальность имени, сохраняет в каталог и возвращает к списку.

    Параметры:
        message: текстовое сообщение с названием упражнения
        state: контекст FSM с pending_shortcut_category_id
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
    category_id = data.get("pending_shortcut_category_id")
    if category_id is not None:
        category = await db.get_category_by_id(category_id)
        if not category or category["id_user"] != user["id"]:
            await state.clear()
            await message.answer("Категория не найдена. Откройте категорию заново.")
            return

    try:
        if await db.user_has_catalog_exercise_name(user["id"], name):
            await message.answer(
                f"Упражнение <b>{name}</b> уже есть в вашем каталоге.\n"
                "Введите другое название:"
            )
            return

        await db.add_global_exercise(
            user_id=user["id"],
            exercise_name=name,
            exercise_type=EXERCISE_WEIGHTED,
            category_id=category_id,
        )
    except Exception:
        logger.exception(
            "Ошибка создания упражнения из категории: user_id=%s",
            message.from_user.id,
        )
        await message.answer("Не удалось создать упражнение. Попробуйте позже.")
        return

    await state.update_data(
        settings_shortcut_create=False,
        pending_shortcut_category_id=None,
    )
    await state.set_state(None)

    await _reply_exercises_list(
        message,
        state,
        user["id"],
        notice=f"✅ Упражнение <b>{name}</b> создано!",
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
async def view_exercise(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Показывает карточку упражнения с доступными действиями.

    Параметры:
        callback: callback-запрос с id упражнения в data
        state: контекст FSM для сохранения экранного сообщения
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

    await show_screen_callback(
        callback,
        state,
        _exercise_card_text(exercise),
        exercise_manage_keyboard(exercise),
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
    await show_screen_message(
        message,
        state,
        f"✅ Название обновлено!\n\n{_exercise_card_text(exercise)}",
        exercise_manage_keyboard(exercise),
    )


@router.callback_query(F.data.startswith("myex:toggle:"))
async def toggle_exercise_type(callback: CallbackQuery, state: FSMContext) -> None:
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

    await show_screen_callback(
        callback,
        state,
        _exercise_card_text(exercise),
        exercise_manage_keyboard(exercise),
    )
    await callback.answer("Тип упражнения обновлён")
