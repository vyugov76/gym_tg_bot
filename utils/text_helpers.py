"""Текстовые утилиты: склонения и форматирование."""

from __future__ import annotations


def get_approach_string(count: int) -> str:
    """Возвращает «N подход/подхода/подходов» с правильным склонением."""
    n = abs(count) % 100
    n1 = n % 10
    if 11 <= n <= 19:
        suffix = "подходов"
    elif n1 == 1:
        suffix = "подход"
    elif 2 <= n1 <= 4:
        suffix = "подхода"
    else:
        suffix = "подходов"
    return f"{count} {suffix}"


def format_exercise_time(seconds: int) -> str:
    """Форматирует секунды для упражнений «на время»."""
    if seconds < 60:
        return f"{seconds}сек."
    minutes = seconds // 60
    secs = seconds % 60
    if secs == 0:
        return f"{minutes}мин."
    return f"{minutes}мин. {secs}сек."
