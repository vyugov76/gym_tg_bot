"""
set_input - парсинг ввода подходов

Регулярные выражения и функции разбора пользовательского ввода для
упражнений с отягощением, с собственным весом и на время.

Ключевые компоненты:
- SET_INPUT_PATTERN, REPS_ONLY_PATTERN, TIME_INPUT_PATTERN - шаблоны ввода
- INVALID_WEIGHTED_MSG, INVALID_REPS_MSG, INVALID_TIME_MSG - сообщения об ошибках
- parse_weighted_set, parse_bodyweight_reps, parse_time_input - парсеры
"""

from __future__ import annotations

import re

SET_INPUT_PATTERN = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*/\s*(\d+)\s*$")
REPS_ONLY_PATTERN = re.compile(r"^\s*(\d+)\s*$")
TIME_INPUT_PATTERN = re.compile(r"^\s*(\d+)(?::(\d+))?\s*$")

INVALID_WEIGHTED_MSG = (
    "Некорректный формат. Пожалуйста, введите данные в формате "
    "ВЕС/ПОВТОРЕНИЯ (например, 80/10):"
)
INVALID_REPS_MSG = (
    "Некорректный формат. Введите целое число повторений от 1 до 100 "
    "(например, 12):"
)
INVALID_TIME_MSG = (
    "Некорректный формат. Введите время в секундах (30) "
    "или в формате мин:сек (1:30):"
)


def parse_weighted_set(text: str | None) -> tuple[float, int] | None:
    """
    Разбирает ввод подхода с отягощением в формате «вес/повторения».

    Параметры:
        text: строка вида «80/10» или «80,5/12»

    Возвращает:
        Кортеж (вес, повторения) или None при ошибке формата или диапазона
        (вес 0-500, повторения 1-100)
    """
    if not text:
        return None
    match = SET_INPUT_PATTERN.match(text)
    if not match:
        return None
    weight = float(match.group(1).replace(",", "."))
    reps = int(match.group(2))
    if weight < 0 or weight > 500 or reps <= 0 or reps > 100:
        return None
    return weight, reps


def parse_bodyweight_reps(text: str | None) -> int | None:
    """
    Разбирает ввод количества повторений для упражнения с собственным весом.

    Параметры:
        text: строка с целым числом повторений

    Возвращает:
        Число повторений (1-100) или None при некорректном вводе
    """
    if not text:
        return None
    match = REPS_ONLY_PATTERN.match(text)
    if not match:
        return None
    reps = int(match.group(1))
    if reps <= 0 or reps > 100:
        return None
    return reps


def parse_time_input(text: str | None) -> int | None:
    """
    Разбирает ввод длительности упражнения на время.

    Параметры:
        text: секунды («30») или минуты:секунды («1:30»)

    Возвращает:
        Общее число секунд (1-7200) или None при некорректном вводе
    """
    if not text:
        return None
    match = TIME_INPUT_PATTERN.match(text.strip())
    if not match:
        return None
    if match.group(2) is not None:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        if seconds >= 60 or minutes < 0:
            return None
        total = minutes * 60 + seconds
    else:
        total = int(match.group(1))
    if total <= 0 or total > 7200:
        return None
    return total
