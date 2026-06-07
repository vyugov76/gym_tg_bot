"""Точка входа: инициализация бота, БД и запуск polling."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from database.connection import close_db, init_db
from handlers.start import router as start_router
from handlers.workout import router as workout_router

# Замените на токен от @BotFather
BOT_TOKEN = "8177271374:AAHLMZiABq4TuryEt8hInuHV7mbVr1YAowQ"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Запуск бота: подключение к БД, регистрация роутеров, polling."""
    # Для тестирования через локальный Happ / SmartProxy / ByeDPI
    bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Подключаем обработчики
    dp.include_router(start_router)
    dp.include_router(workout_router)

    # Инициализируем пул соединений с БД
    await init_db()
    logger.info("Подключение к БД установлено")

    try:
        logger.info("Бот запущен")
        await dp.start_polling(bot)
    finally:
        await close_db()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
