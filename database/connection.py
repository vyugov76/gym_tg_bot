"""
Модуль асинхронного подключения к MS SQL Server.

- Использует aioodbc и ODBC Driver
- Загружает параметры подключения из .env в корне проекта
- Управляет глобальным пулом соединений (init, refresh, close)
- Применяет идемпотентные миграции схемы при старте бота
"""

from __future__ import annotations

from pathlib import Path
import asyncio
import logging
import os

import aioodbc
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

root_dir = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=root_dir / ".env")

DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
DB_SERVER = os.getenv("DB_SERVER", "localhost")
DB_DATABASE = os.getenv("DB_DATABASE", "")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

_pool: aioodbc.Pool | None = None
_pool_generation = 0
_db_lock = asyncio.Lock()

POOL_MINSIZE = 1
POOL_MAXSIZE = 10

ODBC_CONNECTION_TIMEOUT = 5
ODBC_QUERY_TIMEOUT = 5


def build_dsn() -> str:
    """
    Формирует строку подключения ODBC с авторизацией по логину и паролю.

    Возвращает:
        Строка DSN для aioodbc.create_pool.
    """
    return (
        f"DRIVER={{{DB_DRIVER}}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_DATABASE};"
        f"UID={DB_USER};"
        f"PWD={DB_PASSWORD};"
        "TrustServerCertificate=yes;"
        f"Connection Timeout={ODBC_CONNECTION_TIMEOUT};"
        f"Timeout={ODBC_QUERY_TIMEOUT};"
    )


async def _create_pool() -> aioodbc.Pool:
    """
    Создаёт новый пул соединений с текущими параметрами DSN.

    Возвращает:
        Экземпляр aioodbc.Pool с autocommit=True.
    """
    return await aioodbc.create_pool(
        dsn=build_dsn(),
        minsize=POOL_MINSIZE,
        maxsize=POOL_MAXSIZE,
        autocommit=True,
    )


_SCHEMA_MIGRATIONS: tuple[str, ...] = (
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.columns
        WHERE object_id = OBJECT_ID('GTB_workouts') AND name = 'id_preset'
    )
        ALTER TABLE GTB_workouts ADD id_preset INT NULL
    """,
    """
    IF NOT EXISTS (
        SELECT 1 FROM sys.foreign_keys
        WHERE name = 'FK_GTB_workouts_GTB_preset_workouts'
    )
        ALTER TABLE GTB_workouts ADD CONSTRAINT FK_GTB_workouts_GTB_preset_workouts
        FOREIGN KEY (id_preset) REFERENCES GTB_preset_workouts(id_preset)
        ON DELETE NO ACTION
    """,
)


async def apply_schema_migrations() -> None:
    """
    Применяет идемпотентные миграции схемы БД.

    Вызывается при успешном init_db(). При ошибке логирует исключение и пробрасывает его.

    Возвращает:
        None.
    """
    pool = await get_pool()
    conn = await pool.acquire()
    try:
        async with conn.cursor() as cur:
            for sql in _SCHEMA_MIGRATIONS:
                await cur.execute(sql)
        logger.info("Миграции схемы БД применены успешно")
    except Exception:
        logger.exception("Ошибка применения миграций схемы БД")
        raise
    finally:
        await pool.release(conn)


async def _close_pool(pool: aioodbc.Pool | None) -> None:
    """
    Безопасно закрывает пул соединений.

    Параметры:
        pool: Пул для закрытия или None (ничего не делает).

    Возвращает:
        None.
    """
    if pool is None:
        return
    try:
        pool.close()
        await pool.wait_closed()
    except Exception:
        logger.warning("Ошибка при закрытии пула соединений", exc_info=True)


async def init_db() -> None:
    """
    Создаёт пул соединений с базой данных с повторными попытками.

    До 5 попыток с паузой 3 секунды. После успеха применяет миграции схемы.
    Повторный вызов безопасен - пул создаётся только один раз.

    Возвращает:
        None.
    """
    global _pool

    if _pool is not None:
        return

    async with _db_lock:
        if _pool is not None:
            return

        retries = 5
        last_error: Exception | None = None
        pool_ready = False

        for attempt in range(1, retries + 1):
            logger.info("Попытка подключения к БД %s/%s...", attempt, retries)
            try:
                new_pool = await _create_pool()
                _pool = new_pool
                pool_ready = True
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
                break
            except Exception as e:
                last_error = e
                _pool = None
                logger.warning(
                    "Попытка %s завершилась ошибкой: %s. Повтор через 3 сек...",
                    attempt,
                    e,
                )
                if attempt < retries:
                    await asyncio.sleep(3)

        if not pool_ready:
            logger.critical("Все попытки подключения к базе данных исчерпаны.")
            raise last_error

    await apply_schema_migrations()


async def refresh_db_pool() -> None:
    """
    Пересоздаёт пул после потери соединения (таймаут простоя и т.п.).

    Сначала создаёт новый пул, затем атомарно подменяет глобальный экземпляр.
    Старый пул закрывается уже после подмены, вне критической секции.

    Возвращает:
        None.
    """
    global _pool, _pool_generation

    generation_before = _pool_generation
    old_pool: aioodbc.Pool | None = None

    async with _db_lock:
        if _pool_generation != generation_before:
            logger.info(
                "Пул уже пересоздан другой задачей (generation %s -> %s), пропускаем",
                generation_before,
                _pool_generation,
            )
            return

        logger.warning("Пересоздание пула соединений с БД...")
        old_pool = _pool
        new_pool = await _create_pool()
        _pool = new_pool
        _pool_generation += 1
        logger.info(
            "Пул соединений с БД успешно пересоздан (generation=%s)",
            _pool_generation,
        )

    await _close_pool(old_pool)


async def close_db() -> None:
    """
    Закрывает пул соединений при остановке бота.

    Безопасен при повторном вызове или если пул не был инициализирован.

    Возвращает:
        None.
    """
    global _pool

    async with _db_lock:
        if _pool is None:
            return
        pool = _pool
        _pool = None
        pool.close()
        await pool.wait_closed()
        logger.info("Пул соединений с БД закрыт")


async def get_pool() -> aioodbc.Pool:
    """
    Возвращает активный пул соединений.

    Если пул пересоздаётся, ожидает освобождения _db_lock и возвращает новый экземпляр.

    Возвращает:
        Текущий aioodbc.Pool.

    Исключения:
        RuntimeError: Если init_db() ещё не вызывался или пул не создан.
    """
    async with _db_lock:
        if _pool is None:
            raise RuntimeError(
                "Пул БД не инициализирован. Вызовите init_db() перед работой."
            )
        return _pool


async def discard_connection(conn) -> None:
    """
    Закрывает протухшее соединение, не возвращая его в пул.

    Вызывать при OperationalError / ProgrammingError об обрыве связи.

    Параметры:
        conn: Соединение aioodbc, которое нужно уничтожить.

    Возвращает:
        None.
    """
    try:
        await conn.close()
    except Exception:
        logger.debug(
            "Не удалось корректно закрыть проблемное соединение",
            exc_info=True,
        )
