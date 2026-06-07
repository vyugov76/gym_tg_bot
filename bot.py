"""Точка входа: инициализация бота, БД и запуск polling."""

import os
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Явно вычисляем путь к .env относительно этого файла bot.py
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)
print(f"Ищем файл .env по пути: {env_path}")
print(f"Файл .env реально существует? -> {env_path.exists()}")
print(f"Считанный токен: {os.getenv('BOT_TOKEN')}")

# Только ПОСЛЕ этого считываем токен
BOT_TOKEN = os.getenv("BOT_TOKEN")

import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from database.connection import close_db, init_db
from handlers.exercises import router as exercises_router
from handlers.start import router as start_router
from handlers.workout import router as workout_router

PROJECT_ROOT = Path(__file__).resolve().parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging() -> logging.Logger:
    """Настраивает логирование в уникальный файл logs/ и в консоль."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"bot_{timestamp}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    app_logger = logging.getLogger(__name__)
    app_logger.info("Логирование в файл: %s", log_file)
    return app_logger


logger = setup_logging()


async def main() -> None:
    """Запуск бота: подключение к БД, регистрация роутеров, polling."""
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN не задан. Укажите его в файле .env")
        raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start_router)
    dp.include_router(exercises_router)
    dp.include_router(workout_router)

    try:
        await init_db()
        logger.info("Подключение к БД установлено")
        logger.info("Бот запущен")
        await dp.start_polling(bot)
    except Exception:
        logger.critical("Критическая ошибка при работе бота", exc_info=True)
        raise
    finally:
        await close_db()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки (Ctrl+C)")
    except Exception:
        logger.critical("Экстренное завершение работы бота", exc_info=True)
        raise
