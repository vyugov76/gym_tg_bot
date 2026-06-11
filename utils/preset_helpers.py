"""
preset_helpers - утилиты для шаблонов тренировок

Форматирование имён шаблонов, текстов inline-кнопок, парсинг числа
подходов и построение списков упражнений программы.

Ключевые компоненты:
- preset_display_name, preset_button_text - имена и кнопки шаблонов
- parse_sets_count_input - разбор ввода количества подходов
- format_preset_exercise_line, format_preset_exercises_list - списки упражнений
"""

from __future__ import annotations

from utils.text_helpers import get_approach_string

_PRESET_BUTTON_MAX_LEN = 64


def preset_display_name(preset: dict) -> str:
    """
    Извлекает полное имя шаблона из записи БД.

    Параметры:
        preset: словарь шаблона с полями preset_name или name

    Возвращает:
        Обрезанное по краям имя шаблона или пустую строку
    """
    return (preset.get("preset_name") or preset.get("name") or "").strip()


def preset_button_text(preset: dict, *, prefix: str = "📋 ") -> str:
    """
    Формирует текст inline-кнопки шаблона с учётом лимита Telegram (64 символа).

    Параметры:
        preset: словарь шаблона из БД
        prefix: префикс перед именем, по умолчанию «📋 »

    Возвращает:
        Текст кнопки; длинное имя обрезается с «...» в конце
    """
    name = preset_display_name(preset)
    text = f"{prefix}{name}"
    if len(text) <= _PRESET_BUTTON_MAX_LEN:
        return text
    keep = _PRESET_BUTTON_MAX_LEN - len(prefix) - 1
    if keep < 1:
        return text[:_PRESET_BUTTON_MAX_LEN]
    return f"{prefix}{name[:keep]}..."


def parse_sets_count_input(text: str | None) -> int | None:
    """
    Разбирает ввод количества подходов.

    Параметры:
        text: строка от пользователя или None

    Возвращает:
        Неотрицательное целое число или None при некорректном вводе
    """
    if text is None:
        return None
    stripped = text.strip()
    if not stripped.isdigit():
        return None
    return int(stripped)


def format_preset_exercise_line(index: int, exercise: dict) -> str:
    """
    Формирует одну строку упражнения в списке шаблона.

    Параметры:
        index: порядковый номер в списке (1, 2, 3...)
        exercise: словарь с полями name и sets_count

    Возвращает:
        Строку вида «N) Имя - M подходов» или «N) Имя», если подходов нет
    """
    name = exercise["name"]
    sets_count = int(exercise.get("sets_count") or 0)
    if sets_count > 0:
        return f"{index}) {name} - {get_approach_string(sets_count)}"
    return f"{index}) {name}"


def format_preset_exercises_list(exercises: list[dict]) -> str:
    """
    Собирает многострочный список упражнений шаблона.

    Параметры:
        exercises: список словарей упражнений шаблона

    Возвращает:
        Текст списка или сообщение об отсутствии упражнений
    """
    if not exercises:
        return "В программе пока нет упражнений."
    return "\n".join(
        format_preset_exercise_line(idx, ex)
        for idx, ex in enumerate(exercises, start=1)
    )
