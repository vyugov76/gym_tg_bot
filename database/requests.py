"""Запросы к базе данных: пользователи, упражнения, тренировки, подходы."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Literal

from database.connection import get_pool

logger = logging.getLogger(__name__)

FetchMode = Literal["one", "all", "scalar", "none"]


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


async def _run_query(
    sql: str,
    params: tuple = (),
    fetch: FetchMode = "none",
) -> Any:
    """Выполняет SQL-запрос с логированием и обработкой ошибок."""
    try:
        logger.info(f"Выполнение SQL: {sql.strip()} с параметрами: {params}")
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                if fetch == "one":
                    return await _fetch_one_dict(cur)
                if fetch == "all":
                    return await _fetch_all_dicts(cur)
                if fetch == "scalar":
                    row = await cur.fetchone()
                    return row[0] if row else None
        return None
    except Exception:
        logger.exception("Ошибка при работе с БД")
        raise


def _as_bool(value: Any) -> bool:
    return bool(value)


def _normalize_exercise_row(row: dict[str, Any]) -> dict[str, Any]:
    row["is_bodyweight"] = _as_bool(row["is_bodyweight"])
    return row


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


# --- Упражнения (история из GTB_workout_exercises) ---


async def get_exercises_by_user_id(user_id: int) -> list[dict[str, Any]]:
    rows = await _run_query(
        """
        SELECT
            MAX(id_workout_exercise) AS id,
            exercise_name AS name,
            is_bodyweight
        FROM GTB_workout_exercises
        WHERE user_id = ?
        GROUP BY exercise_name, is_bodyweight
        ORDER BY name
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
            user_id,
            exercise_name AS name,
            is_bodyweight
        FROM GTB_workout_exercises
        WHERE id_workout_exercise = ?
        """,
        (exercise_id,),
        fetch="one",
    )
    return _normalize_exercise_row(row) if row else None


async def update_exercise_name(exercise_id: int, new_name: str) -> None:
    exercise = await get_exercise_by_id(exercise_id)
    if not exercise:
        return
    await _run_query(
        """
        UPDATE GTB_workout_exercises
        SET exercise_name = ?
        WHERE user_id = ? AND exercise_name = ? AND is_bodyweight = ?
        """,
        (new_name, exercise["user_id"], exercise["name"], int(exercise["is_bodyweight"])),
    )


async def toggle_exercise_bodyweight(exercise_id: int) -> bool:
    exercise = await get_exercise_by_id(exercise_id)
    if not exercise:
        return False
    new_value = not exercise["is_bodyweight"]
    await _run_query(
        """
        UPDATE GTB_workout_exercises
        SET is_bodyweight = ?
        WHERE user_id = ? AND exercise_name = ? AND is_bodyweight = ?
        """,
        (int(new_value), exercise["user_id"], exercise["name"], int(exercise["is_bodyweight"])),
    )
    return new_value


# --- Тренировки ---


async def create_workout(user_id: int) -> int:
    workout_id = await _run_query(
        """
        INSERT INTO GTB_workouts (user_id)
        OUTPUT INSERTED.id_workout
        VALUES (?)
        """,
        (user_id,),
        fetch="scalar",
    )
    return int(workout_id)


async def add_workout_exercise(
    workout_id: int,
    user_id: int,
    exercise_name: str,
    is_bodyweight: bool,
) -> int:
    workout_exercise_id = await _run_query(
        """
        INSERT INTO GTB_workout_exercises
            (workout_id, user_id, exercise_name, is_bodyweight)
        OUTPUT INSERTED.id_workout_exercise
        VALUES (?, ?, ?, ?)
        """,
        (workout_id, user_id, exercise_name, int(is_bodyweight)),
        fetch="scalar",
    )
    return int(workout_exercise_id)


async def add_set(
    workout_exercise_id: int,
    set_number: int,
    reps: int,
    weight: float | None = None,
) -> int:
    set_id = await _run_query(
        """
        INSERT INTO GTB_sets (workout_exercise_id, set_number, weight, reps)
        OUTPUT INSERTED.id_set
        VALUES (?, ?, ?, ?)
        """,
        (workout_exercise_id, set_number, weight, reps),
        fetch="scalar",
    )
    return int(set_id)


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
        WHERE user_id = ? AND finished_at IS NOT NULL
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
        WHERE user_id = ? AND finished_at IS NOT NULL
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
        WHERE user_id = ?
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
        WHERE user_id = ?
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
        """
        SELECT
            w.id_workout,
            w.started_at,
            w.finished_at,
            we.id_workout_exercise,
            we.exercise_name,
            we.is_bodyweight,
            s.set_number,
            s.weight,
            s.reps
        FROM GTB_workouts w
        INNER JOIN GTB_workout_exercises we
            ON we.workout_id = w.id_workout
        LEFT JOIN GTB_sets s
            ON s.workout_exercise_id = we.id_workout_exercise
        WHERE w.user_id = ?
          AND w.finished_at IS NOT NULL
          AND CAST(w.started_at AS DATE) = ?
        ORDER BY w.started_at, we.id_workout_exercise, s.set_number
        """,
        (user_id, selected_date),
        fetch="all",
    )
    return _normalize_workout_detail_rows(rows)


async def get_workout_detail_by_id(workout_id: int) -> list[dict[str, Any]]:
    """Детальная информация о конкретной завершённой тренировке."""
    rows = await _run_query(
        """
        SELECT
            w.id_workout,
            w.started_at,
            w.finished_at,
            we.id_workout_exercise,
            we.exercise_name,
            we.is_bodyweight,
            s.set_number,
            s.weight,
            s.reps
        FROM GTB_workouts w
        INNER JOIN GTB_workout_exercises we
            ON we.workout_id = w.id_workout
        LEFT JOIN GTB_sets s
            ON s.workout_exercise_id = we.id_workout_exercise
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
        row["is_bodyweight"] = _as_bool(row["is_bodyweight"])
    return rows
