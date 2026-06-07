"""Асинхронное подключение к MS SQL Server через ODBC (aioodbc)."""

from __future__ import annotations

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


async def init_db() -> None:
    """Создаёт пул соединений с базой данных."""
    global _pool
    pool_minsize = 1
    pool_maxsize = 10

    try:
        _pool = await aioodbc.create_pool(
            dsn=build_dsn(),
            minsize=pool_minsize,
            maxsize=pool_maxsize,
            autocommit=True,
        )
        logger.info(
            "Пул БД создан: driver=%s server=%s database=%s user=%s "
            "minsize=%s maxsize=%s autocommit=True",
            DB_DRIVER,
            DB_SERVER,
            DB_DATABASE,
            DB_USER,
            pool_minsize,
            pool_maxsize,
        )
    except Exception:
        logger.exception(
            "Не удалось создать пул соединений: server=%s database=%s user=%s",
            DB_SERVER,
            DB_DATABASE,
            DB_USER,
        )
        raise


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
