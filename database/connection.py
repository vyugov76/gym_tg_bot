"""Асинхронное подключение к MS SQL Server через ODBC (aioodbc)."""

from __future__ import annotations

import os  # <-- ОБЯЗАТЕЛЬНО ДОБАВЛЯЕМ ЭТОТ ИМПОРТ
import aioodbc
from dotenv import load_dotenv

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
    _pool = await aioodbc.create_pool(
        dsn=build_dsn(),
        minsize=1,
        maxsize=10,
        autocommit=True,
    )


async def close_db() -> None:
    """Закрывает пул соединений при остановке бота."""
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


def get_pool() -> aioodbc.Pool:
    """Возвращает активный пул. Вызывать только после init_db()."""
    if _pool is None:
        raise RuntimeError("Пул БД не инициализирован. Вызовите init_db() перед работой.")
    return _pool
