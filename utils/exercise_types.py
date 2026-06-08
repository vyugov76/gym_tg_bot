"""Константы и подписи типов упражнений (is_bodyweight: 0, 1, 2)."""

from __future__ import annotations

EXERCISE_WEIGHTED = 0
EXERCISE_BODYWEIGHT = 1
EXERCISE_TIMED = 2

EXERCISE_ICONS: dict[int, str] = {
    EXERCISE_WEIGHTED: "🏋️‍♂️",
    EXERCISE_BODYWEIGHT: "🤸‍♂️",
    EXERCISE_TIMED: "⏱️",
}

EXERCISE_TYPE_LABELS: dict[int, str] = {
    EXERCISE_WEIGHTED: "с отягощением",
    EXERCISE_BODYWEIGHT: "собственный вес",
    EXERCISE_TIMED: "на время",
}

NEXT_TYPE_BUTTON: dict[int, str] = {
    EXERCISE_WEIGHTED: "🤸‍♂️ Сделать с собственным весом",
    EXERCISE_BODYWEIGHT: "⏱️ Сделать на время",
    EXERCISE_TIMED: "🏋️‍♂️ Сделать с отягощением",
}


def normalize_exercise_type(value: int | bool | None) -> int:
    """Приводит значение из БД к типу 0, 1 или 2."""
    if value is None:
        return EXERCISE_WEIGHTED
    return int(value)


def next_exercise_type(current: int) -> int:
    """Циклическое переключение типа: 0 → 1 → 2 → 0."""
    return (normalize_exercise_type(current) + 1) % 3
