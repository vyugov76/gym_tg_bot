"""
start - обработчик команды /start

Приветствие зарегистрированных пользователей и регистрация новых:
пошаговый ввод роста и веса.

Ключевые обработчики:
- cmd_start - команда /start
- process_height - приём роста при регистрации
- process_weight - приём веса и завершение регистрации
"""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import database.requests as db
from keyboards.menu import main_menu_keyboard
from states.workout_states import RegistrationStates

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """
    Обрабатывает команду /start.

    Сбрасывает FSM, приветствует существующего пользователя с данными профиля
    или запускает пошаговую регистрацию для нового.

    Параметры:
        message: входящее сообщение с командой /start
        state: контекст FSM для сценария регистрации
    """
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
    """
    Принимает рост пользователя на этапе регистрации.

    Проверяет диапазон 100-250 см, сохраняет значение в FSM
    и переводит к вводу веса.

    Параметры:
        message: текстовое сообщение с ростом
        state: контекст FSM с данными регистрации
    """
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
    """
    Принимает вес, завершает регистрацию и показывает главное меню.

    Проверяет диапазон 30-300 кг, создаёт запись пользователя в БД
    и сбрасывает FSM.

    Параметры:
        message: текстовое сообщение с весом
        state: контекст FSM с сохранённым ростом
    """
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
