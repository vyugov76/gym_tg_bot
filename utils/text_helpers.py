"""
text_helpers - текстовые утилиты

Склонение русских слов и форматирование длительности для сообщений бота.

Ключевые компоненты:
- get_approach_string - склонение «подход/подхода/подходов»
- format_exercise_time - отображение секунд в мин:сек
"""

from __future__ import annotations


def get_approach_string(count: int) -> str:
    """
    Формирует строку с числом и правильным склонением слова «подход».

    Параметры:
        count: количество подходов

    Возвращает:
        Строку вида «3 подхода», «1 подход», «5 подходов»
    """
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
    """
    Форматирует длительность упражнения «на время» для отображения.

    Параметры:
        seconds: длительность в секундах

    Возвращает:
        Строку «30сек.», «2мин.» или «2мин. 30сек.»
    """
    if seconds < 60:
        return f"{seconds}сек."
    minutes = seconds // 60
    secs = seconds % 60
    if secs == 0:
        return f"{minutes}мин."
    return f"{minutes}мин. {secs}сек."
