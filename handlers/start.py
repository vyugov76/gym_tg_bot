"""Обработчик /start, регистрация пользователя и профиль."""

import logging

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import database.requests as db
from keyboards.menu import main_menu_keyboard, profile_keyboard
from states.workout_states import ProfileEditStates, RegistrationStates

router = Router(name="start")
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user_by_telegram_id(message.from_user.id)

    if user:
        await message.answer(
            f"С возвращением! 💪\n\n"
            f"Рост: {user['height']} см | Вес: {user['weight']} кг\n"
            f"Выберите действие в меню:",
            reply_markup=main_menu_keyboard(),
        )
        return

    await message.answer(
        "Привет! Я бот для учёта тренировок в зале.\n\n"
        "Для начала нужно зарегистрироваться.\n"
        "Введите ваш <b>рост в см</b> (например, 175):",
    )
    await state.set_state(RegistrationStates.height)


@router.message(RegistrationStates.height)
async def process_height(message: Message, state: FSMContext) -> None:
    try:
        height = float(message.text.replace(",", "."))
        if not (100 <= height <= 250):
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Введите корректный рост числом от 100 до 250 см:")
        return

    await state.update_data(height=height)
    await message.answer("Отлично! Теперь введите ваш <b>вес в кг</b> (например, 75):")
    await state.set_state(RegistrationStates.weight)


@router.message(RegistrationStates.weight)
async def process_weight(message: Message, state: FSMContext) -> None:
    try:
        weight = float(message.text.replace(",", "."))
        if not (30 <= weight <= 300):
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Введите корректный вес числом от 30 до 300 кг:")
        return

    data = await state.get_data()
    await db.add_user(
        telegram_id=message.from_user.id,
        height=data["height"],
        weight=weight,
    )
    await state.clear()

    await message.answer(
        f"Регистрация завершена! ✅\n"
        f"Рост: {data['height']} см | Вес: {weight} кг\n\n"
        f"Теперь можете начать первую тренировку:",
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == "Профиль")
async def show_profile(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start для регистрации.")
        return

    await message.answer(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"Рост: {user['height']} см\n"
        f"Вес: {user['weight']} кг\n"
        f"Дата регистрации: {user['created_at'].strftime('%d.%m.%Y')}",
        reply_markup=profile_keyboard(),
    )


@router.callback_query(F.data == "profile:edit_height")
async def edit_height_start(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("Редактирование роста: user_id=%s", callback.from_user.id)
    await state.set_state(ProfileEditStates.waiting_for_height)
    await callback.message.edit_text(
        "Введите новый <b>рост в см</b> (от 100 до 250):"
    )
    await callback.answer()


@router.callback_query(F.data == "profile:edit_weight")
async def edit_weight_start(callback: CallbackQuery, state: FSMContext) -> None:
    logger.info("Редактирование веса: user_id=%s", callback.from_user.id)
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
        logger.exception(
            "Ошибка обновления роста: user_id=%s",
            message.from_user.id,
        )
        await message.answer("Не удалось обновить рост. Попробуйте позже.")
        return

    await state.clear()
    logger.info(
        "Рост обновлён: telegram_id=%s db_user_id=%s height=%s",
        message.from_user.id,
        user["id"],
        height,
    )
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
        logger.exception(
            "Ошибка обновления веса: user_id=%s",
            message.from_user.id,
        )
        await message.answer("Не удалось обновить вес. Попробуйте позже.")
        return

    await state.clear()
    logger.info(
        "Вес обновлён: telegram_id=%s db_user_id=%s weight=%s",
        message.from_user.id,
        user["id"],
        weight,
    )
    await message.answer(
        f"✅ Вес обновлён: <b>{weight} кг</b>",
        reply_markup=profile_keyboard(),
    )
