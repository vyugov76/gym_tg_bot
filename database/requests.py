"""
Модуль SQL-запросов к базе данных бота.

- Пользователи, категории, каталог упражнений
- Шаблоны тренировок (пресеты)
- Активные и завершённые тренировки, подходы
- Статистика и in-memory кэш каталога упражнений
- Повторы запросов при обрыве соединения и обновление пула
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any, AsyncIterator, Literal

import pyodbc

from database.connection import discard_connection, get_pool, refresh_db_pool

logger = logging.getLogger(__name__)

FetchMode = Literal["one", "all", "scalar", "none"]
MAX_QUERY_ATTEMPTS = 3
RETRY_DELAY_SEC = 0.5

_CONNECTION_ERROR_CODES = frozenset({"08S01", "HYT00", "HYT01", "01000"})

USER_CACHE_TTL_SECONDS = 7200

_admin_exercises_cache: list[dict[str, Any]] | None = None
_user_exercises_cache: dict[int, dict[str, Any]] = {}


def _cache_monotonic_time() -> float:
    """
    Возвращает монотонное время для TTL кэша.

    Возвращает:
        Текущее monotonic-время event loop в секундах.
    """
    return asyncio.get_event_loop().time()


def _store_user_exercises_cache(user_id: int, exercises: list[dict[str, Any]]) -> None:
    """
    Сохраняет каталог упражнений пользователя в in-memory кэш.

    Параметры:
        user_id: Внутренний id_user.
        exercises: Нормализованный список упражнений каталога.

    Возвращает:
        None.
    """
    _user_exercises_cache[user_id] = {
        "data": exercises,
        "expires_at": _cache_monotonic_time() + USER_CACHE_TTL_SECONDS,
    }


def _get_valid_user_exercises_cache(user_id: int) -> list[dict[str, Any]] | None:
    """
    Возвращает кэш каталога пользователя, если он ещё не истёк.

    Параметры:
        user_id: Внутренний id_user.

    Возвращает:
        Список упражнений или None, если кэш отсутствует или просрочен.
    """
    entry = _user_exercises_cache.get(user_id)
    if entry is None:
        return None
    if _cache_monotonic_time() >= entry["expires_at"]:
        _user_exercises_cache.pop(user_id, None)
        return None
    return entry["data"]


async def _fetch_one_dict(cur) -> dict[str, Any] | None:
    """
    Читает одну строку курсора и преобразует её в словарь.

    Параметры:
        cur: Асинхронный курсор aioodbc.

    Возвращает:
        Словарь column_name -> value или None, если строк нет.
    """
    row = await cur.fetchone()
    if row is None:
        return None
    columns = [col[0] for col in cur.description]
    return dict(zip(columns, row, strict=False))


async def _fetch_all_dicts(cur) -> list[dict[str, Any]]:
    """
    Читает все строки курсора и преобразует их в список словарей.

    Параметры:
        cur: Асинхронный курсор aioodbc.

    Возвращает:
        Список словарей column_name -> value.
    """
    rows = await cur.fetchall()
    columns = [col[0] for col in cur.description]
    return [dict(zip(columns, row, strict=False)) for row in rows]


def _error_text(exc: BaseException) -> str:
    """
    Возвращает текст исключения в нижнем регистре для сравнения.

    Параметры:
        exc: Исключение.

    Возвращает:
        str(exc).lower().
    """
    return str(exc).lower()


def _is_dead_connection_error(exc: BaseException) -> bool:
    """
    Определяет, связана ли ошибка с обрывом TCP или протухшим соединением из пула.

    Параметры:
        exc: Исключение из execute/fetch.

    Возвращает:
        True, если соединение считается нерабочим (10054, 08S01, closed connection и т.п.).
    """
    if isinstance(exc, (pyodbc.OperationalError, pyodbc.InterfaceError)):
        return True

    if isinstance(exc, pyodbc.ProgrammingError):
        text = _error_text(exc)
        if (
            "connection has been closed" in text
            or "closed connection" in text
            or "cursor's connection has been closed" in text
        ):
            return True

    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError)):
        return True

    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 10054:
        return True

    if isinstance(exc, pyodbc.Error):
        if exc.args:
            code = str(exc.args[0])
            if code in _CONNECTION_ERROR_CODES:
                return True
        if "10054" in str(exc) or "08s01" in _error_text(exc):
            return True

    cause = exc.__cause__
    if cause is not None and cause is not exc:
        return _is_dead_connection_error(cause)

    return False


async def _read_fetch_result(cur, fetch: FetchMode) -> Any:
    """
    Читает результат запроса в формате, заданном параметром fetch.

    Параметры:
        cur: Асинхронный курсор после execute.
        fetch: Режим чтения: one, all, scalar или none.

    Возвращает:
        dict, list[dict], скалярное значение или None в зависимости от fetch.
    """
    if fetch == "one":
        return await _fetch_one_dict(cur)
    if fetch == "all":
        return await _fetch_all_dicts(cur)
    if fetch == "scalar":
        row = await cur.fetchone()
        return row[0] if row else None
    return None


@asynccontextmanager
async def _pooled_connection() -> AsyncIterator[Any]:
    """
    Асинхронный контекст: соединение из пула с release или discard при обрыве.

    Возвращает:
        Асинхронный итератор, отдающий соединение aioodbc из пула.
    """
    pool = await get_pool()
    conn = await pool.acquire()
    discard = False
    try:
        yield conn
    except Exception as exc:
        if _is_dead_connection_error(exc):
            logger.warning(
                "Протухшее соединение из пула, закрываем: %s",
                exc,
            )
            await discard_connection(conn)
            discard = True
        raise
    finally:
        if not discard:
            await pool.release(conn)


async def _execute_query(
    sql: str,
    params: tuple,
    fetch: FetchMode,
) -> Any:
    """
    Выполняет один SQL-запрос: acquire -> execute -> release (или discard при обрыве).

    Параметры:
        sql: Текст SQL-запроса с плейсхолдерами ?.
        params: Кортеж параметров для подстановки.
        fetch: Режим чтения результата.

    Возвращает:
        Результат _read_fetch_result или None для fetch=none.
    """
    async with _pooled_connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await _read_fetch_result(cur, fetch)


async def _run_query(
    sql: str,
    params: tuple = (),
    fetch: FetchMode = "none",
) -> Any:
    """
    Выполняет SQL с повторами при обрыве соединения (до MAX_QUERY_ATTEMPTS попыток).

    Параметры:
        sql: Текст SQL-запроса.
        params: Параметры запроса, по умолчанию пустой кортеж.
        fetch: Режим чтения результата, по умолчанию none.

    Возвращает:
        Результат запроса или None для fetch=none.

    Исключения:
        Exception: Любая не связанная с обрывом ошибка или исчерпание попыток.
    """
    last_error: BaseException | None = None

    for attempt in range(1, MAX_QUERY_ATTEMPTS + 1):
        try:
            logger.debug(
                "Выполнение SQL (попытка %s/%s): %s с параметрами: %s",
                attempt,
                MAX_QUERY_ATTEMPTS,
                sql.strip(),
                params,
            )
            return await _execute_query(sql, params, fetch)
        except Exception as exc:
            if not _is_dead_connection_error(exc):
                logger.exception("Ошибка при работе с БД")
                raise

            last_error = exc
            if attempt < MAX_QUERY_ATTEMPTS:
                logger.warning(
                    "Обрыв соединения с БД (попытка %s/%s): %s. "
                    "Обновляем пул, пауза %.1f с и повтор...",
                    attempt,
                    MAX_QUERY_ATTEMPTS,
                    exc,
                    RETRY_DELAY_SEC,
                )
                await refresh_db_pool()
                await asyncio.sleep(RETRY_DELAY_SEC)
                continue

            logger.error(
                "Запрос не выполнен после %s попыток: %s",
                MAX_QUERY_ATTEMPTS,
                exc,
            )
            raise

    if last_error is not None:
        raise last_error
    return None


def _as_exercise_type(value: Any) -> int:
    """
    Приводит значение is_bodyweight к целочисленному типу упражнения.

    Параметры:
        value: Значение из БД или None.

    Возвращает:
        0 - с весом, 1 - свой вес, 2 - на время; None трактуется как 0.
    """
    return int(value) if value is not None else 0


def _normalize_exercise_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    Добавляет поле exercise_type и нормализует is_bodyweight в строке упражнения.

    Параметры:
        row: Строка результата запроса (изменяется in-place).

    Возвращает:
        Тот же словарь row с заполненным exercise_type.
    """
    row["is_bodyweight"] = _as_exercise_type(row["is_bodyweight"])
    row["exercise_type"] = row["is_bodyweight"]
    return row


_SET_DETAIL_COLUMNS = """
    s.set_number,
    s.weight,
    s.reps,
    s.duration_seconds,
    s.distance_meters
"""

_WORKOUT_DETAIL_SELECT = f"""
    SELECT
        w.id_workout,
        w.started_at,
        w.finished_at,
        w.id_preset,
        pw.preset_name,
        we.id_workout_exercise,
        we.exercise_name,
        we.is_bodyweight,
        {_SET_DETAIL_COLUMNS}
    FROM GTB_workouts w
    LEFT JOIN GTB_preset_workouts pw
        ON pw.id_preset = w.id_preset
    INNER JOIN GTB_workout_exercises we
        ON we.workout_id = w.id_workout
    LEFT JOIN GTB_sets s
        ON s.id_workout_exercise = we.id_workout_exercise
"""

_CATALOG_SELECT = """
    SELECT
        id_workout_exercise AS id,
        exercise_name AS name,
        is_bodyweight,
        category_id,
        id_user
    FROM GTB_workout_exercises
"""


def clear_exercise_cache(user_id: int | None = None) -> None:
    """
    Сбрасывает кэш каталога упражнений.

    Параметры:
        user_id: Если None - сбрасывает весь кэш; иначе только для одного пользователя.

    Возвращает:
        None.
    """
    global _admin_exercises_cache
    if user_id is None:
        _admin_exercises_cache = None
        _user_exercises_cache.clear()
        return
    _user_exercises_cache.pop(user_id, None)


def _invalidate_exercise_cache(user_id: int | None = None) -> None:
    """
    Обёртка над clear_exercise_cache для вызова после изменений каталога.

    Параметры:
        user_id: Пользователь, чей кэш нужно сбросить, или None для полного сброса.

    Возвращает:
        None.
    """
    clear_exercise_cache(user_id)


async def _fetch_admin_exercises(*, refresh: bool = False) -> list[dict[str, Any]]:
    """
    Загружает админский каталог упражнений (id_user IS NULL) с in-memory кэшем.

    Параметры:
        refresh: Принудительно перечитать данные из БД, игнорируя кэш.

    Возвращает:
        Список нормализованных упражнений админского каталога.
    """
    global _admin_exercises_cache
    if not refresh and _admin_exercises_cache is not None:
        return _admin_exercises_cache

    rows = await _run_query(
        f"""
        {_CATALOG_SELECT}
        WHERE id_user IS NULL
          AND workout_id IS NULL
          AND is_deleted = 0
        ORDER BY exercise_name
        """,
        fetch="all",
    )
    _admin_exercises_cache = [_normalize_exercise_row(row) for row in rows]
    return _admin_exercises_cache


async def _fetch_user_catalog_exercises(
    user_id: int,
    *,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """
    Загружает личные упражнения пользователя в каталоге с кэшем на user_id.

    Параметры:
        user_id: Внутренний id_user.
        refresh: Принудительно перечитать данные из БД.

    Возвращает:
        Список нормализованных упражнений пользователя.
    """
    if not refresh:
        cached = _get_valid_user_exercises_cache(user_id)
        if cached is not None:
            return cached

    rows = await _run_query(
        f"""
        {_CATALOG_SELECT}
        WHERE id_user = ?
          AND workout_id IS NULL
          AND is_deleted = 0
        ORDER BY exercise_name
        """,
        (user_id,),
        fetch="all",
    )
    normalized = [_normalize_exercise_row(row) for row in rows]
    _store_user_exercises_cache(user_id, normalized)
    return normalized


async def _fetch_workout_detail_rows(
    where_clause: str,
    params: tuple,
    order_by: str,
) -> list[dict[str, Any]]:
    """
    Выполняет детальный SELECT тренировки с подходами и нормализует типы упражнений.

    Параметры:
        where_clause: Фрагмент SQL после WHERE (без ключевого слова WHERE).
        params: Параметры для where_clause.
        order_by: Выражение ORDER BY (без ключевого слова ORDER BY).

    Возвращает:
        Список строк с полями тренировки, упражнения и подхода.
    """
    rows = await _run_query(
        f"""
        {_WORKOUT_DETAIL_SELECT}
        WHERE {where_clause}
        ORDER BY {order_by}
        """,
        params,
        fetch="all",
    )
    return _normalize_workout_detail_rows(rows)


def _normalize_workout_detail_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Нормализует is_bodyweight и добавляет exercise_type в строках детализации тренировки.

    Параметры:
        rows: Список строк результата JOIN (изменяется in-place).

    Возвращает:
        Тот же список rows с заполненным exercise_type.
    """
    for row in rows:
        row["is_bodyweight"] = _as_exercise_type(row["is_bodyweight"])
        row["exercise_type"] = row["is_bodyweight"]
    return rows


# --- Пользователи ---


async def get_user_by_telegram_id(telegram_id: int) -> dict[str, Any] | None:
    """
    Находит пользователя по Telegram ID.

    Параметры:
        telegram_id: ID пользователя в Telegram.

    Возвращает:
        Словарь с полями id, telegram_id, height, weight, created_at или None.
    """
    return await _run_query(
        """
        SELECT id_user AS id, telegram_id, height, weight, created_at
        FROM GTB_users
        WHERE telegram_id = ?
        """,
        (telegram_id,),
        fetch="one",
    )


async def update_user_height(user_id: int, height: float) -> None:
    """
    Обновляет рост пользователя.

    Параметры:
        user_id: Внутренний id_user.
        height: Новое значение роста.

    Возвращает:
        None.
    """
    await _run_query(
        """
        UPDATE GTB_users
        SET height = ?
        WHERE id_user = ?
        """,
        (height, user_id),
    )


async def update_user_weight(user_id: int, weight: float) -> None:
    """
    Обновляет вес пользователя.

    Параметры:
        user_id: Внутренний id_user.
        weight: Новое значение веса.

    Возвращает:
        None.
    """
    await _run_query(
        """
        UPDATE GTB_users
        SET weight = ?
        WHERE id_user = ?
        """,
        (weight, user_id),
    )


async def add_user(telegram_id: int, height: float, weight: float) -> int:
    """
    Создаёт нового пользователя.

    Параметры:
        telegram_id: ID пользователя в Telegram.
        height: Рост при регистрации.
        weight: Вес при регистрации.

    Возвращает:
        id_user созданной записи.
    """
    user_id = await _run_query(
        """
        INSERT INTO GTB_users (telegram_id, height, weight)
        OUTPUT INSERTED.id_user
        VALUES (?, ?, ?)
        """,
        (telegram_id, height, weight),
        fetch="scalar",
    )
    return int(user_id)


# --- Категории ---


async def get_categories_by_user_id(user_id: int) -> list[dict[str, Any]]:
    """
    Возвращает категории упражнений пользователя.

    Параметры:
        user_id: Внутренний id_user.

    Возвращает:
        Список словарей с полями id и name, отсортированный по имени.
    """
    return await _run_query(
        """
        SELECT id_category AS id, category_name AS name
        FROM GTB_categories
        WHERE id_user = ?
        ORDER BY category_name
        """,
        (user_id,),
        fetch="all",
    )


async def get_category_by_id(category_id: int) -> dict[str, Any] | None:
    """
    Возвращает категорию по id.

    Параметры:
        category_id: id_category.

    Возвращает:
        Словарь с полями id, id_user, name или None.
    """
    return await _run_query(
        """
        SELECT id_category AS id, id_user, category_name AS name
        FROM GTB_categories
        WHERE id_category = ?
        """,
        (category_id,),
        fetch="one",
    )


async def add_category(user_id: int, category_name: str) -> int:
    """
    Создаёт категорию упражнений для пользователя.

    Параметры:
        user_id: Внутренний id_user.
        category_name: Название категории.

    Возвращает:
        id_category новой записи.
    """
    category_id = await _run_query(
        """
        INSERT INTO GTB_categories (id_user, category_name)
        OUTPUT INSERTED.id_category
        VALUES (?, ?)
        """,
        (user_id, category_name),
        fetch="scalar",
    )
    return int(category_id)


async def bulk_assign_exercises_to_category(
    exercise_ids: list[int],
    category_id: int,
    id_user: int,
) -> int:
    """
    Назначает несортированные упражнения в категорию.

    Параметры:
        exercise_ids: Список id_workout_exercise для обновления.
        category_id: Целевая категория.
        id_user: Владелец упражнений.

    Возвращает:
        Число переданных ID (0, если список пуст).
    """
    if not exercise_ids:
        return 0
    placeholders = ",".join("?" * len(exercise_ids))
    await _run_query(
        f"""
        UPDATE GTB_workout_exercises
        SET category_id = ?
        WHERE id_workout_exercise IN ({placeholders})
          AND id_user = ?
          AND workout_id IS NULL
          AND is_deleted = 0
          AND category_id IS NULL
        """,
        (category_id, *exercise_ids, id_user),
    )
    _invalidate_exercise_cache(id_user)
    return len(exercise_ids)


async def bulk_unassign_exercises_from_category(
    exercise_ids: list[int],
    category_id: int,
    id_user: int,
) -> int:
    """
    Сбрасывает category_id в NULL для упражнений указанной категории.

    Параметры:
        exercise_ids: Список id_workout_exercise.
        category_id: Категория, из которой снимаются упражнения.
        id_user: Владелец упражнений.

    Возвращает:
        Число переданных ID (0, если список пуст).
    """
    if not exercise_ids:
        return 0
    placeholders = ",".join("?" * len(exercise_ids))
    await _run_query(
        f"""
        UPDATE GTB_workout_exercises
        SET category_id = NULL
        WHERE id_workout_exercise IN ({placeholders})
          AND id_user = ?
          AND category_id = ?
          AND workout_id IS NULL
          AND is_deleted = 0
        """,
        (*exercise_ids, id_user, category_id),
    )
    _invalidate_exercise_cache(id_user)
    return len(exercise_ids)


async def delete_category(category_id: int, user_id: int) -> None:
    """
    Удаляет категорию пользователя.

    Упражнения получают category_id = NULL (ON DELETE SET NULL).

    Параметры:
        category_id: id_category.
        user_id: Внутренний id_user владельца.

    Возвращает:
        None.
    """
    await _run_query(
        """
        DELETE FROM GTB_categories
        WHERE id_category = ? AND id_user = ?
        """,
        (category_id, user_id),
    )


async def update_category_name(
    category_id: int,
    user_id: int,
    category_name: str,
) -> None:
    """
    Переименовывает категорию пользователя.

    Параметры:
        category_id: id_category.
        user_id: Внутренний id_user владельца.
        category_name: Новое название категории.

    Возвращает:
        None.
    """
    await _run_query(
        """
        UPDATE GTB_categories
        SET category_name = ?
        WHERE id_category = ? AND id_user = ?
        """,
        (category_name, category_id, user_id),
    )


# --- Глобальный каталог упражнений (workout_id IS NULL) ---


async def get_global_exercises_by_user_id(
    user_id: int,
    *,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """
    Возвращает полный каталог: админские и личные упражнения пользователя.

    Параметры:
        user_id: Внутренний id_user.
        refresh: Принудительно перечитать данные из БД, минуя кэш.

    Возвращает:
        Объединённый отсортированный список упражнений каталога.
    """
    admin = await _fetch_admin_exercises(refresh=refresh)
    user_rows = await _fetch_user_catalog_exercises(user_id, refresh=refresh)
    merged = [*admin, *user_rows]
    merged.sort(key=lambda row: row["name"].casefold())
    return merged


async def get_exercises_by_category(
    user_id: int,
    category_id: int,
    *,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """
    Возвращает упражнения указанной категории (фильтрация на стороне СУБД).

    Параметры:
        user_id: Внутренний id_user.
        category_id: id_category.
        refresh: Не используется; запрос всегда читает актуальные данные из БД.

    Возвращает:
        Список упражнений категории (админские и пользовательские).
    """
    del refresh
    rows = await _run_query(
        f"""
        {_CATALOG_SELECT}
        WHERE workout_id IS NULL
          AND is_deleted = 0
          AND category_id = ?
          AND (id_user = ? OR id_user IS NULL)
        ORDER BY exercise_name
        """,
        (category_id, user_id),
        fetch="all",
    )
    return [_normalize_exercise_row(row) for row in rows]


async def get_unsorted_exercises(
    user_id: int,
    *,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """
    Возвращает несортированные упражнения (category_id IS NULL).

    Параметры:
        user_id: Внутренний id_user.
        refresh: Не используется; запрос всегда читает актуальные данные из БД.

    Возвращает:
        Список упражнений без категории.
    """
    del refresh
    rows = await _run_query(
        f"""
        {_CATALOG_SELECT}
        WHERE workout_id IS NULL
          AND is_deleted = 0
          AND category_id IS NULL
          AND (id_user = ? OR id_user IS NULL)
        ORDER BY exercise_name
        """,
        (user_id,),
        fetch="all",
    )
    return [_normalize_exercise_row(row) for row in rows]


async def get_exercise_by_id(exercise_id: int) -> dict[str, Any] | None:
    """
    Возвращает упражнение по id_workout_exercise.

    Параметры:
        exercise_id: id_workout_exercise.

    Возвращает:
        Нормализованный словарь упражнения или None, если не найдено.
    """
    row = await _run_query(
        """
        SELECT
            id_workout_exercise AS id,
            id_user,
            exercise_name AS name,
            is_bodyweight,
            category_id,
            workout_id,
            is_deleted
        FROM GTB_workout_exercises
        WHERE id_workout_exercise = ?
          AND (workout_id IS NOT NULL OR is_deleted = 0)
        """,
        (exercise_id,),
        fetch="one",
    )
    return _normalize_exercise_row(row) if row else None


async def user_has_catalog_exercise_name(user_id: int, exercise_name: str) -> bool:
    """
    Проверяет, есть ли у пользователя упражнение с таким названием в каталоге.

    Параметры:
        user_id: внутренний id_user
        exercise_name: название для проверки без учёта регистра

    Возвращает:
        True, если неудалённое упражнение с таким именем уже существует
    """
    found = await _run_query(
        """
        SELECT TOP 1 1
        FROM GTB_workout_exercises
        WHERE id_user = ?
          AND workout_id IS NULL
          AND is_deleted = 0
          AND LOWER(exercise_name) = LOWER(?)
        """,
        (user_id, exercise_name.strip()),
        fetch="scalar",
    )
    return found is not None


async def add_global_exercise(
    user_id: int,
    exercise_name: str,
    exercise_type: int,
    category_id: int | None = None,
) -> int:
    """
    Добавляет упражнение в глобальный каталог пользователя.

    Параметры:
        user_id: Внутренний id_user.
        exercise_name: Название упражнения.
        exercise_type: Тип: 0 - с весом, 1 - свой вес, 2 - на время.
        category_id: id_category или None для несортированных.

    Возвращает:
        id_workout_exercise новой записи.
    """
    exercise_id = await _run_query(
        """
        INSERT INTO GTB_workout_exercises
            (workout_id, id_user, exercise_name, is_bodyweight, category_id, is_deleted)
        OUTPUT INSERTED.id_workout_exercise
        VALUES (NULL, ?, ?, ?, ?, 0)
        """,
        (user_id, exercise_name, exercise_type, category_id),
        fetch="scalar",
    )
    _invalidate_exercise_cache(user_id)
    return int(exercise_id)


async def update_exercise_name(exercise_id: int, new_name: str) -> None:
    """
    Переименовывает упражнение в глобальном каталоге.

    Параметры:
        exercise_id: id_workout_exercise.
        new_name: Новое название.

    Возвращает:
        None.
    """
    exercise = await get_exercise_by_id(exercise_id)
    await _run_query(
        """
        UPDATE GTB_workout_exercises
        SET exercise_name = ?
        WHERE id_workout_exercise = ? AND workout_id IS NULL
          AND id_user IS NOT NULL AND is_deleted = 0
        """,
        (new_name, exercise_id),
    )
    if exercise and exercise.get("id_user") is not None:
        _invalidate_exercise_cache(int(exercise["id_user"]))


async def soft_delete_global_exercise(exercise_id: int, id_user: int) -> bool:
    """
    Мягко удаляет упражнение из каталога пользователя (is_deleted = 1).

    Параметры:
        exercise_id: id_workout_exercise.
        id_user: Владелец упражнения.

    Возвращает:
        True после выполнения UPDATE.
    """
    await _run_query(
        """
        UPDATE GTB_workout_exercises
        SET is_deleted = 1
        WHERE id_workout_exercise = ?
          AND id_user = ?
          AND workout_id IS NULL
          AND is_deleted = 0
        """,
        (exercise_id, id_user),
    )
    _invalidate_exercise_cache(id_user)
    return True


async def cycle_exercise_type(exercise_id: int) -> int:
    """
    Переключает тип глобального упражнения по циклу 0 -> 1 -> 2 -> 0.

    Параметры:
        exercise_id: id_workout_exercise.

    Возвращает:
        Новое значение типа или 0, если упражнение не найдено.
    """
    exercise = await get_exercise_by_id(exercise_id)
    if not exercise:
        return 0
    current = _as_exercise_type(exercise["is_bodyweight"])
    new_value = (current + 1) % 3
    await _run_query(
        """
        UPDATE GTB_workout_exercises
        SET is_bodyweight = ?
        WHERE id_workout_exercise = ? AND workout_id IS NULL
          AND id_user IS NOT NULL AND is_deleted = 0
        """,
        (new_value, exercise_id),
    )
    if exercise.get("id_user") is not None:
        _invalidate_exercise_cache(int(exercise["id_user"]))
    return new_value


async def get_exercises_by_user_id(user_id: int) -> list[dict[str, Any]]:
    """
    Обратная совместимость: алиас get_global_exercises_by_user_id.

    Параметры:
        user_id: Внутренний id_user.

    Возвращает:
        Полный каталог упражнений пользователя.
    """
    return await get_global_exercises_by_user_id(user_id)


# --- Пресеты (готовые тренировки) ---


async def get_presets_by_user_id(user_id: int) -> list[dict[str, Any]]:
    """
    Возвращает шаблоны тренировок пользователя.

    Параметры:
        user_id: Внутренний id_user.

    Возвращает:
        Список словарей с полями id и name.
    """
    return await _run_query(
        """
        SELECT id_preset AS id, preset_name AS name, preset_name
        FROM GTB_preset_workouts
        WHERE id_user = ? AND is_deleted = 0
        ORDER BY preset_name
        """,
        (user_id,),
        fetch="all",
    )


async def get_preset_by_id(preset_id: int) -> dict[str, Any] | None:
    """
    Возвращает шаблон тренировки по id.

    Параметры:
        preset_id: id_preset.

    Возвращает:
        Словарь с полями id, id_user, name или None.
    """
    return await _run_query(
        """
        SELECT id_preset AS id, id_user, preset_name AS name, preset_name
        FROM GTB_preset_workouts
        WHERE id_preset = ? AND is_deleted = 0
        """,
        (preset_id,),
        fetch="one",
    )


async def get_preset_exercises(preset_id: int) -> list[dict[str, Any]]:
    """
    Возвращает упражнения шаблона в порядке sequence_number.

    Параметры:
        preset_id: id_preset.

    Возвращает:
        Список нормализованных упражнений шаблона.
    """
    rows = await _run_query(
        """
        SELECT
            id_preset_exercise AS id,
            exercise_name AS name,
            is_bodyweight,
            sequence_number,
            sets_count
        FROM GTB_preset_exercises
        WHERE id_preset = ?
        ORDER BY sequence_number, id_preset_exercise
        """,
        (preset_id,),
        fetch="all",
    )
    return [_normalize_exercise_row(row) for row in rows]


async def create_preset(user_id: int, preset_name: str) -> int:
    """
    Создаёт пустой шаблон тренировки.

    Параметры:
        user_id: Внутренний id_user.
        preset_name: Название шаблона.

    Возвращает:
        id_preset новой записи.
    """
    preset_id = await _run_query(
        """
        INSERT INTO GTB_preset_workouts (id_user, preset_name, is_deleted)
        OUTPUT INSERTED.id_preset
        VALUES (?, ?, 0)
        """,
        (user_id, preset_name),
        fetch="scalar",
    )
    return int(preset_id)


async def get_max_preset_sequence_number(preset_id: int) -> int:
    """
    Возвращает максимальный sequence_number в шаблоне.

    Параметры:
        preset_id: id_preset.

    Возвращает:
        Максимальный порядковый номер или 0, если шаблон пуст.
    """
    value = await _run_query(
        """
        SELECT ISNULL(MAX(sequence_number), 0)
        FROM GTB_preset_exercises
        WHERE id_preset = ?
        """,
        (preset_id,),
        fetch="scalar",
    )
    return int(value or 0)


async def bulk_add_global_exercises_to_preset(
    preset_id: int,
    global_exercise_ids: list[int],
    id_user: int,
) -> int:
    """
    Добавляет глобальные упражнения в шаблон тренировки.

    Параметры:
        preset_id: id_preset.
        global_exercise_ids: Список id упражнений каталога.
        id_user: Владелец шаблона и упражнений.

    Возвращает:
        Число фактически добавленных упражнений.
    """
    if not global_exercise_ids:
        return 0

    preset = await get_preset_by_id(preset_id)
    if not preset or preset["id_user"] != id_user:
        return 0

    sequence = await get_max_preset_sequence_number(preset_id)
    added = 0
    for exercise_id in global_exercise_ids:
        exercise = await get_exercise_by_id(exercise_id)
        if not exercise or exercise.get("workout_id") is not None:
            continue
        ex_owner = exercise.get("id_user")
        if ex_owner is not None and ex_owner != id_user:
            continue
        sequence += 1
        await add_preset_exercise(
            preset_id=preset_id,
            exercise_name=exercise["name"],
            exercise_type=exercise["is_bodyweight"],
            sequence_number=sequence,
            sets_count=0,
        )
        added += 1
    return added


async def bulk_delete_preset_exercises(
    preset_exercise_ids: list[int],
    preset_id: int,
    id_user: int,
) -> int:
    """
    Удаляет упражнения из шаблона по списку id.

    Параметры:
        preset_exercise_ids: Список id_preset_exercise.
        preset_id: id_preset.
        id_user: Владелец шаблона.

    Возвращает:
        Число переданных ID (0, если список пуст или нет доступа).
    """
    if not preset_exercise_ids:
        return 0

    preset = await get_preset_by_id(preset_id)
    if not preset or preset["id_user"] != id_user:
        return 0

    placeholders = ",".join("?" * len(preset_exercise_ids))
    await _run_query(
        f"""
        DELETE FROM GTB_preset_exercises
        WHERE id_preset_exercise IN ({placeholders})
          AND id_preset = ?
        """,
        (*preset_exercise_ids, preset_id),
    )
    return len(preset_exercise_ids)


async def add_preset_exercise(
    preset_id: int,
    exercise_name: str,
    exercise_type: int,
    sequence_number: int,
    sets_count: int = 0,
) -> int:
    """
    Добавляет упражнение в шаблон тренировки.

    Параметры:
        preset_id: id_preset.
        exercise_name: Название упражнения.
        exercise_type: Тип упражнения (0, 1 или 2).
        sequence_number: Порядок в шаблоне.
        sets_count: Планируемое число подходов, по умолчанию 0.

    Возвращает:
        id_preset_exercise новой записи.
    """
    preset_exercise_id = await _run_query(
        """
        INSERT INTO GTB_preset_exercises
            (id_preset, exercise_name, is_bodyweight, sequence_number, sets_count)
        OUTPUT INSERTED.id_preset_exercise
        VALUES (?, ?, ?, ?, ?)
        """,
        (preset_id, exercise_name, exercise_type, sequence_number, sets_count),
        fetch="scalar",
    )
    return int(preset_exercise_id)


async def update_preset_exercise_sets_count(
    preset_exercise_id: int,
    preset_id: int,
    sets_count: int,
) -> None:
    """
    Обновляет планируемое число подходов упражнения в шаблоне.

    Параметры:
        preset_exercise_id: id_preset_exercise.
        preset_id: id_preset (проверка принадлежности).
        sets_count: Новое значение sets_count.

    Возвращает:
        None.
    """
    await _run_query(
        """
        UPDATE GTB_preset_exercises
        SET sets_count = ?
        WHERE id_preset_exercise = ? AND id_preset = ?
        """,
        (sets_count, preset_exercise_id, preset_id),
    )


async def delete_preset(preset_id: int, user_id: int) -> None:
    """
    Мягко удаляет шаблон тренировки (is_deleted = 1).

    Исторические GTB_workouts не затрагиваются.

    Параметры:
        preset_id: id_preset.
        user_id: Внутренний id_user владельца.

    Возвращает:
        None.
    """
    await _run_query(
        """
        UPDATE GTB_preset_workouts
        SET is_deleted = 1
        WHERE id_preset = ? AND id_user = ? AND is_deleted = 0
        """,
        (preset_id, user_id),
    )


async def get_unique_workout_exercises_ordered(
    workout_id: int,
) -> list[dict[str, Any]]:
    """
    Возвращает уникальные упражнения тренировки в порядке первого появления.

    Параметры:
        workout_id: id_workout.

    Возвращает:
        Список упражнений с полями name, is_bodyweight, first_id.
    """
    rows = await _run_query(
        """
        SELECT
            exercise_name AS name,
            is_bodyweight,
            MIN(id_workout_exercise) AS first_id
        FROM GTB_workout_exercises
        WHERE workout_id = ?
        GROUP BY exercise_name, is_bodyweight
        ORDER BY MIN(id_workout_exercise)
        """,
        (workout_id,),
        fetch="all",
    )
    return [_normalize_exercise_row(row) for row in rows]


async def create_preset_from_workout(
    user_id: int,
    preset_name: str,
    workout_id: int,
) -> int:
    """
    Создаёт шаблон из завершённой тренировки.

    Параметры:
        user_id: Внутренний id_user.
        preset_name: Название нового шаблона.
        workout_id: id_workout-источника.

    Возвращает:
        id_preset созданного шаблона.
    """
    preset_id = await create_preset(user_id, preset_name)
    await copy_workout_exercises_to_preset(preset_id, workout_id)
    return preset_id


async def get_workout_exercises_with_set_counts(
    workout_id: int,
) -> list[dict[str, Any]]:
    """
    Возвращает упражнения тренировки с фактическим числом подходов.

    Порядок - по первому появлению упражнения в сессии.

    Параметры:
        workout_id: id_workout.

    Возвращает:
        Список упражнений с полем performed_sets.
    """
    rows = await _run_query(
        """
        SELECT
            we.exercise_name AS name,
            we.is_bodyweight,
            MIN(we.id_workout_exercise) AS first_id,
            COUNT(s.id_set) AS performed_sets
        FROM GTB_workout_exercises we
        LEFT JOIN GTB_sets s
            ON s.id_workout_exercise = we.id_workout_exercise
        WHERE we.workout_id = ?
        GROUP BY we.exercise_name, we.is_bodyweight
        ORDER BY MIN(we.id_workout_exercise)
        """,
        (workout_id,),
        fetch="all",
    )
    result = []
    for row in rows:
        normalized = _normalize_exercise_row(row)
        normalized["performed_sets"] = int(row.get("performed_sets") or 0)
        result.append(normalized)
    return result


async def copy_workout_exercises_to_preset(
    preset_id: int,
    workout_id: int,
) -> int:
    """
    Копирует упражнения тренировки в шаблон (порядок первого появления).

    Параметры:
        preset_id: id_preset.
        workout_id: id_workout-источника.

    Возвращает:
        Число скопированных упражнений.
    """
    exercises = await get_workout_exercises_with_set_counts(workout_id)
    for seq, exercise in enumerate(exercises, start=1):
        await add_preset_exercise(
            preset_id=preset_id,
            exercise_name=exercise["name"],
            exercise_type=exercise["is_bodyweight"],
            sequence_number=seq,
            sets_count=int(exercise.get("performed_sets") or 0),
        )
    return len(exercises)


async def get_previous_finished_workout_id(
    user_id: int,
    preset_id: int,
    *,
    exclude_workout_id: int | None = None,
) -> int | None:
    """
    Возвращает id последней завершённой тренировки по тому же шаблону.

    Параметры:
        user_id: Внутренний id_user.
        preset_id: id_preset.
        exclude_workout_id: id_workout, который нужно исключить из поиска.

    Возвращает:
        id_workout или None, если предыдущих сессий нет.
    """
    if exclude_workout_id is not None:
        workout_id = await _run_query(
            """
            SELECT TOP 1 id_workout
            FROM GTB_workouts
            WHERE id_user = ?
              AND id_preset = ?
              AND finished_at IS NOT NULL
              AND id_workout <> ?
            ORDER BY finished_at DESC
            """,
            (user_id, preset_id, exclude_workout_id),
            fetch="scalar",
        )
    else:
        workout_id = await _run_query(
            """
            SELECT TOP 1 id_workout
            FROM GTB_workouts
            WHERE id_user = ?
              AND id_preset = ?
              AND finished_at IS NOT NULL
            ORDER BY finished_at DESC
            """,
            (user_id, preset_id),
            fetch="scalar",
        )
    return int(workout_id) if workout_id is not None else None


async def get_previous_workout_detail_for_preset(
    user_id: int,
    preset_id: int,
    *,
    exclude_workout_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Возвращает детали последней завершённой тренировки по шаблону одним SQL-запросом.

    Параметры:
        user_id: Внутренний id_user.
        preset_id: id_preset.
        exclude_workout_id: id_workout для исключения из поиска.

    Возвращает:
        Список строк с упражнениями и подходами или пустой список.
    """
    if exclude_workout_id is not None:
        where_clause = """
            w.id_workout = (
                SELECT TOP 1 id_workout
                FROM GTB_workouts
                WHERE id_user = ?
                  AND id_preset = ?
                  AND finished_at IS NOT NULL
                  AND id_workout <> ?
                ORDER BY finished_at DESC
            )
            AND w.finished_at IS NOT NULL
        """
        params: tuple = (user_id, preset_id, exclude_workout_id)
    else:
        where_clause = """
            w.id_workout = (
                SELECT TOP 1 id_workout
                FROM GTB_workouts
                WHERE id_user = ?
                  AND id_preset = ?
                  AND finished_at IS NOT NULL
                ORDER BY finished_at DESC
            )
            AND w.finished_at IS NOT NULL
        """
        params = (user_id, preset_id)

    rows = await _fetch_workout_detail_rows(
        where_clause,
        params,
        "we.id_workout_exercise, s.set_number",
    )
    return rows


async def get_previous_set_for_exercise(
    user_id: int,
    preset_id: int,
    exercise_name: str,
    exercise_type: int,
    set_number: int,
    *,
    exclude_workout_id: int | None = None,
) -> dict[str, Any] | None:
    """
    Возвращает подход с тем же номером из предыдущей тренировки по шаблону.

    Параметры:
        user_id: Внутренний id_user.
        preset_id: id_preset.
        exercise_name: Название упражнения.
        exercise_type: Тип упражнения (0, 1 или 2).
        set_number: Номер подхода.
        exclude_workout_id: id_workout для исключения из поиска.

    Возвращает:
        Словарь с полями подхода или None, если подход не найден.
    """
    rows = await get_previous_workout_detail_for_preset(
        user_id,
        preset_id,
        exclude_workout_id=exclude_workout_id,
    )
    if not rows:
        return None

    exercise_type = _as_exercise_type(exercise_type)
    for row in rows:
        if row.get("set_number") is None:
            continue
        if (
            row["exercise_name"] == exercise_name
            and _as_exercise_type(row["is_bodyweight"]) == exercise_type
            and int(row["set_number"]) == set_number
        ):
            return {
                "set_number": row["set_number"],
                "weight": row.get("weight"),
                "reps": row.get("reps"),
                "duration_seconds": row.get("duration_seconds"),
                "distance_meters": row.get("distance_meters"),
            }
    return None


async def get_previous_workout_sets_for_exercise(
    user_id: int,
    exercise_name: str,
    exercise_type: int,
    *,
    exclude_workout_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Возвращает подходы упражнения из последней завершённой тренировки пользователя.

    Ищет последнюю тренировку, где выполнялось это упражнение, независимо от шаблона.

    Параметры:
        user_id: Внутренний id_user.
        exercise_name: Название упражнения.
        exercise_type: Тип упражнения (0, 1 или 2).
        exclude_workout_id: id_workout для исключения из поиска.

    Возвращает:
        Строки детализации подходов или пустой список.
    """
    exercise_type = _as_exercise_type(exercise_type)
    exclude_sql = "AND w2.id_workout <> ?" if exclude_workout_id is not None else ""
    params: list[Any] = [user_id, user_id, exercise_name, exercise_type]
    if exclude_workout_id is not None:
        params.append(exclude_workout_id)
    params.extend([exercise_name, exercise_type])

    where_clause = f"""
        w.id_user = ?
        AND w.finished_at IS NOT NULL
        AND w.id_workout = (
            SELECT TOP 1 w2.id_workout
            FROM GTB_workouts w2
            INNER JOIN GTB_workout_exercises we2 ON we2.workout_id = w2.id_workout
            WHERE w2.id_user = ?
              AND w2.finished_at IS NOT NULL
              AND we2.exercise_name = ?
              AND we2.is_bodyweight = ?
              {exclude_sql}
            ORDER BY w2.finished_at DESC
        )
        AND we.exercise_name = ?
        AND we.is_bodyweight = ?
    """
    return await _fetch_workout_detail_rows(
        where_clause,
        tuple(params),
        "we.id_workout_exercise, s.set_number",
    )


async def replace_preset_exercises_from_workout(
    preset_id: int,
    user_id: int,
    workout_id: int,
) -> int:
    """
    Перезаписывает упражнения шаблона списком из завершённой тренировки.

    Параметры:
        preset_id: id_preset.
        user_id: Внутренний id_user владельца шаблона.
        workout_id: id_workout-источника.

    Возвращает:
        Число упражнений, скопированных в шаблон.

    Исключения:
        ValueError: Если шаблон не найден или нет доступа.
    """
    preset = await get_preset_by_id(preset_id)
    if not preset or preset["id_user"] != user_id:
        raise ValueError("Шаблон не найден или нет доступа")

    await _run_query(
        """
        DELETE FROM GTB_preset_exercises
        WHERE id_preset = ?
        """,
        (preset_id,),
    )
    return await copy_workout_exercises_to_preset(preset_id, workout_id)


# --- Тренировки ---


async def create_workout(user_id: int, id_preset: int | None = None) -> int:
    """
    Создаёт новую активную тренировку.

    Параметры:
        user_id: Внутренний id_user.
        id_preset: id_preset или None для свободной тренировки.

    Возвращает:
        id_workout новой записи.
    """
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    workout_id = await _run_query(
        """
        INSERT INTO GTB_workouts (id_user, id_preset, started_at)
        OUTPUT INSERTED.id_workout
        VALUES (?, ?, ?)
        """,
        (user_id, id_preset, started_at),
        fetch="scalar",
    )
    return int(workout_id)


async def add_workout_exercise(
    workout_id: int,
    user_id: int,
    exercise_name: str,
    exercise_type: int,
    category_id: int | None = None,
) -> int:
    """
    Добавляет упражнение в активную тренировку.

    Параметры:
        workout_id: id_workout.
        user_id: Внутренний id_user.
        exercise_name: Название упражнения.
        exercise_type: Тип упражнения (0, 1 или 2).
        category_id: id_category или None.

    Возвращает:
        id_workout_exercise новой записи.
    """
    workout_exercise_id = await _run_query(
        """
        INSERT INTO GTB_workout_exercises
            (workout_id, id_user, exercise_name, is_bodyweight, category_id)
        OUTPUT INSERTED.id_workout_exercise
        VALUES (?, ?, ?, ?, ?)
        """,
        (workout_id, user_id, exercise_name, exercise_type, category_id),
        fetch="scalar",
    )
    return int(workout_exercise_id)


async def add_set(
    workout_exercise_id: int,
    set_number: int,
    *,
    reps: int | None = None,
    weight: float | None = None,
    duration_seconds: int | None = None,
    distance_meters: int | None = None,
) -> int:
    """
    Добавляет подход к упражнению тренировки.

    Параметры:
        workout_exercise_id: id_workout_exercise.
        set_number: Порядковый номер подхода.
        reps: Повторения (для типов с весом и своим весом).
        weight: Вес (кг).
        duration_seconds: Длительность (сек) для упражнений на время.
        distance_meters: Дистанция (м) для упражнений на время.

    Возвращает:
        id_set новой записи.
    """
    set_id = await _run_query(
        """
        INSERT INTO GTB_sets
            (id_workout_exercise, set_number, weight, reps, duration_seconds, distance_meters)
        OUTPUT INSERTED.id_set
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            workout_exercise_id,
            set_number,
            weight,
            reps,
            duration_seconds,
            distance_meters,
        ),
        fetch="scalar",
    )
    return int(set_id)


async def delete_last_set(workout_exercise_id: int) -> int | None:
    """
    Удаляет последний подход упражнения тренировки.

    Параметры:
        workout_exercise_id: id_workout_exercise.

    Возвращает:
        Номер удалённого подхода или None, если подходов не было.
    """
    set_number = await _run_query(
        """
        SELECT TOP 1 set_number
        FROM GTB_sets
        WHERE id_workout_exercise = ?
        ORDER BY set_number DESC, id_set DESC
        """,
        (workout_exercise_id,),
        fetch="scalar",
    )
    if set_number is None:
        return None

    await _run_query(
        """
        DELETE FROM GTB_sets
        WHERE id_workout_exercise = ? AND set_number = ?
        """,
        (workout_exercise_id, int(set_number)),
    )
    return int(set_number)


async def finish_workout(workout_id: int) -> None:
    """
    Завершает тренировку, записывая finished_at.

    finished_at - наивный UTC (datetime.now(timezone.utc) без tzinfo).

    Параметры:
        workout_id: id_workout.

    Возвращает:
        None.
    """
    finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await _run_query(
        """
        UPDATE GTB_workouts
        SET finished_at = ?
        WHERE id_workout = ?
        """,
        (finished_at, workout_id),
    )


async def get_workout_statistics(user_id: int) -> dict[str, Any]:
    """
    Возвращает агрегированную статистику тренировок одним запросом к БД.

    Параметры:
        user_id: Внутренний id_user.

    Возвращает:
        Словарь с workout_count, workout_count_week/month/year и total_weight_lifted_all_time.
    """
    row = await _run_query(
        """
        SELECT
            COUNT(*) AS workout_count_all_time,
            SUM(CASE
                WHEN YEAR(w.finished_at) = YEAR(GETDATE())
                 AND DATEPART(ISO_WEEK, w.finished_at) = DATEPART(ISO_WEEK, GETDATE())
                THEN 1 ELSE 0
            END) AS workout_count_week,
            SUM(CASE
                WHEN YEAR(w.finished_at) = YEAR(GETDATE())
                 AND MONTH(w.finished_at) = MONTH(GETDATE())
                THEN 1 ELSE 0
            END) AS workout_count_month,
            SUM(CASE
                WHEN YEAR(w.finished_at) = YEAR(GETDATE())
                THEN 1 ELSE 0
            END) AS workout_count_year,
            (
                SELECT ISNULL(SUM(s.weight * s.reps), 0)
                FROM GTB_sets s
                INNER JOIN GTB_workout_exercises we
                    ON we.id_workout_exercise = s.id_workout_exercise
                INNER JOIN GTB_workouts w2
                    ON w2.id_workout = we.workout_id
                WHERE w2.id_user = ?
                  AND w2.finished_at IS NOT NULL
                  AND s.weight IS NOT NULL
                  AND s.reps IS NOT NULL
            ) AS total_weight_lifted_all_time
        FROM GTB_workouts w
        WHERE w.id_user = ?
          AND w.finished_at IS NOT NULL
        """,
        (user_id, user_id),
        fetch="one",
    )
    if not row:
        return {
            "workout_count": 0,
            "workout_count_all_time": 0,
            "workout_count_week": 0,
            "workout_count_month": 0,
            "workout_count_year": 0,
            "total_weight_lifted_all_time": 0.0,
        }
    return {
        "workout_count": int(row["workout_count_all_time"]),
        "workout_count_all_time": int(row["workout_count_all_time"]),
        "workout_count_week": int(row["workout_count_week"] or 0),
        "workout_count_month": int(row["workout_count_month"] or 0),
        "workout_count_year": int(row["workout_count_year"] or 0),
        "total_weight_lifted_all_time": float(row["total_weight_lifted_all_time"] or 0),
    }


async def get_user_workout_stats(user_id: int) -> dict[str, Any]:
    """
    Обратная совместимость: только общее число завершённых тренировок.

    Параметры:
        user_id: Внутренний id_user.

    Возвращает:
        Словарь с ключом workout_count.
    """
    stats = await get_workout_statistics(user_id)
    return {"workout_count": stats["workout_count"]}


async def get_last_workouts(user_id: int, limit: int = 5) -> list[dict[str, Any]]:
    """
    Возвращает последние завершённые тренировки пользователя.

    Параметры:
        user_id: Внутренний id_user.
        limit: Максимальное число записей, по умолчанию 5.

    Возвращает:
        Список словарей с полями id, started_at, finished_at.
    """
    return await _run_query(
        """
        SELECT TOP (?) id_workout AS id, started_at, finished_at
        FROM GTB_workouts
        WHERE id_user = ? AND finished_at IS NOT NULL
        ORDER BY finished_at DESC
        """,
        (limit, user_id),
        fetch="all",
    )


# --- Статистика ---


async def get_total_workouts_for_current_month(user_id: int) -> int:
    """
    Возвращает количество завершённых тренировок за текущий календарный месяц.

    Параметры:
        user_id: Внутренний id_user.

    Возвращает:
        Число тренировок за текущий месяц.
    """
    stats = await get_workout_statistics(user_id)
    return int(stats["workout_count_month"])


async def get_workout_days_for_month(user_id: int, year: int, month: int) -> set[int]:
    """
    Возвращает номера дней месяца, в которые были завершённые тренировки.

    Параметры:
        user_id: Внутренний id_user.
        year: Год календаря.
        month: Месяц (1-12).

    Возвращает:
        Множество номеров дней (DAY(started_at)).
    """
    rows = await _run_query(
        """
        SELECT DISTINCT DAY(started_at) AS workout_day
        FROM GTB_workouts
        WHERE id_user = ?
          AND finished_at IS NOT NULL
          AND YEAR(started_at) = ?
          AND MONTH(started_at) = ?
        """,
        (user_id, year, month),
        fetch="all",
    )
    return {int(row["workout_day"]) for row in rows}


async def get_detailed_workouts_by_date(
    user_id: int,
    selected_date: date,
) -> list[dict[str, Any]]:
    """
    Возвращает детализацию тренировок за выбранную дату.

    JOIN GTB_workouts, GTB_workout_exercises и GTB_sets.
    Фильтр по CAST(w.started_at AS DATE).

    Параметры:
        user_id: Внутренний id_user.
        selected_date: Календарная дата.

    Возвращает:
        Список строк с упражнениями и подходами за день.
    """
    return await _fetch_workout_detail_rows(
        "w.id_user = ? AND w.finished_at IS NOT NULL AND CAST(w.started_at AS DATE) = ?",
        (user_id, selected_date),
        "w.started_at, we.id_workout_exercise, s.set_number",
    )


async def get_workout_user_id(workout_id: int) -> int | None:
    """
    Возвращает id_user владельца тренировки.

    Параметры:
        workout_id: id_workout.

    Возвращает:
        id_user или None, если тренировка не найдена.
    """
    user_id = await _run_query(
        """
        SELECT id_user
        FROM GTB_workouts
        WHERE id_workout = ?
        """,
        (workout_id,),
        fetch="scalar",
    )
    return int(user_id) if user_id is not None else None


async def delete_workout(workout_id: int) -> None:
    """
    Удаляет тренировку и все связанные подходы и упражнения сессии.

    Параметры:
        workout_id: id_workout.

    Возвращает:
        None.
    """
    await _run_query(
        """
        DELETE s
        FROM GTB_sets s
        INNER JOIN GTB_workout_exercises we
            ON we.id_workout_exercise = s.id_workout_exercise
        WHERE we.workout_id = ?
        """,
        (workout_id,),
    )
    await _run_query(
        """
        DELETE FROM GTB_workout_exercises
        WHERE workout_id = ?
        """,
        (workout_id,),
    )
    await _run_query(
        """
        DELETE FROM GTB_workouts
        WHERE id_workout = ?
        """,
        (workout_id,),
    )


async def get_set_count(workout_exercise_id: int) -> int:
    """
    Возвращает количество подходов в упражнении тренировки.

    Параметры:
        workout_exercise_id: id_workout_exercise.

    Возвращает:
        Число записей в GTB_sets.
    """
    count = await _run_query(
        """
        SELECT COUNT(*) AS cnt
        FROM GTB_sets
        WHERE id_workout_exercise = ?
        """,
        (workout_exercise_id,),
        fetch="scalar",
    )
    return int(count or 0)


async def get_set_by_number(
    workout_exercise_id: int,
    set_number: int,
) -> dict[str, Any] | None:
    """
    Возвращает подход по номеру внутри упражнения тренировки.

    Параметры:
        workout_exercise_id: id_workout_exercise.
        set_number: Номер подхода.

    Возвращает:
        Словарь с полями id, set_number, weight, reps, duration_seconds, distance_meters или None.
    """
    return await _run_query(
        """
        SELECT id_set AS id, set_number, weight, reps, duration_seconds, distance_meters
        FROM GTB_sets
        WHERE id_workout_exercise = ? AND set_number = ?
        """,
        (workout_exercise_id, set_number),
        fetch="one",
    )


async def update_set(
    set_id: int,
    *,
    reps: int | None = None,
    weight: float | None = None,
    duration_seconds: int | None = None,
    distance_meters: int | None = None,
) -> None:
    """
    Обновляет поля подхода.

    Параметры:
        set_id: id_set.
        reps: Повторения.
        weight: Вес (кг).
        duration_seconds: Длительность (сек).
        distance_meters: Дистанция (м).

    Возвращает:
        None.
    """
    await _run_query(
        """
        UPDATE GTB_sets
        SET weight = ?, reps = ?, duration_seconds = ?, distance_meters = ?
        WHERE id_set = ?
        """,
        (weight, reps, duration_seconds, distance_meters, set_id),
    )


async def get_workout_detail_by_id(workout_id: int) -> list[dict[str, Any]]:
    """
    Возвращает детальную информацию о конкретной завершённой тренировке.

    Параметры:
        workout_id: id_workout.

    Возвращает:
        Список строк с упражнениями и подходами.
    """
    return await _fetch_workout_detail_rows(
        "w.id_workout = ? AND w.finished_at IS NOT NULL",
        (workout_id,),
        "we.id_workout_exercise, s.set_number",
    )
