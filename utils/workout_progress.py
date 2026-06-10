"""Сравнение подходов с предыдущей тренировкой по шаблону."""

from __future__ import annotations

from utils.exercise_types import (
    EXERCISE_BODYWEIGHT,
    EXERCISE_TIMED,
    EXERCISE_WEIGHTED,
    normalize_exercise_type,
)
from utils.text_helpers import format_exercise_time


def _format_weight(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(value).rstrip("0").rstrip(".")


def _set_duration_seconds(set_row: dict) -> int:
    if set_row.get("duration_seconds") is not None:
        return int(set_row["duration_seconds"])
    if set_row.get("reps") is not None:
        return int(set_row["reps"])
    return 0


def compare_set_progress(
    current: dict,
    previous: dict | None,
    exercise_type: int,
) -> str:
    """
    Возвращает эмодзи-индикатор: 🟢 прогресс, 🔴 регресс, ⚪ без выделения.
    """
    if previous is None:
        return ""

    exercise_type = normalize_exercise_type(exercise_type)

    if exercise_type == EXERCISE_WEIGHTED:
        cw, cr = current.get("weight"), current.get("reps")
        pw, pr = previous.get("weight"), previous.get("reps")
        if cw is None or cr is None or pw is None or pr is None:
            return ""
        cw, cr, pw, pr = float(cw), int(cr), float(pw), int(pr)
        if cw == pw and cr == pr:
            return ""
        if cw > pw and cr > pr:
            return "🟢 "
        if cw < pw and cr < pr:
            return "🔴 "
        if cw > pw and cr == pr:
            return "🟢 "
        if cw == pw and cr > pr:
            return "🟢 "
        if cw < pw and cr == pr:
            return "🔴 "
        if cw == pw and cr < pr:
            return "🔴 "
        return ""

    if exercise_type == EXERCISE_BODYWEIGHT:
        cr, pr = current.get("reps"), previous.get("reps")
        if cr is None or pr is None:
            return ""
        cr, pr = int(cr), int(pr)
        if cr == pr:
            return ""
        if cr > pr:
            return "🟢 "
        if cr < pr:
            return "🔴 "
        return ""

    if exercise_type == EXERCISE_TIMED:
        cd = _set_duration_seconds(current)
        pd = _set_duration_seconds(previous)
        if cd == pd:
            return ""
        if cd > pd:
            return "🟢 "
        if cd < pd:
            return "🔴 "
        return ""

    return ""


def format_set_value_for_display(set_row: dict, exercise_type: int) -> str:
    exercise_type = normalize_exercise_type(exercise_type)
    if exercise_type == EXERCISE_BODYWEIGHT:
        return f"{set_row['reps']} повт."
    if exercise_type == EXERCISE_TIMED:
        return format_exercise_time(_set_duration_seconds(set_row))
    if set_row.get("reps") is not None:
        return f"{_format_weight(set_row['weight'])}/{set_row['reps']}"
    return ""


def build_previous_sets_map(rows: list[dict]) -> dict[tuple[str, int, int], dict]:
    """Ключ: (exercise_name, exercise_type, set_number)."""
    result: dict[tuple[str, int, int], dict] = {}
    for row in rows:
        if row.get("set_number") is None:
            continue
        key = (
            row["exercise_name"],
            normalize_exercise_type(row["is_bodyweight"]),
            int(row["set_number"]),
        )
        result[key] = row
    return result
