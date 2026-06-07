"""Асинхронное подключение к MS SQL Server через ODBC (aioodbc)."""

from __future__ import annotations

import aioodbc

# Параметры подключения — замените на свои
DB_CONFIG = {
    "driver": "ODBC Driver 17 for SQL Server",
    "server": "stud-mssql.sttec.yar.ru,38325",
    "database": "user260_db",
    "user": "user260_db",
    "password": "user260",
}

# Глобальный пул соединений (создаётся при старте бота)
_pool: aioodbc.Pool | None = None


def build_dsn() -> str:
    """Формирует строку подключения ODBC для локального SQL Server."""
    return (
        f"DRIVER={{{DB_CONFIG['driver']}}};"
        f"SERVER={DB_CONFIG['server']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['user']};"
        f"PWD={DB_CONFIG['password']};"
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
