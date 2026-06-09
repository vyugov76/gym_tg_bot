"""Настройки: категории, готовые тренировки, профиль."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database.requests as db
from keyboards.bulk_select import bulk_select_keyboard
from keyboards.menu import (
    categories_list_keyboard,
    category_detail_keyboard,
    exercise_manage_keyboard,
    my_exercises_keyboard,
    preset_detail_keyboard,
    presets_list_keyboard,
    profile_keyboard,
    settings_menu_keyboard,
)
from states.workout_states import CategoryStates, PresetCreateStates, ProfileEditStates
from utils.exercise_types import EXERCISE_TYPE_LABELS, normalize_exercise_type

router = Router(name="settings")
logger = logging.getLogger(__name__)


def _type_label(exercise: dict) -> str:
    exercise_type = normalize_exercise_type(
        exercise.get("exercise_type", exercise.get("is_bodyweight"))
    )
    return EXERCISE_TYPE_LABELS.get(exercise_type, "неизвестно")


def _format_preset_exercises(exercises: list[dict]) -> str:
    if not exercises:
        return "В программе пока нет упражнений."
    lines = []
    for idx, ex in enumerate(exercises, start=1):
        lines.append(f"{idx}) {ex['name']} — {_type_label(ex)}")
    return "\n".join(lines)


async def _render_category_view(
    callback: CallbackQuery,
    state: FSMContext,
    category_id: int,
    id_user: int,
    *,
    notice: str | None = None,
) -> None:
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

    text = f"📂 <b>{category['name']}</b>\n\nУпражнения в категории ({len(exercises)}):"
    if notice:
        text = f"{notice}\n\n{text}"

    await callback.message.edit_text(
        text,
        reply_markup=my_exercises_keyboard(exercises),
    )
    await callback.message.answer(
        "Действия с категорией:",
        reply_markup=category_detail_keyboard(category_id),
    )


async def _render_preset_view(
    target: CallbackQuery | Message,
    preset_id: int,
    id_user: int,
    *,
    notice: str | None = None,
) -> None:
    preset = await db.get_preset_by_id(preset_id)
    if not preset or preset["id_user"] != id_user:
        if isinstance(target, CallbackQuery):
            await target.answer("Программа не найдена", show_alert=True)
        return

    exercises = await db.get_preset_exercises(preset_id)
    text = f"📋 <b>{preset['name']}</b>\n\n{_format_preset_exercises(exercises)}"
    if notice:
        text = f"{notice}\n\n{text}"

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(
            text,
            reply_markup=preset_detail_keyboard(preset_id),
        )
    else:
        await target.answer(
            text,
            reply_markup=preset_detail_keyboard(preset_id),
        )


async def _load_bulk_exercises(
    mode: str,
    context_id: int,
    id_user: int,
) -> list[dict]:
    if mode == "cat_add":
        return await db.get_unsorted_exercises(id_user)
    if mode == "cat_rm":
        return await db.get_exercises_by_category(id_user, context_id)
    if mode == "preset_add":
        return await db.get_global_exercises_by_user_id(id_user)
    if mode == "preset_rm":
        return await db.get_preset_exercises(context_id)
    return []


def _bulk_title(mode: str, context_name: str) -> str:
    titles = {
        "cat_add": f"➕ Добавление в «{context_name}»\n\nОтметьте несортированные упражнения:",
        "cat_rm": f"➖ Удаление из «{context_name}»\n\nОтметьте упражнения для переноса в «Несортированные»:",
        "preset_add": f"➕ Добавление в «{context_name}»\n\nОтметьте упражнения для шаблона:",
        "preset_rm": f"➖ Удаление из «{context_name}»\n\nОтметьте упражнения для удаления из шаблона:",
    }
    return titles.get(mode, "Выберите упражнения:")


@router.message(F.text == "⚙️ Настройки")
async def show_settings(message: Message, state: FSMContext) -> None:
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
    await state.clear()
    await callback.message.edit_text(
        "Настройки аккаунта и конструктора:",
        reply_markup=settings_menu_keyboard(),
    )
    await callback.answer()


# --- Профиль ---


@router.callback_query(F.data == "settings:profile")
async def show_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    await callback.message.edit_text(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"Рост: {user['height']} см\n"
        f"Вес: {user['weight']} кг\n"
        f"Дата регистрации: {user['created_at'].strftime('%d.%m.%Y')}",
        reply_markup=profile_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "profile:edit_height")
async def edit_height_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileEditStates.waiting_for_height)
    await callback.message.edit_text(
        "Введите новый <b>рост в см</b> (от 100 до 250):"
    )
    await callback.answer()


@router.callback_query(F.data == "profile:edit_weight")
async def edit_weight_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProfileEditStates.waiting_for_weight)
    await callback.message.edit_text(
        "Введите новый <b>вес в кг</b> (от 30 до 300):"
    )
    await callback.answer()


@router.message(ProfileEditStates.waiting_for_height)
async def edit_height_finish(message: Message, state: FSMContext) -> None:
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
    await message.answer(
        f"✅ Рост обновлён: <b>{height} см</b>",
        reply_markup=profile_keyboard(),
    )


@router.message(ProfileEditStates.waiting_for_weight)
async def edit_weight_finish(message: Message, state: FSMContext) -> None:
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
    await message.answer(
        f"✅ Вес обновлён: <b>{weight} кг</b>",
        reply_markup=profile_keyboard(),
    )


# --- Категории ---


@router.callback_query(F.data == "settings:categories")
async def show_categories(callback: CallbackQuery, state: FSMContext) -> None:
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
    await callback.message.edit_text(
        text,
        reply_markup=categories_list_keyboard(categories),
    )
    await callback.answer()


@router.callback_query(F.data == "cat:create")
async def create_category_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CategoryStates.waiting_for_name)
    await callback.message.edit_text(
        "Введите <b>название категории</b> (например, Грудь):"
    )
    await callback.answer()


@router.message(CategoryStates.waiting_for_name)
async def create_category_finish(message: Message, state: FSMContext) -> None:
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
    await message.answer(
        f"✅ Категория <b>{name}</b> создана!\n\n"
        f"📂 <b>Категории упражнений</b>",
        reply_markup=categories_list_keyboard(categories),
    )


@router.callback_query(F.data == "cat:unsorted")
async def view_unsorted_exercises(callback: CallbackQuery, state: FSMContext) -> None:
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    exercises = await db.get_unsorted_exercises(user["id"])
    await state.update_data(settings_category_id=None, settings_category_name=None)

    await callback.message.edit_text(
        f"📁 <b>Несортированные</b>\n\nУпражнения ({len(exercises)}):",
        reply_markup=my_exercises_keyboard(exercises),
    )
    await callback.message.answer(
        "◀️ Вернуться к категориям:",
        reply_markup=categories_list_keyboard(
            await db.get_categories_by_user_id(user["id"])
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat:view:"))
async def view_category(callback: CallbackQuery, state: FSMContext) -> None:
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

    text = (
        f"📂 <b>{category['name']}</b>\n\n"
        f"Упражнения в категории ({len(exercises)}):"
    )
    await callback.message.edit_text(
        text,
        reply_markup=my_exercises_keyboard(exercises),
    )
    await callback.message.answer(
        "Действия с категорией:",
        reply_markup=category_detail_keyboard(category_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cat:delete:"))
async def delete_category(callback: CallbackQuery, state: FSMContext) -> None:
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
    await callback.message.edit_text(
        "✅ Категория удалена. Упражнения перенесены в «Несортированные».\n\n"
        "📂 <b>Категории упражнений</b>",
        reply_markup=categories_list_keyboard(categories),
    )
    await callback.answer()


# --- Готовые тренировки ---


@router.callback_query(F.data == "settings:presets")
async def show_presets(callback: CallbackQuery, state: FSMContext) -> None:
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
    await callback.message.edit_text(text, reply_markup=presets_list_keyboard(presets))
    await callback.answer()


@router.callback_query(F.data == "preset:noop")
async def preset_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "preset:create")
async def create_preset_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PresetCreateStates.waiting_for_name)
    await callback.message.edit_text(
        "Введите <b>название шаблона</b> (например, Руки/Плечи):"
    )
    await callback.answer()


@router.message(PresetCreateStates.waiting_for_name)
async def create_preset_finish(message: Message, state: FSMContext) -> None:
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
        preset_id,
        user["id"],
        notice=f"✅ Шаблон <b>{name}</b> создан!",
    )


@router.callback_query(F.data.startswith("preset:view:"))
async def view_preset(callback: CallbackQuery, state: FSMContext) -> None:
    preset_id = int(callback.data.split(":")[-1])
    user = await db.get_user_by_telegram_id(callback.from_user.id)
    if not user:
        await callback.answer("Сначала нажмите /start", show_alert=True)
        return

    await state.update_data(bulk_selected_ids=[])
    await _render_preset_view(callback, preset_id, user["id"])
    await callback.answer()


@router.callback_query(F.data.startswith("preset:delete:"))
async def delete_preset(callback: CallbackQuery, state: FSMContext) -> None:
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
    await callback.message.edit_text(
        "✅ Готовая тренировка удалена.\n\n📋 <b>Мои готовые тренировки</b>",
        reply_markup=presets_list_keyboard(presets),
    )
    await callback.answer()


# --- Мульти-выбор упражнений (категории и шаблоны) ---


@router.callback_query(F.data.startswith("cat:bulk_add:"))
async def category_bulk_add_start(callback: CallbackQuery, state: FSMContext) -> None:
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
    await callback.answer()


@router.callback_query(F.data.startswith("cat:bulk_rm:"))
async def category_bulk_remove_start(callback: CallbackQuery, state: FSMContext) -> None:
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
    await callback.answer()


@router.callback_query(F.data.startswith("preset:bulk_add:"))
async def preset_bulk_add_start(callback: CallbackQuery, state: FSMContext) -> None:
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
    await callback.answer()


@router.callback_query(F.data.regexp(r"^bulk:toggle:[a-z_]+:\d+:\d+$"))
async def bulk_toggle(callback: CallbackQuery, state: FSMContext) -> None:
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
            count = await db.bulk_assign_exercises_to_category(
                selected, context_id, user["id"]
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
            count = await db.bulk_add_global_exercises_to_preset(
                context_id, selected, user["id"]
            )
            await _render_preset_view(
                callback,
                context_id,
                user["id"],
                notice=f"✅ Добавлено в шаблон: {count}",
            )
        elif mode == "preset_rm":
            count = await db.bulk_delete_preset_exercises(
                selected, context_id, user["id"]
            )
            await _render_preset_view(
                callback,
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
        await _render_preset_view(callback, context_id, user["id"])

    await callback.answer("Отменено")
