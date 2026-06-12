"""
workout_progress - сравнение подходов с предыдущей тренировкой

Определяет прогресс или регресс относительно прошлого выполнения
упражнения по тому же шаблону и форматирует значения подходов.

Ключевые компоненты:
- compare_set_progress - эмодзи-индикатор прогресса подхода (🟢 / 🔴)
- format_set_value_for_display - текстовое значение подхода по типу
- build_previous_sets_map - индекс подходов предыдущей тренировки
"""

from __future__ import annotations

from utils.exercise_types import (
    EXERCISE_BODYWEIGHT,
    EXERCISE_TIMED,
    EXERCISE_WEIGHTED,
    normalize_exercise_type,
)
from utils.text_helpers import format_exercise_time


def _format_weight(value: float | None) -> str:
    """
    Форматирует вес без лишних нулей после запятой.

    Параметры:
        value: вес в килограммах или None

    Возвращает:
        Строку с весом или пустую строку
    """
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(value).rstrip("0").rstrip(".")


def _set_duration_seconds(set_row: dict) -> int:
    """
    Извлекает длительность подхода в секундах из записи БД.

    Параметры:
        set_row: словарь подхода с полями duration_seconds или reps (legacy)

    Возвращает:
        Число секунд; 0, если поля отсутствуют
    """
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
    Сравнивает текущий подход с аналогичным из предыдущей тренировки.

    Бинарная схема: 🟢 прогресс, 🔴 регресс, без маркера - без изменений
    или нет данных для сравнения.

    Параметры:
        current: словарь текущего подхода
        previous: словарь предыдущего подхода или None
        exercise_type: тип упражнения (0 - отягощение, 1 - вес, 2 - время)

    Возвращает:
        Префикс-эмодзи с пробелом или пустую строку
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
        weight_up = cw > pw
        weight_down = cw < pw
        reps_up = cr > pr
        reps_down = cr < pr
        if (weight_up and reps_down) or (weight_down and reps_up):
            return ""
        if weight_up or reps_up:
            return "🟢 "
        if weight_down or reps_down:
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
    """
    Форматирует значение одного подхода для отображения в отчёте.

    Параметры:
        set_row: словарь подхода из БД
        exercise_type: тип упражнения (0, 1 или 2)

    Возвращает:
        Строку «80/10», «12 повт.», «1мин. 30сек.» или пустую строку
    """
    exercise_type = normalize_exercise_type(exercise_type)
    if exercise_type == EXERCISE_BODYWEIGHT:
        return f"{set_row['reps']} повт."
    if exercise_type == EXERCISE_TIMED:
        return format_exercise_time(_set_duration_seconds(set_row))
    if set_row.get("reps") is not None:
        return f"{_format_weight(set_row['weight'])}/{set_row['reps']}"
    return ""


def build_previous_sets_map(rows: list[dict]) -> dict[tuple[str, int, int], dict]:
    """
    Строит индекс подходов предыдущей тренировки для быстрого сравнения.

    Параметры:
        rows: плоские строки тренировки из БД

    Возвращает:
        Словарь с ключом (exercise_name, exercise_type, set_number)
    """
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
