"""
bot - точка входа Telegram-бота для учёта тренировок

Инициализирует логирование, загружает переменные из .env в корне проекта,
создаёт экземпляр Bot (с опциональным SOCKS5-прокси), подключается к БД
и запускает long polling через aiogram Dispatcher.

Ключевые функции:
- setup_logging - настройка файлового и консольного логирования
- create_bot - создание Bot с прокси или прямым подключением
- main - регистрация роутеров, init_db и start_polling

Переменные окружения (.env):
- BOT_TOKEN - токен Telegram-бота (обязательно)
- PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS - опциональный SOCKS5
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp_socks import ProxyConnector
from dotenv import load_dotenv

from database.connection import close_db, init_db
from handlers.exercises import router as exercises_router
from handlers.settings import router as settings_router
from handlers.start import router as start_router
from handlers.statistics import router as statistics_router
from handlers.workout import router as workout_router

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN")

LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging() -> logging.Logger:
    """
    Настраивает логирование приложения.

    Создаёт каталог logs/, пишет в файл bot_YYYYMMDD_HHMMSS.log и в stdout.
    Возвращает логгер модуля bot.
    """
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


def _build_socks5_proxy_url() -> str | None:
    """
    Собирает URL SOCKS5-прокси из переменных окружения.

    Читает PROXY_HOST, PROXY_PORT, PROXY_USER и PROXY_PASS.
    Если host или port не заданы - возвращает None (прямое подключение).
    """
    host = (os.getenv("PROXY_HOST") or "").strip()
    port = (os.getenv("PROXY_PORT") or "").strip()
    if not host or not port:
        return None

    user = (os.getenv("PROXY_USER") or "").strip()
    password = (os.getenv("PROXY_PASS") or "").strip()
    if user and password:
        return (
            f"socks5://{quote(user, safe='')}:{quote(password, safe='')}"
            f"@{host}:{port}"
        )
    return f"socks5://{host}:{port}"


def create_bot() -> Bot:
    """
    Создаёт экземпляр aiogram Bot.

    При наличии настроек прокси подключает AiohttpSession с SOCKS5.
    Иначе использует стандартную сессию для локальной разработки.
    """
    bot_kwargs = {
        "token": BOT_TOKEN,
        "default": DefaultBotProperties(parse_mode=ParseMode.HTML),
    }
    proxy_url = _build_socks5_proxy_url()
    if proxy_url:
        session = AiohttpSession(proxy=ProxyConnector.from_url(proxy_url))
        bot_kwargs["session"] = session
        host = (os.getenv("PROXY_HOST") or "").strip()
        port = (os.getenv("PROXY_PORT") or "").strip()
        logger.info("Telegram API через SOCKS5-прокси %s:%s", host, port)
    else:
        logger.info("Telegram API: прямое подключение (прокси не задан)")
    return Bot(**bot_kwargs)


async def main() -> None:
    """
    Основной цикл работы бота.

    Проверяет BOT_TOKEN, инициализирует Bot и Dispatcher, регистрирует
    роутеры, подключается к БД и запускает long polling.
    При завершении закрывает соединение с БД и сессию бота.
    """
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN не задан. Укажите его в файле .env")
        raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

    bot = create_bot()
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start_router)
    dp.include_router(settings_router)
    dp.include_router(exercises_router)
    dp.include_router(statistics_router)
    dp.include_router(workout_router)

    try:
        await init_db()
        logger.info("Подключение к БД установлено")
        logger.info("Бот запущен")
        await dp.start_polling(bot, drop_pending_updates=True)
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
