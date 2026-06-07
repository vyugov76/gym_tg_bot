"""Запросы к базе данных: пользователи, тренировки, упражнения, подходы."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from database.connection import get_pool


async def _fetch_one_dict(cur) -> dict[str, Any] | None:
    """Преобразует одну строку результата в словарь {имя_столбца: значение}."""
    row = await cur.fetchone()
    if row is None:
        return None
    columns = [col[0] for col in cur.description]
    return dict(zip(columns, row, strict=False))


async def _fetch_all_dicts(cur) -> list[dict[str, Any]]:
    """Преобразует все строки результата в список словарей."""
    rows = await cur.fetchall()
    columns = [col[0] for col in cur.description]
    return [dict(zip(columns, row, strict=False)) for row in rows]


async def get_user_by_telegram_id(telegram_id: int) -> dict[str, Any] | None:
    """Возвращает пользователя по Telegram ID или None, если не найден."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id_user AS id, telegram_id, height, weight, created_at
                FROM GTB_users
                WHERE telegram_id = ?
                """,
                (telegram_id,),
            )
            return await _fetch_one_dict(cur)


async def add_user(telegram_id: int, height: float, weight: float) -> int:
    """Регистрирует нового пользователя. Возвращает id записи."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO GTB_users (telegram_id, height, weight)
                OUTPUT INSERTED.id_user
                VALUES (?, ?, ?)
                """,
                (telegram_id, height, weight),
            )
            row = await cur.fetchone()
            return int(row[0])


async def create_workout(user_id: int) -> int:
    """Создаёт новую тренировку. Возвращает id записи."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO GTB_workouts (user_id)
                OUTPUT INSERTED.id_workout
                VALUES (?)
                """,
                (user_id,),
            )
            row = await cur.fetchone()
            return int(row[0])


async def add_workout_exercise(workout_id: int, category: str, exercise_name: str) -> int:
    """Добавляет упражнение в тренировку. Возвращает id записи."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO GTB_workout_exercises (workout_id, category, exercise_name)
                OUTPUT INSERTED.id_workout_exercise
                VALUES (?, ?, ?)
                """,
                (workout_id, category, exercise_name),
            )
            row = await cur.fetchone()
            return int(row[0])


async def add_set(workout_exercise_id: int, set_number: int, weight: float, reps: int) -> int:
    """Записывает подход. Возвращает id записи."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO GTB_sets (workout_exercise_id, set_number, weight, reps)
                OUTPUT INSERTED.id_set
                VALUES (?, ?, ?, ?)
                """,
                (workout_exercise_id, set_number, weight, reps),
            )
            row = await cur.fetchone()
            return int(row[0])


async def calculate_workout_tonnage(workout_id: int) -> float:
    """Считает суммарный тоннаж тренировки: Σ(вес × повторения) по всем подходам."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COALESCE(SUM(s.weight * s.reps), 0)
                FROM GTB_sets s
                INNER JOIN GTB_workout_exercises we
                    ON we.id_workout_exercise = s.workout_exercise_id
                WHERE we.workout_id = ?
                """,
                (workout_id,),
            )
            row = await cur.fetchone()
            return float(row[0])


async def finish_workout(workout_id: int, total_tonnage: float) -> None:
    """Завершает тренировку и сохраняет итоговый тоннаж."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE GTB_workouts
                SET finished_at = ?, total_tonnage = ?
                WHERE id_workout = ?
                """,
                (datetime.now(), total_tonnage, workout_id),
            )


async def get_user_workout_stats(user_id: int) -> dict[str, Any]:
    """Статистика пользователя: число тренировок и суммарный тоннаж."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    COUNT(*) AS workout_count,
                    COALESCE(SUM(total_tonnage), 0) AS total_tonnage
                FROM GTB_workouts
                WHERE user_id = ? AND finished_at IS NOT NULL
                """,
                (user_id,),
            )
            row = await cur.fetchone()
            return {
                "workout_count": int(row[0]),
                "total_tonnage": float(row[1]),
            }


async def get_last_workouts(user_id: int, limit: int = 5) -> list[dict[str, Any]]:
    """Последние завершённые тренировки пользователя."""
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT TOP (?) id_workout AS id, started_at, finished_at, total_tonnage
                FROM GTB_workouts
                WHERE user_id = ? AND finished_at IS NOT NULL
                ORDER BY finished_at DESC
                """,
                (limit, user_id),
            )
            return await _fetch_all_dicts(cur)
