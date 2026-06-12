"""
settings - настройки аккаунта и конструктора

Категории упражнений, готовые программы (шаблоны), профиль пользователя
и массовый выбор упражнений для категорий и шаблонов.

Ключевые обработчики:
- show_settings, settings_back - меню настроек
- show_profile, edit_height_start, edit_weight_start - профиль
- show_categories, view_category, rename_category, delete_category - категории
- show_presets, create_preset_start, view_preset, delete_preset - шаблоны
- bulk_toggle, bulk_confirm, bulk_cancel - массовый выбор упражнений
- preset_edit_sets_start, preset_edit_sets_apply - редактирование подходов шаблона
"""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database.requests as db
from handlers.exercises import build_exercises_view_content
from keyboards.bulk_select import bulk_select_keyboard
from keyboards.menu import (
    categories_list_keyboard,
    my_exercises_keyboard,
    preset_detail_keyboard,
    presets_list_keyboard,
    template_edit_sets_keyboard,
    profile_keyboard,
    settings_menu_keyboard,
)
from states.workout_states import (
    CategoryStates,
    PresetBulkAddStates,
    PresetCreateStates,
    ProfileEditStates,
    TemplateEditStates,
)
from utils.preset_helpers import format_preset_exercises_list, parse_sets_count_input
from utils.screen_message import show_screen_callback, show_screen_message, store_screen_message

router = Router(name="settings")
logger = logging.getLogger(__name__)


def _format_preset_exercises(exercises: list[dict]) -> str:
    """
    Форматирует список упражнений шаблона для отображения в сообщении.

    Параметры:
        exercises: список упражнений шаблона из БД

    Возвращает:
        Многострочный текст со списком упражнений и числом подходов
    """
    return format_preset_exercises_list(exercises)


def _profile_text(user: dict) -> str:
    """
    Формирует текст экрана профиля пользователя.

    Параметры:
        user: запись пользователя из БД

    Возвращает:
        HTML-текст с ростом, весом и датой регистрации
    """
    return (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"Рост: {user['height']} см\n"
        f"Вес: {user['weight']} кг\n"
        f"Дата регистрации: {user['created_at'].strftime('%d.%m.%Y')}"
    )


async def _build_preset_add_queue(
    exercise_ids: list[int],
    id_user: int,
) -> list[dict]:
    """
    Собирает очередь упражнений для пошагового добавления в шаблон.

    Параметры:
        exercise_ids: идентификаторы выбранных упражнений
        id_user: внутренний id пользователя в БД

    Возвращает:
        Список словарей с полями name и exercise_type для FSM
    """
    queue: list[dict] = []
    for exercise_id in exercise_ids:
        exercise = await db.get_exercise_by_id(exercise_id)
        if not exercise or exercise.get("workout_id") is not None:
            continue
        ex_owner = exercise.get("id_user")
        if ex_owner is not None and ex_owner != id_user:
            continue
        queue.append({
            "name": exercise["name"],
            "exercise_type": exercise["is_bodyweight"],
        })
    return queue


async def _prompt_preset_add_sets_count(
    target: CallbackQuery | Message,
    state: FSMContext,
    exercise: dict,
    index: int,
    total: int,
) -> None:
    """
    Запрашивает количество подходов при массовом добавлении в шаблон.

    Параметры:
        target: сообщение или callback для ответа пользователю
        state: контекст FSM с очередью preset_add_queue
        exercise: текущее упражнение из очереди
        index: индекс упражнения в очереди (с нуля)
        total: общее число упражнений в очереди
    """
    text = (
        f"Упражнение {index + 1}/{total}: <b>{exercise['name']}</b>\n"
        f"Введите количество подходов для этого упражнения "
        f"(0 - не указывать):"
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text)
        await store_screen_message(state, target.message)
    else:
        await show_screen_message(target, state, text)


def _format_template_edit_list(exercises: list[dict]) -> str:
    """
    Формирует текст списка упражнений для редактирования числа подходов.

    Параметры:
        exercises: упражнения шаблона из БД

    Возвращает:
        Многострочный текст с нумерованным списком и текущим sets_count
    """
    lines = [
        "Выберите номер упражнения для изменения количества подходов "
        "или нажмите 'Готово':",
    ]
    for idx, ex in enumerate(exercises, start=1):
        sets_count = int(ex.get("sets_count") or 0)
        lines.append(f"{idx}) {ex['name']} (сейчас: {sets_count})")
    return "\n".join(lines)


async def _show_template_edit_selection(
    target: CallbackQuery | Message,
    state: FSMContext,
    preset_id: int,
    exercises: list[dict],
    *,
    notice: str | None = None,
) -> None:
    """
    Показывает экран выбора упражнения для изменения числа подходов.

    Параметры:
        target: сообщение или callback для редактирования/ответа
        state: контекст FSM
        preset_id: id шаблона
        exercises: актуальный список упражнений шаблона
        notice: необязательное уведомление над списком
    """
    await state.update_data(
        template_edit_preset_id=preset_id,
        template_edit_exercises=exercises,
    )
    await state.set_state(TemplateEditStates.waiting_for_exercise_selection)

    text = _format_template_edit_list(exercises)
    if notice:
        text = f"{notice}\n\n{text}"
    keyboard = template_edit_sets_keyboard(preset_id, exercises)

    if isinstance(target, CallbackQuery):
        await show_screen_callback(target, state, text, keyboard)
    else:
        await show_screen_message(target, state, text, keyboard)


async def _begin_template_edit_sets_count(
    target: CallbackQuery | Message,
    state: FSMContext,
    preset_id: int,
    exercises: list[dict],
    index: int,
) -> None:
    """
    Переводит FSM к вводу нового числа подходов для выбранного упражнения.

    Параметры:
        target: сообщение или callback
        state: контекст FSM
        preset_id: id шаблона
        exercises: список упражнений шаблона
        index: индекс упражнения в списке (с нуля)
    """
    if index < 0 or index >= len(exercises):
        msg = "Номер вне списка. Выберите упражнение из списка."
        if isinstance(target, CallbackQuery):
            await target.answer(msg, show_alert=True)
        else:
            await target.answer(msg)
        return

    exercise = exercises[index]
    await state.update_data(
        template_edit_preset_id=preset_id,
        template_edit_exercises=exercises,
        template_edit_exercise_id=int(exercise["id"]),
    )
    await state.set_state(TemplateEditStates.waiting_for_sets_count)

    prompt = (
        f"Упражнение: <b>{exercise['name']}</b>. "
        f"Введите новое количество подходов (0 - не указывать):"
    )
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(prompt)
        await store_screen_message(state, target.message)
        await target.answer()
    else:
        await show_screen_message(target, state, prompt)


async def _render_category_view(
    callback: CallbackQuery,
    state: FSMContext,
    category_id: int,
    id_user: int,
    *,
    notice: str | None = None,
) -> None:
    """
    Отображает категорию с упражнениями и клавиатурой действий.

    Параметры:
        callback: callback-запрос для edit_text и answer
        state: контекст FSM
        category_id: id категории
        id_user: внутренний id пользователя
        notice: необязательное сообщение над заголовком
    """
    category = await db.get_category_by_id(category_id)
    if not category or category["id_user"] != id_user:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    exercises = await db.get_exercises_by_category(id_user, category_id)
    await state.update_data(
        settings_category_id=category_id,
        settings_category_name=category["name"],
        bulk_selected_ids=[],
    )

    text, markup = build_exercises_view_content(
        category_id,
        category["name"],
        exercises,
        notice=notice,
    )
    await show_screen_callback(callback, state, text, markup)


async def _render_preset_view(
    target: CallbackQuery | Message,
    state: FSMContext,
    preset_id: int,
    id_user: int,
    *,
    notice: str | None = None,
) -> None:
    """
    Отображает карточку шаблона с упражнениями и клавиатурой действий.

    Параметры:
        target: callback или сообщение для ответа
        preset_id: id шаблона
        id_user: внутренний id пользователя
        notice: необязательное сообщение над заголовком
    """
    preset = await db.get_preset_by_id(preset_id)
    if not preset or preset["id_user"] != id_user:
        if isinstance(target, CallbackQuery):
            await target.answer("Программа не найдена", show_alert=True)
        return

    exercises = await db.get_preset_exercises(preset_id)
    text = f"📋 <b>{preset['name']}</b>\n\n{_format_preset_exercises(exercises)}"
    if notice:
        text = f"{notice}\n\n{text}"

    markup = preset_detail_keyboard(preset_id)
    if isinstance(target, CallbackQuery):
        await show_screen_callback(target, state, text, markup)
    else:
        await show_screen_message(target, state, text, markup)


async def _load_bulk_exercises(
    mode: str,
    context_id: int,
    id_user: int,
) -> list[dict]:
    """
    Загружает список упражнений для режима массового выбора.

    Параметры:
        mode: режим (cat_add, cat_rm, preset_add, preset_rm)
        context_id: id категории или шаблона
        id_user: внутренний id пользователя

    Возвращает:
        Список упражнений для отображения в bulk_select_keyboard
    """
    if mode == "cat_add":
        return await db.get_unsorted_exercises(id_user)
    if mode == "cat_rm":
        return await db.get_exercises_by_category(id_user, context_id)
    if mode == "preset_add":
        return await db.get_global_exercises_by_user_id(id_user)
    if mode == "preset_rm":
        return await db.get_preset_exercises(context_id)
    return []


async def _filter_owned_exercise_ids(
    exercise_ids: list[int],
    id_user: int,
) -> list[int]:
    """
    Оставляет только упражнения, принадлежащие пользователю.

    Параметры:
        exercise_ids: выбранные id упражнений
        id_user: внутренний id пользователя

    Возвращает:
        Подмножество exercise_ids, где id_user совпадает с владельцем
    """
    owned: list[int] = []
    for exercise_id in exercise_ids:
        exercise = await db.get_exercise_by_id(exercise_id)
        if exercise and exercise.get("id_user") == id_user:
            owned.append(exercise_id)
    return owned


def _bulk_title(mode: str, context_name: str) -> str:
    """
    Возвращает заголовок экрана массового выбора упражнений.

    Параметры:
        mode: режим bulk (cat_add, cat_rm, preset_add, preset_rm)
        context_name: название категории или шаблона

    Возвращает:
        Текст заголовка для edit_text
    """
    titles = {
        "cat_add": f"➕ Добавление в «{context_name}»\n\nОтметьте несортированные упражнения:",
        "cat_rm": f"➖ Удаление из «{context_name}»\n\nОтметьте упражнения для переноса в «Несортированные»:",
        "preset_add": f"➕ Добавление в «{context_name}»\n\nОтметьте упражнения для шаблона:",
        "preset_rm": f"➖ Удаление из «{context_name}»\n\nОтметьте упражнения для удаления из шаблона:",
    }
    return titles.get(mode, "Выберите упражнения:")


@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message, state: FSMContext) -> None:
    """
    Открывает меню настроек по пункту главного меню.

    Параметры:
        message: входящее сообщение с текстом кнопки
        state: контекст FSM, сбрасывается при входе
    """
    await state.clear()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start для регистрации.")
        return

    await message.answer(
        "Настройки аккаунта и конструктора:",
        reply_markup=settings_menu_keyboard(),
    )


@router.callback_query(F.data == "settings:back")
async def settings_back(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Возвращает к корневому меню настроек.

    Параметры:
        callback: inline-кнопка «Назад»
        state: контекст FSM, сбрасывается
    """
    await state.clear()
    await show_screen_callback(
        callback,
        state,
        "Настройки аккаунта и конструктора:",
        settings_menu_keyboard(),
    )
    await callback.answer()


# --- Профиль ---


@router.callback_query(F.data == "settings:profile")
async def show_profile(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Показывает профиль пользователя: рост, вес, дата регистрации.

    Параметры:
        callback: inline-кнопка «Профиль»
        state: контекст FSM, сбрасывается
    """
    await state.clear()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    await show_screen_callback(
        callback,
        state,
        _profile_text(user),
        profile_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "profile:edit_height")
async def edit_height_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начинает редактирование роста пользователя.

    Параметры:
        callback: inline-кнопка изменения роста
        state: переводится в ProfileEditStates.waiting_for_height
    """
    await state.set_state(ProfileEditStates.waiting_for_height)
    await callback.message.edit_text(
        "Введите новый <b>рост в см</b> (от 100 до 250):"
    )
    await store_screen_message(state, callback.message)
    await callback.answer()


@router.callback_query(F.data == "profile:edit_weight")
async def edit_weight_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начинает редактирование веса пользователя.

    Параметры:
        callback: inline-кнопка изменения веса
        state: переводится в ProfileEditStates.waiting_for_weight
    """
    await state.set_state(ProfileEditStates.waiting_for_weight)
    await callback.message.edit_text(
        "Введите новый <b>вес в кг</b> (от 30 до 300):"
    )
    await store_screen_message(state, callback.message)
    await callback.answer()


@router.message(ProfileEditStates.waiting_for_height)
async def edit_height_finish(message: Message, state: FSMContext) -> None:
    """
    Сохраняет новый рост пользователя в БД.

    Параметры:
        message: текстовое сообщение с ростом в см
        state: контекст FSM редактирования профиля
    """
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer("Сначала нажмите /start для регистрации.")
        return

    try:
        height = float(message.text.replace(",", "."))
        if not (100 <= height <= 250):
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Введите корректный рост числом от 100 до 250 см:")
        return

    try:
        await db.update_user_height(user["id"], height)
    except Exception:
        logger.exception("Ошибка обновления роста: user_id=%s", message.from_user.id)
        await message.answer("Не удалось обновить рост. Попробуйте позже.")
        return

    await state.clear()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    await show_screen_message(
        message,
        state,
        f"✅ Рост обновлён: <b>{height} см</b>\n\n{_profile_text(user)}",
        profile_keyboard(),
    )


@router.message(ProfileEditStates.waiting_for_weight)
async def edit_weight_finish(message: Message, state: FSMContext) -> None:
    """
    Сохраняет новый вес пользователя в БД.

    Параметры:
        message: текстовое сообщение с весом в кг
        state: контекст FSM редактирования профиля
    """
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer("Сначала нажмите /start для регистрации.")
        return

    try:
        weight = float(message.text.replace(",", "."))
        if not (30 <= weight <= 300):
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Введите корректный вес числом от 30 до 300 кг:")
        return

    try:
        await db.update_user_weight(user["id"], weight)
    except Exception:
        logger.exception("Ошибка обновления веса: user_id=%s", message.from_user.id)
        await message.answer("Не удалось обновить вес. Попробуйте позже.")
        return

    await state.clear()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    await show_screen_message(
        message,
        state,
        f"✅ Вес обновлён: <b>{weight} кг</b>\n\n{_profile_text(user)}",
        profile_keyboard(),
    )


# --- Категории ---


@router.callback_query(F.data == "settings:categories")
async def show_categories(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Показывает список категорий упражнений пользователя.

    Параметры:
        callback: inline-кнопка «Категории»
        state: контекст FSM, сбрасывается
    """
    await state.clear()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    categories = await db.get_categories_by_user_id(user["id"])
    text = (
        "📂 <b>Упражнения</b>\n\n"
        "Выберите категорию или создайте новую:"
        if categories
        else "📂 <b>Упражнения</b>\n\nУ вас пока нет категорий."
    )
    await show_screen_callback(
        callback,
        state,
        text,
        categories_list_keyboard(categories),
    )
    await callback.answer()


@router.callback_query(F.data == "cat:create")
async def create_category_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Запрашивает название новой категории упражнений.

    Параметры:
        callback: inline-кнопка создания категории
        state: переводится в CategoryStates.waiting_for_name
    """
    await state.set_state(CategoryStates.waiting_for_name)
    await callback.message.edit_text(
        "Введите <b>название категории</b> (например, Грудь):"
    )
    await store_screen_message(state, callback.message)
    await callback.answer()


@router.message(CategoryStates.waiting_for_name)
async def create_category_finish(message: Message, state: FSMContext) -> None:
    """
    Создаёт категорию с введённым названием и показывает список категорий.

    Параметры:
        message: текстовое сообщение с названием категории
        state: контекст FSM создания категории
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

    try:
        await db.add_category(user["id"], name)
        categories = await db.get_categories_by_user_id(user["id"])
    except Exception:
        logger.exception("Ошибка создания категории: user_id=%s", message.from_user.id)
        await message.answer("Не удалось создать категорию. Попробуйте позже.")
        return

    await state.clear()
    await show_screen_message(
        message,
        state,
        f"✅ Категория <b>{name}</b> создана!\n\n📂 <b>Категории упражнений</b>",
        categories_list_keyboard(categories),
    )


@router.callback_query(F.data == "cat:unsorted")
async def view_unsorted_exercises(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Показывает упражнения без категории (несортированные).

    Параметры:
        callback: inline-кнопка «Несортированные»
        state: сохраняет settings_category_id=None
    """
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    exercises = await db.get_unsorted_exercises(user["id"])
    await state.update_data(settings_category_id=None, settings_category_name=None)

    text, markup = build_exercises_view_content(None, None, exercises)
    await show_screen_callback(callback, state, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("cat:view:"))
async def view_category(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Открывает категорию и список её упражнений.

    Параметры:
        callback: inline-кнопка cat:view:{category_id}
        state: сохраняет id и название категории
    """
    category_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    category = await db.get_category_by_id(category_id)
    if not category or category["id_user"] != user["id"]:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    exercises = await db.get_exercises_by_category(user["id"], category_id)
    await state.update_data(
        settings_category_id=category_id,
        settings_category_name=category["name"],
    )

    text, markup = build_exercises_view_content(
        category_id,
        category["name"],
        exercises,
    )
    await show_screen_callback(callback, state, text, markup)
    await callback.answer()


@router.callback_query(F.data.startswith("cat:rename:"))
async def rename_category_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Запрашивает новое название категории упражнений.

    Параметры:
        callback: inline-кнопка cat:rename:{category_id}
        state: переводится в CategoryStates.waiting_for_rename
    """
    category_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    category = await db.get_category_by_id(category_id)
    if not category or category["id_user"] != user["id"]:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    await store_screen_message(state, callback.message)
    await state.update_data(
        settings_category_id=category_id,
        settings_category_name=category["name"],
        renaming_category_id=category_id,
    )
    await state.set_state(CategoryStates.waiting_for_rename)
    await callback.message.edit_text(
        f"📂 Текущее название: <b>{category['name']}</b>\n\n"
        "Введите <b>новое название</b> категории:"
    )
    await callback.answer()


@router.message(CategoryStates.waiting_for_rename)
async def rename_category_finish(message: Message, state: FSMContext) -> None:
    """
    Сохраняет новое название категории и обновляет экран списка упражнений.

    Параметры:
        message: текстовое сообщение с новым названием
        state: контекст FSM с renaming_category_id
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
    category_id = data.get("renaming_category_id")
    if not category_id:
        await state.clear()
        await message.answer("Категория не найдена. Откройте категорию заново.")
        return

    category = await db.get_category_by_id(category_id)
    if not category or category["id_user"] != user["id"]:
        await state.clear()
        await message.answer("Категория не найдена. Откройте категорию заново.")
        return

    try:
        await db.update_category_name(category_id, user["id"], name)
    except Exception:
        logger.exception(
            "Ошибка переименования категории: user_id=%s category_id=%s",
            message.from_user.id,
            category_id,
        )
        await message.answer("Не удалось обновить название. Попробуйте позже.")
        return

    exercises = await db.get_exercises_by_category(user["id"], category_id)
    await state.update_data(
        settings_category_id=category_id,
        settings_category_name=name,
        renaming_category_id=None,
    )
    await state.set_state(None)

    text, markup = build_exercises_view_content(
        category_id,
        name,
        exercises,
        notice=f"✅ Категория переименована в <b>{name}</b>",
    )
    await show_screen_message(
        message,
        state,
        text,
        markup,
    )


@router.callback_query(F.data.startswith("cat:delete:"))
async def delete_category(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Удаляет категорию и переносит упражнения в «Несортированные».

    Параметры:
        callback: inline-кнопка cat:delete:{category_id}
        state: контекст FSM, сбрасывается после удаления
    """
    category_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    try:
        await db.delete_category(category_id, user["id"])
        categories = await db.get_categories_by_user_id(user["id"])
    except Exception:
        logger.exception(
            "Ошибка удаления категории: user_id=%s category_id=%s",
            callback.from_user.id,
            category_id,
        )
        await callback.answer("Не удалось удалить категорию", show_alert=True)
        return

    await state.clear()
    await show_screen_callback(
        callback,
        state,
        "✅ Категория удалена. Упражнения перенесены в «Несортированные».\n\n"
        "📂 <b>Категории упражнений</b>",
        categories_list_keyboard(categories),
    )
    await callback.answer()


# --- Готовые тренировки ---


@router.callback_query(F.data == "settings:presets")
async def show_presets(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Показывает список сохранённых программ (шаблонов) пользователя.

    Параметры:
        callback: inline-кнопка «Готовые тренировки»
        state: контекст FSM, сбрасывается
    """
    await state.clear()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    presets = await db.get_presets_by_user_id(user["id"])
    text = (
        "📋 <b>Мои готовые тренировки</b>\n\n"
        "Выберите программу:"
        if presets
        else "📋 <b>Мои готовые тренировки</b>\n\nУ вас пока нет сохранённых программ."
    )
    await show_screen_callback(
        callback,
        state,
        text,
        presets_list_keyboard(presets),
    )
    await callback.answer()


@router.callback_query(F.data == "preset:noop")
async def preset_noop(callback: CallbackQuery) -> None:
    """
    Заглушка для неактивных кнопок в списке шаблонов.

    Параметры:
        callback: inline-кнопка без действия
    """
    await callback.answer()


@router.callback_query(F.data == "preset:create")
async def create_preset_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Запрашивает название нового шаблона тренировки.

    Параметры:
        callback: inline-кнопка создания шаблона
        state: переводится в PresetCreateStates.waiting_for_name
    """
    await state.set_state(PresetCreateStates.waiting_for_name)
    await callback.message.edit_text(
        "Введите <b>название шаблона</b> (например, Руки/Плечи):"
    )
    await store_screen_message(state, callback.message)
    await callback.answer()


@router.message(PresetCreateStates.waiting_for_name)
async def create_preset_finish(message: Message, state: FSMContext) -> None:
    """
    Создаёт пустой шаблон и показывает его карточку.

    Параметры:
        message: текстовое сообщение с названием шаблона
        state: контекст FSM создания шаблона
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

    try:
        preset_id = await db.create_preset(user["id"], name)
    except Exception:
        logger.exception("Ошибка создания шаблона: telegram_id=%s", message.from_user.id)
        await message.answer("Не удалось создать шаблон. Попробуйте позже.")
        return

    await state.clear()
    await _render_preset_view(
        message,
        state,
        preset_id,
        user["id"],
        notice=f"✅ Шаблон <b>{name}</b> создан!",
    )


@router.callback_query(F.data.startswith("preset:view:"))
async def view_preset(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Открывает карточку выбранного шаблона с упражнениями.

    Параметры:
        callback: inline-кнопка preset:view:{preset_id}
        state: сбрасывает bulk_selected_ids
    """
    preset_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    await state.update_data(bulk_selected_ids=[])
    await _render_preset_view(callback, state, preset_id, user["id"])
    await callback.answer()


@router.callback_query(F.data.startswith("preset:delete:"))
async def delete_preset(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Удаляет шаблон и возвращает к списку программ.

    Параметры:
        callback: inline-кнопка preset:delete:{preset_id}
        state: контекст FSM, сбрасывается
    """
    preset_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    try:
        await db.delete_preset(preset_id, user["id"])
        presets = await db.get_presets_by_user_id(user["id"])
    except Exception:
        logger.exception(
            "Ошибка удаления пресета: telegram_id=%s id_preset=%s",
            callback.from_user.id,
            preset_id,
        )
        await callback.answer("Не удалось удалить программу", show_alert=True)
        return

    await state.clear()
    await show_screen_callback(
        callback,
        state,
        "✅ Готовая тренировка удалена.\n\n📋 <b>Мои готовые тренировки</b>",
        presets_list_keyboard(presets),
    )
    await callback.answer()


# --- Мульти-выбор упражнений (категории и шаблоны) ---


@router.callback_query(F.data.startswith("cat:bulk_add:"))
async def category_bulk_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Открывает массовый выбор несортированных упражнений для добавления в категорию.

    Параметры:
        callback: inline-кнопка cat:bulk_add:{category_id}
        state: устанавливает bulk_mode=cat_add
    """
    category_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    category = await db.get_category_by_id(category_id)
    if not category or category["id_user"] != user["id"]:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    exercises = await db.get_unsorted_exercises(user["id"])
    await state.update_data(bulk_mode="cat_add", bulk_context_id=category_id, bulk_selected_ids=[])
    await callback.message.edit_text(
        _bulk_title("cat_add", category["name"]),
        reply_markup=bulk_select_keyboard(exercises, [], "cat_add", category_id),
    )
    await store_screen_message(state, callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("cat:bulk_rm:"))
async def category_bulk_remove_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Открывает массовый выбор упражнений для удаления из категории.

    Параметры:
        callback: inline-кнопка cat:bulk_rm:{category_id}
        state: устанавливает bulk_mode=cat_rm
    """
    category_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    category = await db.get_category_by_id(category_id)
    if not category or category["id_user"] != user["id"]:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    exercises = await db.get_exercises_by_category(user["id"], category_id)
    await state.update_data(bulk_mode="cat_rm", bulk_context_id=category_id, bulk_selected_ids=[])
    await callback.message.edit_text(
        _bulk_title("cat_rm", category["name"]),
        reply_markup=bulk_select_keyboard(exercises, [], "cat_rm", category_id),
    )
    await store_screen_message(state, callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("preset:bulk_add:"))
async def preset_bulk_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Открывает массовый выбор упражнений для добавления в шаблон.

    Параметры:
        callback: inline-кнопка preset:bulk_add:{preset_id}
        state: устанавливает bulk_mode=preset_add
    """
    preset_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    preset = await db.get_preset_by_id(preset_id)
    if not preset or preset["id_user"] != user["id"]:
        await callback.answer("Программа не найдена", show_alert=True)
        return

    exercises = await db.get_global_exercises_by_user_id(user["id"])
    await state.update_data(bulk_mode="preset_add", bulk_context_id=preset_id, bulk_selected_ids=[])
    await callback.message.edit_text(
        _bulk_title("preset_add", preset["name"]),
        reply_markup=bulk_select_keyboard(exercises, [], "preset_add", preset_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("preset:bulk_rm:"))
async def preset_bulk_remove_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Открывает массовый выбор упражнений для удаления из шаблона.

    Параметры:
        callback: inline-кнопка preset:bulk_rm:{preset_id}
        state: устанавливает bulk_mode=preset_rm
    """
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
    await state.update_data(bulk_mode="preset_rm", bulk_context_id=preset_id, bulk_selected_ids=[])
    await callback.message.edit_text(
        _bulk_title("preset_rm", preset["name"]),
        reply_markup=bulk_select_keyboard(exercises, [], "preset_rm", preset_id),
    )
    await callback.answer()


@router.callback_query(F.data == "bulk:noop")
async def bulk_noop(callback: CallbackQuery) -> None:
    """
    Заглушка для неактивных кнопок в режиме массового выбора.

    Параметры:
        callback: inline-кнопка без действия
    """
    await callback.answer()


@router.callback_query(F.data.regexp(r"^bulk:toggle:[a-z_]+:\d+:\d+$"))
async def bulk_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Переключает отметку упражнения в списке массового выбора.

    Параметры:
        callback: inline-кнопка bulk:toggle:{mode}:{context_id}:{exercise_id}
        state: обновляет bulk_selected_ids
    """
    _, _, mode, context_id_str, ex_id_str = callback.data.split(":", maxsplit=4)
    context_id = int(context_id_str)
    ex_id = int(ex_id_str)

    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    data = await state.get_data()
    selected = list(data.get("bulk_selected_ids", []))
    if ex_id in selected:
        selected.remove(ex_id)
    else:
        selected.append(ex_id)

    await state.update_data(
        bulk_mode=mode,
        bulk_context_id=context_id,
        bulk_selected_ids=selected,
    )

    exercises = await _load_bulk_exercises(mode, context_id, user["id"])
    context_name = ""
    if mode.startswith("cat"):
        category = await db.get_category_by_id(context_id)
        context_name = category["name"] if category else ""
    else:
        preset = await db.get_preset_by_id(context_id)
        context_name = preset["name"] if preset else ""

    await callback.message.edit_reply_markup(
        reply_markup=bulk_select_keyboard(exercises, selected, mode, context_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^bulk:confirm:[a-z_]+:\d+$"))
async def bulk_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Применяет массовую операцию с выбранными упражнениями.

    Параметры:
        callback: inline-кнопка bulk:confirm:{mode}:{context_id}
        state: контекст FSM с bulk_selected_ids
    """
    _, _, mode, context_id_str = callback.data.split(":", maxsplit=3)
    context_id = int(context_id_str)

    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    data = await state.get_data()
    selected: list[int] = list(data.get("bulk_selected_ids", []))
    if not selected:
        await callback.answer("Выберите хотя бы одно упражнение", show_alert=True)
        return

    try:
        if mode == "cat_add":
            owned_ids = await _filter_owned_exercise_ids(selected, user["id"])
            if not owned_ids:
                await callback.answer(
                    "Можно добавлять в категорию только свои упражнения",
                    show_alert=True,
                )
                return
            count = await db.bulk_assign_exercises_to_category(
                owned_ids, context_id, user["id"]
            )
            await _render_category_view(
                callback,
                state,
                context_id,
                user["id"],
                notice=f"✅ Добавлено упражнений: {count}",
            )
        elif mode == "cat_rm":
            count = await db.bulk_unassign_exercises_from_category(
                selected, context_id, user["id"]
            )
            await _render_category_view(
                callback,
                state,
                context_id,
                user["id"],
                notice=f"✅ Убрано из категории: {count}",
            )
        elif mode == "preset_add":
            queue = await _build_preset_add_queue(selected, user["id"])
            if not queue:
                await callback.answer(
                    "Нет упражнений для добавления",
                    show_alert=True,
                )
                return
            await state.update_data(
                preset_add_preset_id=context_id,
                preset_add_queue=queue,
                preset_add_index=0,
                bulk_selected_ids=[],
            )
            await state.set_state(PresetBulkAddStates.waiting_for_sets_count)
            await _prompt_preset_add_sets_count(
                callback, state, queue[0], 0, len(queue)
            )
            await callback.answer()
            return
        elif mode == "preset_rm":
            count = await db.bulk_delete_preset_exercises(
                selected, context_id, user["id"]
            )
            await _render_preset_view(
                callback,
                state,
                context_id,
                user["id"],
                notice=f"✅ Удалено из шаблона: {count}",
            )
        else:
            await callback.answer("Неизвестный режим выбора", show_alert=True)
            return
    except Exception:
        logger.exception(
            "Ошибка массовой операции: mode=%s context_id=%s",
            mode,
            context_id,
        )
        await callback.answer("Не удалось сохранить изменения", show_alert=True)
        return

    await state.update_data(bulk_selected_ids=[])
    await callback.answer()


@router.callback_query(F.data.regexp(r"^bulk:cancel:[a-z_]+:\d+$"))
async def bulk_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Отменяет массовый выбор и возвращает к категории или шаблону.

    Параметры:
        callback: inline-кнопка bulk:cancel:{mode}:{context_id}
        state: сбрасывает bulk_selected_ids
    """
    _, _, mode, context_id_str = callback.data.split(":", maxsplit=3)
    context_id = int(context_id_str)

    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    await state.update_data(bulk_selected_ids=[])

    if mode.startswith("cat"):
        await _render_category_view(callback, state, context_id, user["id"])
    else:
        await _render_preset_view(callback, state, context_id, user["id"])

    await callback.answer("Отменено")


@router.message(PresetBulkAddStates.waiting_for_sets_count)
async def preset_bulk_add_sets_count(message: Message, state: FSMContext) -> None:
    """
    Принимает число подходов при пошаговом добавлении упражнений в шаблон.

    Параметры:
        message: текстовое сообщение с количеством подходов
        state: контекст FSM с preset_add_queue и preset_add_index
    """
    sets_count = parse_sets_count_input(message.text)
    if sets_count is None:
        await message.answer(
            "Введите целое число от 0 и выше (0 - не указывать количество подходов):"
        )
        return

    data = await state.get_data()
    preset_id = data.get("preset_add_preset_id")
    queue: list[dict] = list(data.get("preset_add_queue", []))
    index = int(data.get("preset_add_index", 0))
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user or not preset_id or index >= len(queue):
        await state.clear()
        await message.answer("Данные шаблона потеряны. Начните заново.")
        return

    exercise = queue[index]
    try:
        sequence = await db.get_max_preset_sequence_number(preset_id) + 1
        await db.add_preset_exercise(
            preset_id=preset_id,
            exercise_name=exercise["name"],
            exercise_type=exercise["exercise_type"],
            sequence_number=sequence,
            sets_count=sets_count,
        )
    except Exception:
        logger.exception(
            "Ошибка добавления упражнения в шаблон: preset_id=%s",
            preset_id,
        )
        await message.answer("Не удалось сохранить упражнение. Попробуйте позже.")
        return

    index += 1
    if index < len(queue):
        await state.update_data(preset_add_index=index)
        await _prompt_preset_add_sets_count(
            message, state, queue[index], index, len(queue)
        )
        return

    await state.clear()
    await _render_preset_view(
        message,
        state,
        preset_id,
        user["id"],
        notice=f"✅ Добавлено в шаблон: {len(queue)}",
    )


@router.callback_query(
    TemplateEditStates.waiting_for_exercise_selection,
    F.data.regexp(r"^preset:edit_sets:pick:\d+:\d+$"),
)
async def preset_edit_sets_pick(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Выбор упражнения по inline-кнопке для редактирования числа подходов.

    Параметры:
        callback: inline-кнопка preset:edit_sets:pick:{preset_id}:{index}
        state: контекст FSM редактирования шаблона
    """
    logger.info(
        "Inline-кнопка: user_id=%s callback_data=%s",
        callback.from_user.id,
        callback.data,
    )
    parts = callback.data.split(":")
    preset_id = int(parts[3])
    index = int(parts[4])

    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    preset = await db.get_preset_by_id(preset_id)
    if not preset or preset["id_user"] != user["id"]:
        await callback.answer("Программа не найдена", show_alert=True)
        return

    data = await state.get_data()
    exercises: list[dict] = list(data.get("template_edit_exercises", []))
    if not exercises or data.get("template_edit_preset_id") != preset_id:
        exercises = await db.get_preset_exercises(preset_id)

    await _begin_template_edit_sets_count(
        callback, state, preset_id, exercises, index
    )


@router.callback_query(
    TemplateEditStates.waiting_for_exercise_selection,
    F.data.regexp(r"^preset:edit_sets:done:\d+$"),
)
async def preset_edit_sets_done(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Завершает редактирование подходов и возвращает к карточке шаблона.

    Параметры:
        callback: inline-кнопка preset:edit_sets:done:{preset_id}
        state: контекст FSM, сбрасывается
    """
    logger.info(
        "Inline-кнопка: user_id=%s callback_data=%s",
        callback.from_user.id,
        callback.data,
    )
    preset_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    preset = await db.get_preset_by_id(preset_id)
    if not preset or preset["id_user"] != user["id"]:
        await callback.answer("Программа не найдена", show_alert=True)
        return

    await state.clear()
    await _render_preset_view(callback, state, preset_id, user["id"])
    await callback.answer()


@router.callback_query(F.data.regexp(r"^preset:edit_sets:\d+$"))
async def preset_edit_sets_start(callback: CallbackQuery, state: FSMContext) -> None:
    """
    Начинает редактирование числа подходов упражнений шаблона.

    Параметры:
        callback: inline-кнопка preset:edit_sets:{preset_id}
        state: переводится в TemplateEditStates.waiting_for_exercise_selection
    """
    logger.info(
        "Inline-кнопка: user_id=%s callback_data=%s",
        callback.from_user.id,
        callback.data,
    )
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
        await callback.answer("В шаблоне нет упражнений", show_alert=True)
        return

    await _show_template_edit_selection(callback, state, preset_id, exercises)
    await callback.answer()


@router.message(TemplateEditStates.waiting_for_exercise_selection)
async def preset_edit_sets_select_by_number(
    message: Message,
    state: FSMContext,
) -> None:
    """
    Выбор упражнения по номеру из списка для редактирования подходов.

    Параметры:
        message: текстовое сообщение с номером упражнения
        state: контекст FSM редактирования шаблона
    """
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(
            "Введите номер упражнения из списка или используйте кнопки ниже."
        )
        return

    data = await state.get_data()
    preset_id = data.get("template_edit_preset_id")
    exercises: list[dict] = list(data.get("template_edit_exercises", []))
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user or not preset_id or not exercises:
        await state.clear()
        await message.answer("Данные шаблона потеряны. Начните заново.")
        return

    await _begin_template_edit_sets_count(
        message,
        state,
        preset_id,
        exercises,
        int(text) - 1,
    )


@router.message(TemplateEditStates.waiting_for_sets_count)
async def preset_edit_sets_apply(message: Message, state: FSMContext) -> None:
    """
    Сохраняет новое число подходов и возвращает к списку упражнений шаблона.

    Параметры:
        message: текстовое сообщение с количеством подходов
        state: контекст FSM с template_edit_exercise_id
    """
    sets_count = parse_sets_count_input(message.text)
    if sets_count is None:
        await message.answer(
            "Введите целое число от 0 и выше (0 - не указывать количество подходов):"
        )
        return

    data = await state.get_data()
    preset_id = data.get("template_edit_preset_id")
    exercise_id = data.get("template_edit_exercise_id")
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user or not preset_id or not exercise_id:
        await state.clear()
        await message.answer("Данные шаблона потеряны. Начните заново.")
        return

    try:
        await db.update_preset_exercise_sets_count(
            int(exercise_id),
            preset_id,
            sets_count,
        )
    except Exception:
        logger.exception(
            "Ошибка обновления подходов шаблона: preset_id=%s exercise_id=%s",
            preset_id,
            exercise_id,
        )
        await message.answer("Не удалось сохранить. Попробуйте ещё раз.")
        return

    exercises = await db.get_preset_exercises(preset_id)
    await _show_template_edit_selection(
        message,
        state,
        preset_id,
        exercises,
        notice="✅ Количество подходов обновлено",
    )
