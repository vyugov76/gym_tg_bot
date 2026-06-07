"""Обработчик /start, регистрация пользователя, профиль и статистика."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import database.requests as db
from keyboards.menu import main_menu_keyboard
from states.workout_states import RegistrationStates

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Приветствие: проверяет пользователя в БД или запускает регистрацию."""
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
    """Принимает рост и запрашивает вес."""
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
    """Принимает вес, сохраняет пользователя в БД."""
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
async def show_profile(message: Message) -> None:
    """Показывает данные профиля пользователя."""
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start для регистрации.")
        return

    await message.answer(
        f"👤 <b>Ваш профиль</b>\n\n"
        f"Рост: {user['height']} см\n"
        f"Вес: {user['weight']} кг\n"
        f"Дата регистрации: {user['created_at'].strftime('%d.%m.%Y')}",
    )


@router.message(F.text == "Моя статистика")
async def show_stats(message: Message) -> None:
    """Показывает сводную статистику тренировок."""
    user = await db.get_user_by_telegram_id(message.from_user.id)
    if not user:
        await message.answer("Сначала нажмите /start для регистрации.")
        return

    stats = await db.get_user_workout_stats(user["id"])
    workouts = await db.get_last_workouts(user["id"])

    lines = [
        "📊 <b>Моя статистика</b>\n",
        f"Завершённых тренировок: {stats['workout_count']}",
        f"Суммарный тоннаж: {stats['total_tonnage']:.0f} кг",
    ]

    if workouts:
        lines.append("\n<b>Последние тренировки:</b>")
        for w in workouts:
            date = w["finished_at"].strftime("%d.%m.%Y")
            lines.append(f"• {date} — {w['total_tonnage']:.0f} кг")

    await message.answer("\n".join(lines))
