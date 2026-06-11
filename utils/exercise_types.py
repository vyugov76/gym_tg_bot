"""
exercise_types - типы упражнений и связанные константы

Определяет числовые коды типов упражнений (поле is_bodyweight в БД),
иконки, подписи для интерфейса и функции переключения типа.

Ключевые компоненты:
- EXERCISE_WEIGHTED, EXERCISE_BODYWEIGHT, EXERCISE_TIMED - коды типов
- EXERCISE_ICONS, EXERCISE_TYPE_LABELS, NEXT_TYPE_BUTTON - подписи UI
- normalize_exercise_type - приведение значения из БД к допустимому типу
- next_exercise_type - циклическое переключение типа
"""

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
    """
    Приводит значение типа упражнения из БД к целому 0, 1 или 2.

    Параметры:
        value: значение is_bodyweight из БД или None

    Возвращает:
        EXERCISE_WEIGHTED (0), если value равен None; иначе int(value)
    """
    if value is None:
        return EXERCISE_WEIGHTED
    return int(value)


def next_exercise_type(current: int) -> int:
    """
    Возвращает следующий тип упражнения по циклу 0 - 1 - 2 - 0.

    Параметры:
        current: текущий тип упражнения

    Возвращает:
        Следующий тип после нормализации current
    """
    return (normalize_exercise_type(current) + 1) % 3
