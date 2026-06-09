"""Асинхронное подключение к MS SQL Server через ODBC (aioodbc)."""

from __future__ import annotations

import asyncio
import logging
import os

import aioodbc
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Находим путь к текущему файлу (connection.py)
current_path = os.path.abspath(__file__)

# Отсекаем всё, что идет после названия корневой папки проекта
root_dir = current_path.split("gym_tg_bot")[0] + "gym_tg_bot"

# Собираем идеальный абсолютный путь к .env
env_path = os.path.join(root_dir, ".env")

# Загружаем переменные окружения
load_dotenv(dotenv_path=env_path)

DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
DB_SERVER = os.getenv("DB_SERVER", "localhost")
DB_DATABASE = os.getenv("DB_DATABASE", "")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# Глобальный пул соединений (создаётся при старте бота)
_pool: aioodbc.Pool | None = None

POOL_MINSIZE = 1
POOL_MAXSIZE = 10

# ... дальше твои функции build_dsn(), init_db() и остальные идут без изменений ...


def build_dsn() -> str:
    """Формирует строку подключения ODBC с авторизацией по логину и паролю."""
    return (
        f"DRIVER={{{DB_DRIVER}}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_DATABASE};"
        f"UID={DB_USER};"
        f"PWD={DB_PASSWORD};"
        "TrustServerCertificate=yes;"
    )


async def _create_pool() -> aioodbc.Pool:
    """Создаёт новый пул соединений."""
    return await aioodbc.create_pool(
        dsn=build_dsn(),
        minsize=POOL_MINSIZE,
        maxsize=POOL_MAXSIZE,
        autocommit=True,
    )


async def _close_pool(pool: aioodbc.Pool | None) -> None:
    """Безопасно закрывает пул."""
    if pool is None:
        return
    try:
        pool.close()
        await pool.wait_closed()
    except Exception:
        logger.warning("Ошибка при закрытии пула соединений", exc_info=True)


async def init_db() -> None:
    """Создаёт пул соединений с базой данных (с повторными попытками)."""
    global _pool
    retries = 5
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        logger.info("Попытка подключения к БД %s/%s...", attempt, retries)
        try:
            _pool = await _create_pool()
            logger.info("Пул соединений с БД успешно создан!")
            logger.info(
                "Параметры пула: driver=%s server=%s database=%s user=%s "
                "minsize=%s maxsize=%s autocommit=True",
                DB_DRIVER,
                DB_SERVER,
                DB_DATABASE,
                DB_USER,
                POOL_MINSIZE,
                POOL_MAXSIZE,
            )
            return
        except Exception as e:
            last_error = e
            logger.warning(
                "Попытка %s завершилась ошибкой: %s. Повтор через 3 сек...",
                attempt,
                e,
            )
            if attempt < retries:
                await asyncio.sleep(3)

    logger.critical("Все попытки подключения к базе данных исчерпаны.")
    raise last_error


async def refresh_db_pool() -> None:
    """Пересоздаёт пул после потери соединения (таймаут простоя и т.п.)."""
    global _pool
    logger.warning("Пересоздание пула соединений с БД...")
    old_pool = _pool
    _pool = None
    await _close_pool(old_pool)
    _pool = await _create_pool()
    logger.info("Пул соединений с БД успешно пересоздан")


async def close_db() -> None:
    """Закрывает пул соединений при остановке бота."""
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        logger.info("Пул соединений с БД закрыт")


def get_pool() -> aioodbc.Pool:
    """Возвращает активный пул. Вызывать только после init_db()."""
    if _pool is None:
        raise RuntimeError("Пул БД не инициализирован. Вызовите init_db() перед работой.")
    return _pool
