"""Утилиты для шаблонов тренировок: подходы и форматирование."""

from __future__ import annotations

from utils.text_helpers import get_approach_string

# Лимит Telegram для текста inline-кнопки
_PRESET_BUTTON_MAX_LEN = 64


def preset_display_name(preset: dict) -> str:
    """Полное имя шаблона из БД (preset_name / name)."""
    return (preset.get("preset_name") or preset.get("name") or "").strip()


def preset_button_text(preset: dict, *, prefix: str = "📋 ") -> str:
    """Текст кнопки шаблона: полное preset_name, обрезка только по лимиту Telegram."""
    name = preset_display_name(preset)
    text = f"{prefix}{name}"
    if len(text) <= _PRESET_BUTTON_MAX_LEN:
        return text
    keep = _PRESET_BUTTON_MAX_LEN - len(prefix) - 1
    if keep < 1:
        return text[:_PRESET_BUTTON_MAX_LEN]
    return f"{prefix}{name[:keep]}..."


def parse_sets_count_input(text: str | None) -> int | None:
    """Целое число >= 0 или None при некорректном вводе."""
    if text is None:
        return None
    stripped = text.strip()
    if not stripped.isdigit():
        return None
    return int(stripped)


def format_preset_exercise_line(index: int, exercise: dict) -> str:
    """Строка упражнения в списке шаблона."""
    name = exercise["name"]
    sets_count = int(exercise.get("sets_count") or 0)
    if sets_count > 0:
        return f"{index}) {name} - {get_approach_string(sets_count)}"
    return f"{index}) {name}"


def format_preset_exercises_list(exercises: list[dict]) -> str:
    if not exercises:
        return "В программе пока нет упражнений."
    return "\n".join(
        format_preset_exercise_line(idx, ex)
        for idx, ex in enumerate(exercises, start=1)
    )
