"""Запросы к базе данных: пользователи, упражнения, тренировки, подходы."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, Literal

import pyodbc

from database.connection import discard_connection, get_pool, refresh_db_pool

logger = logging.getLogger(__name__)

FetchMode = Literal["one", "all", "scalar", "none"]
MAX_QUERY_ATTEMPTS = 3
RETRY_DELAY_SEC = 0.5

_CONNECTION_ERROR_CODES = frozenset({"08S01", "HYT00", "HYT01", "01000"})


async def _fetch_one_dict(cur) -> dict[str, Any] | None:
    row = await cur.fetchone()
    if row is None:
        return None
    columns = [col[0] for col in cur.description]
    return dict(zip(columns, row, strict=False))


async def _fetch_all_dicts(cur) -> list[dict[str, Any]]:
    rows = await cur.fetchall()
    columns = [col[0] for col in cur.description]
    return [dict(zip(columns, row, strict=False)) for row in rows]


def _error_text(exc: BaseException) -> str:
    return str(exc).lower()


def _is_dead_connection_error(exc: BaseException) -> bool:
    """Обрыв TCP / протухшее соединение из пула (10054, 08S01, closed connection)."""
    if isinstance(exc, (pyodbc.OperationalError, pyodbc.InterfaceError)):
        return True

    if isinstance(exc, pyodbc.ProgrammingError):
        text = _error_text(exc)
        if "connection has been closed" in text or "closed connection" in text:
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
    if fetch == "one":
        return await _fetch_one_dict(cur)
    if fetch == "all":
        return await _fetch_all_dicts(cur)
    if fetch == "scalar":
        row = await cur.fetchone()
        return row[0] if row else None
    return None


async def _execute_query(
    sql: str,
    params: tuple,
    fetch: FetchMode,
) -> Any:
    """Одна попытка: acquire → execute → release (или discard при обрыве)."""
    pool = get_pool()
    conn = await pool.acquire()
    try:
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await _read_fetch_result(cur, fetch)
    except Exception as exc:
        if _is_dead_connection_error(exc):
            logger.warning(
                "Протухшее соединение из пула, закрываем: %s",
                exc,
            )
            await discard_connection(conn)
            conn = None
        raise
    finally:
        if conn is not None:
            await pool.release(conn)


async def _run_query(
    sql: str,
    params: tuple = (),
    fetch: FetchMode = "none",
) -> Any:
    """Выполняет SQL с повторами при обрыве соединения (до 3 попыток)."""
    last_error: BaseException | None = None

    for attempt in range(1, MAX_QUERY_ATTEMPTS + 1):
        try:
            logger.info(
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
    """Тип упражнения: 0 — с весом, 1 — своий вес, 2 — на время."""
    return int(value) if value is not None else 0


def _normalize_exercise_row(row: dict[str, Any]) -> dict[str, Any]:
    row["is_bodyweight"] = _as_exercise_type(row["is_bodyweight"])
    row["exercise_type"] = row["is_bodyweight"]
    return row


# Фильтр каталога: свои + админские, без удалённых
_CATALOG_WHERE = """
    (id_user = ? OR id_user IS NULL)
    AND workout_id IS NULL
    AND is_deleted = 0
"""

_SET_DETAIL_COLUMNS = """
    s.set_number,
    s.weight,
    s.reps,
    s.duration_seconds,
    s.distance_meters
"""


# --- Пользователи ---


async def get_user_by_telegram_id(telegram_id: int) -> dict[str, Any] | None:
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
    await _run_query(
        """
        UPDATE GTB_users
        SET height = ?
        WHERE id_user = ?
        """,
        (height, user_id),
    )


async def update_user_weight(user_id: int, weight: float) -> None:
    await _run_query(
        """
        UPDATE GTB_users
        SET weight = ?
        WHERE id_user = ?
        """,
        (weight, user_id),
    )


async def add_user(telegram_id: int, height: float, weight: float) -> int:
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
    """Назначает несортированные упражнения в категорию. Возвращает число обновлённых строк."""
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
    return len(exercise_ids)


async def bulk_unassign_exercises_from_category(
    exercise_ids: list[int],
    category_id: int,
    id_user: int,
) -> int:
    """Сбрасывает category_id в NULL для упражнений категории."""
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
    return len(exercise_ids)


async def delete_category(category_id: int, user_id: int) -> None:
    """Удаляет категорию. Упражнения получают category_id = NULL (ON DELETE SET NULL)."""
    await _run_query(
        """
        DELETE FROM GTB_categories
        WHERE id_category = ? AND id_user = ?
        """,
        (category_id, user_id),
    )


# --- Глобальный каталог упражнений (workout_id IS NULL) ---


async def get_global_exercises_by_user_id(user_id: int) -> list[dict[str, Any]]:
    rows = await _run_query(
        f"""
        SELECT
            id_workout_exercise AS id,
            exercise_name AS name,
            is_bodyweight,
            category_id,
            id_user
        FROM GTB_workout_exercises
        WHERE {_CATALOG_WHERE}
        ORDER BY exercise_name
        """,
        (user_id,),
        fetch="all",
    )
    return [_normalize_exercise_row(row) for row in rows]


async def get_exercises_by_category(
    user_id: int,
    category_id: int,
) -> list[dict[str, Any]]:
    rows = await _run_query(
        """
        SELECT
            id_workout_exercise AS id,
            exercise_name AS name,
            is_bodyweight,
            category_id,
            id_user
        FROM GTB_workout_exercises
        WHERE (id_user = ? OR id_user IS NULL)
          AND workout_id IS NULL
          AND is_deleted = 0
          AND category_id = ?
        ORDER BY exercise_name
        """,
        (user_id, category_id),
        fetch="all",
    )
    return [_normalize_exercise_row(row) for row in rows]


async def get_unsorted_exercises(user_id: int) -> list[dict[str, Any]]:
    rows = await _run_query(
        f"""
        SELECT
            id_workout_exercise AS id,
            exercise_name AS name,
            is_bodyweight,
            category_id,
            id_user
        FROM GTB_workout_exercises
        WHERE {_CATALOG_WHERE}
          AND category_id IS NULL
        ORDER BY exercise_name
        """,
        (user_id,),
        fetch="all",
    )
    return [_normalize_exercise_row(row) for row in rows]


async def get_exercise_by_id(exercise_id: int) -> dict[str, Any] | None:
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


async def add_global_exercise(
    user_id: int,
    exercise_name: str,
    exercise_type: int,
    category_id: int | None = None,
) -> int:
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
    return int(exercise_id)


async def update_exercise_name(exercise_id: int, new_name: str) -> None:
    await _run_query(
        """
        UPDATE GTB_workout_exercises
        SET exercise_name = ?
        WHERE id_workout_exercise = ? AND workout_id IS NULL
          AND id_user IS NOT NULL AND is_deleted = 0
        """,
        (new_name, exercise_id),
    )


async def soft_delete_global_exercise(exercise_id: int, id_user: int) -> bool:
    """Мягкое удаление упражнения из каталога пользователя."""
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
    return True


async def cycle_exercise_type(exercise_id: int) -> int:
    """Переключает тип глобального упражнения по циклу 0 → 1 → 2 → 0."""
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
    return new_value


# Обратная совместимость: старое имя функции
async def get_exercises_by_user_id(user_id: int) -> list[dict[str, Any]]:
    return await get_global_exercises_by_user_id(user_id)


# --- Пресеты (готовые тренировки) ---


async def get_presets_by_user_id(user_id: int) -> list[dict[str, Any]]:
    return await _run_query(
        """
        SELECT id_preset AS id, preset_name AS name
        FROM GTB_preset_workouts
        WHERE id_user = ? AND is_deleted = 0
        ORDER BY preset_name
        """,
        (user_id,),
        fetch="all",
    )


async def get_preset_by_id(preset_id: int) -> dict[str, Any] | None:
    return await _run_query(
        """
        SELECT id_preset AS id, id_user, preset_name AS name
        FROM GTB_preset_workouts
        WHERE id_preset = ? AND is_deleted = 0
        """,
        (preset_id,),
        fetch="one",
    )


async def get_preset_exercises(preset_id: int) -> list[dict[str, Any]]:
    rows = await _run_query(
        """
        SELECT
            id_preset_exercise AS id,
            exercise_name AS name,
            is_bodyweight,
            sequence_number
        FROM GTB_preset_exercises
        WHERE id_preset = ?
        ORDER BY sequence_number, id_preset_exercise
        """,
        (preset_id,),
        fetch="all",
    )
    return [_normalize_exercise_row(row) for row in rows]


async def create_preset(user_id: int, preset_name: str) -> int:
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
    """Максимальный sequence_number в шаблоне (0 если пусто)."""
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
    """Добавляет глобальные упражнения в шаблон. Возвращает число добавленных."""
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
        )
        added += 1
    return added


async def bulk_delete_preset_exercises(
    preset_exercise_ids: list[int],
    preset_id: int,
    id_user: int,
) -> int:
    """Удаляет упражнения из шаблона. Возвращает число переданных ID."""
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
) -> int:
    preset_exercise_id = await _run_query(
        """
        INSERT INTO GTB_preset_exercises
            (id_preset, exercise_name, is_bodyweight, sequence_number)
        OUTPUT INSERTED.id_preset_exercise
        VALUES (?, ?, ?, ?)
        """,
        (preset_id, exercise_name, exercise_type, sequence_number),
        fetch="scalar",
    )
    return int(preset_exercise_id)


async def delete_preset(preset_id: int, user_id: int) -> None:
    """Мягкое удаление шаблона. Исторические GTB_workouts не затрагиваются."""
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
    """Уникальные упражнения тренировки в порядке первого появления."""
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
    preset_id = await create_preset(user_id, preset_name)
    await copy_workout_exercises_to_preset(preset_id, workout_id)
    return preset_id


async def copy_workout_exercises_to_preset(
    preset_id: int,
    workout_id: int,
) -> int:
    """Копирует упражнения тренировки в шаблон (порядок первого появления)."""
    exercises = await get_unique_workout_exercises_ordered(workout_id)
    for seq, exercise in enumerate(exercises, start=1):
        await add_preset_exercise(
            preset_id=preset_id,
            exercise_name=exercise["name"],
            exercise_type=exercise["is_bodyweight"],
            sequence_number=seq,
        )
    return len(exercises)


async def replace_preset_exercises_from_workout(
    preset_id: int,
    user_id: int,
    workout_id: int,
) -> int:
    """Перезаписывает упражнения шаблона списком из завершённой тренировки."""
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
    workout_id = await _run_query(
        """
        INSERT INTO GTB_workouts (id_user, id_preset)
        OUTPUT INSERTED.id_workout
        VALUES (?, ?)
        """,
        (user_id, id_preset),
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
    """Удаляет последний подход упражнения. Возвращает номер удалённого подхода."""
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
    """Завершает тренировку. finished_at ставится на стороне SQL Server (SYSDATETIME)."""
    await _run_query(
        """
        UPDATE GTB_workouts
        SET finished_at = SYSDATETIME()
        WHERE id_workout = ?
        """,
        (workout_id,),
    )


async def get_user_workout_stats(user_id: int) -> dict[str, Any]:
    row = await _run_query(
        """
        SELECT COUNT(*) AS workout_count
        FROM GTB_workouts
        WHERE id_user = ? AND finished_at IS NOT NULL
        """,
        (user_id,),
        fetch="one",
    )
    return {"workout_count": int(row["workout_count"])}


async def get_last_workouts(user_id: int, limit: int = 5) -> list[dict[str, Any]]:
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
    """Количество завершённых тренировок за текущий календарный месяц."""
    count = await _run_query(
        """
        SELECT COUNT(*) AS total
        FROM GTB_workouts
        WHERE id_user = ?
          AND finished_at IS NOT NULL
          AND YEAR(finished_at) = YEAR(GETDATE())
          AND MONTH(finished_at) = MONTH(GETDATE())
        """,
        (user_id,),
        fetch="scalar",
    )
    return int(count or 0)


async def get_workout_days_for_month(user_id: int, year: int, month: int) -> set[int]:
    """Множество номеров дней месяца, в которые были завершённые тренировки."""
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
    JOIN GTB_workouts, GTB_workout_exercises и GTB_sets за выбранную дату.
    Фильтр по CAST(w.started_at AS DATE). user_id — внутренний id_user.
    """
    rows = await _run_query(
        f"""
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
        WHERE w.id_user = ?
          AND w.finished_at IS NOT NULL
          AND CAST(w.started_at AS DATE) = ?
        ORDER BY w.started_at, we.id_workout_exercise, s.set_number
        """,
        (user_id, selected_date),
        fetch="all",
    )
    return _normalize_workout_detail_rows(rows)


async def get_workout_user_id(workout_id: int) -> int | None:
    """Возвращает id_user владельца тренировки или None."""
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
    """Удаляет тренировку и все связанные подходы/упражнения сессии."""
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
    """Количество подходов в упражнении тренировки."""
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
    """Возвращает подход по номеру внутри упражнения."""
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
    """Обновляет поля подхода."""
    await _run_query(
        """
        UPDATE GTB_sets
        SET weight = ?, reps = ?, duration_seconds = ?, distance_meters = ?
        WHERE id_set = ?
        """,
        (weight, reps, duration_seconds, distance_meters, set_id),
    )


async def get_workout_detail_by_id(workout_id: int) -> list[dict[str, Any]]:
    """Детальная информация о конкретной завершённой тренировке."""
    rows = await _run_query(
        f"""
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
        WHERE w.id_workout = ?
          AND w.finished_at IS NOT NULL
        ORDER BY we.id_workout_exercise, s.set_number
        """,
        (workout_id,),
        fetch="all",
    )
    return _normalize_workout_detail_rows(rows)


def _normalize_workout_detail_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for row in rows:
        row["is_bodyweight"] = _as_exercise_type(row["is_bodyweight"])
        row["exercise_type"] = row["is_bodyweight"]
    return rows
