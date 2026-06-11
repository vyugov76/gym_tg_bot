"""Форматирование времени и детализации тренировок."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from utils.exercise_types import (
    EXERCISE_BODYWEIGHT,
    EXERCISE_TIMED,
    EXERCISE_WEIGHTED,
    normalize_exercise_type,
)
from utils.text_helpers import format_exercise_time, get_approach_string
from utils.workout_progress import (
    build_previous_sets_map,
    compare_set_progress,
    format_set_value_for_display,
)


def infer_user_utc_offset(telegram_date: datetime | None) -> timedelta:
    """
    Оценивает смещение локального времени пользователя от UTC.

    Telegram передаёт date как UTC-instant. Сравниваем наивное локальное
    отображение этого момента с текущим UTC — получаем timedelta для
    перевода UTC из БД в локальное wall-clock время пользователя.
    """
    if telegram_date is None:
        return timedelta(0)

    utc_now = datetime.now(timezone.utc)
    if telegram_date.tzinfo is None:
        msg_utc = telegram_date.replace(tzinfo=timezone.utc)
    else:
        msg_utc = telegram_date.astimezone(timezone.utc)

    msg_local_naive = msg_utc.astimezone().replace(tzinfo=None)
    utc_naive = utc_now.replace(tzinfo=None)
    return msg_local_naive - utc_naive


def utc_offset_to_seconds(offset: timedelta | None) -> int:
    if offset is None:
        return 0
    return int(offset.total_seconds())


def utc_offset_from_seconds(seconds: int | None) -> timedelta:
    if seconds is None:
        return timedelta(0)
    return timedelta(seconds=seconds)


def to_local_datetime(
    dt: datetime | None,
    utc_offset: timedelta | None = None,
) -> datetime | None:
    """Переводит naive UTC из БД в локальное время пользователя."""
    if dt is None:
        return None

    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt.astimezone(timezone.utc)

    offset = utc_offset or timedelta(0)
    return (utc_dt + offset).replace(tzinfo=None)


def format_weight(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(value).rstrip("0").rstrip(".")


def format_duration(
    started_at: datetime,
    finished_at: datetime | None,
    *,
    utc_offset: timedelta | None = None,
) -> str:
    """Рассчитывает длительность через разницу datetime в Python."""
    if not finished_at:
        return "—"

    start_local = to_local_datetime(started_at, utc_offset)
    finish_local = to_local_datetime(finished_at, utc_offset)
    minutes = round((finish_local - start_local).total_seconds() / 60)

    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        if mins:
            return f"{hours} ч. {mins} мин."
        return f"{hours} ч."
    return f"{minutes} минут"


def _set_duration_seconds(set_row: dict) -> int:
    """Секунды подхода: новое поле duration_seconds или legacy reps."""
    if set_row.get("duration_seconds") is not None:
        return int(set_row["duration_seconds"])
    if set_row.get("reps") is not None:
        return int(set_row["reps"])
    return 0


def _format_set_parts(
    exercise_type: int,
    sets: list[dict],
    *,
    exercise_name: str | None = None,
    previous_sets_map: dict[tuple[str, int, int], dict] | None = None,
) -> str:
    exercise_type = normalize_exercise_type(exercise_type)
    parts: list[str] = []
    for s in sets:
        value = format_set_value_for_display(s, exercise_type)
        if not value:
            continue
        prefix = ""
        if previous_sets_map is not None and exercise_name is not None:
            key = (exercise_name, exercise_type, int(s["set_number"]))
            prev = previous_sets_map.get(key)
            prefix = compare_set_progress(s, prev, exercise_type)
        parts.append(f"{prefix}{value}")
    return " ".join(parts)


def get_exercises_from_rows(rows: list[dict]) -> list[dict]:
    """Упражнения с подходами в порядке отображения (1, 2, 3...)."""
    exercises: dict[int, dict] = {}
    for row in rows:
        if row.get("set_number") is None:
            continue
        we_id = row["id_workout_exercise"]
        if we_id not in exercises:
            exercises[we_id] = {
                "id": we_id,
                "name": row["exercise_name"],
                "exercise_type": normalize_exercise_type(row["is_bodyweight"]),
            }
    return [exercises[k] for k in sorted(exercises.keys())]


def format_exercise_lines(
    rows: list[dict],
    *,
    previous_rows: list[dict] | None = None,
) -> list[str]:
    """Форматирует блоки упражнений с нумерацией 1), 2), 3)."""
    previous_sets_map = (
        build_previous_sets_map(previous_rows) if previous_rows else None
    )
    exercises: dict[int, dict] = {}
    for row in rows:
        if row.get("set_number") is None:
            continue
        we_id = row["id_workout_exercise"]
        if we_id not in exercises:
            exercises[we_id] = {
                "name": row["exercise_name"],
                "exercise_type": normalize_exercise_type(row["is_bodyweight"]),
                "sets": [],
            }
        exercises[we_id]["sets"].append(row)

    lines: list[str] = []
    for idx, (_, ex_data) in enumerate(
        sorted(exercises.items(), key=lambda item: item[0]),
        start=1,
    ):
        sets = sorted(ex_data["sets"], key=lambda s: s["set_number"])
        exercise_type = ex_data["exercise_type"]
        lines.append(
            f"{idx}) {ex_data['name']} - {get_approach_string(len(sets))}"
        )
        lines.append(
            _format_set_parts(
                exercise_type,
                sets,
                exercise_name=ex_data["name"],
                previous_sets_map=previous_sets_map,
            )
        )
        lines.append("")

    return lines


def _workout_title_lines(
    first: dict,
    selected_date: date | None = None,
    *,
    utc_offset: timedelta | None = None,
) -> list[str]:
    """Заголовок отчёта: дата на первой строке, название шаблона — на второй."""
    if selected_date is not None:
        date_str = selected_date.strftime("%d.%m.%Y")
    else:
        started_at = to_local_datetime(first["started_at"], utc_offset)
        date_str = started_at.strftime("%d.%m.%Y")

    lines = [f"📅 Тренировка на {date_str}"]
    preset_name = (first.get("preset_name") or "").strip()
    if preset_name:
        lines.append(preset_name)
    return lines


def format_calendar_workout(
    rows: list[dict],
    selected_date: date,
    *,
    previous_rows: list[dict] | None = None,
    utc_offset: timedelta | None = None,
) -> str:
    """Формат детализации для календаря статистики."""
    first = rows[0]
    started_at = to_local_datetime(first["started_at"], utc_offset)

    lines = [
        *_workout_title_lines(first, selected_date, utc_offset=utc_offset),
        f"Начало тренировки: {started_at.strftime('%H:%M')}",
        f"Продолжительность: {format_duration(
            first['started_at'],
            first.get('finished_at'),
            utc_offset=utc_offset,
        )}",
        "",
    ]
    lines.extend(format_exercise_lines(rows, previous_rows=previous_rows))
    return "\n".join(lines).rstrip()


def format_finish_workout(
    rows: list[dict],
    *,
    previous_rows: list[dict] | None = None,
    utc_offset: timedelta | None = None,
) -> str:
    """Формат отчёта при завершении тренировки."""
    first = rows[0]
    started_at = to_local_datetime(first["started_at"], utc_offset)
    duration_str = format_duration(
        first["started_at"],
        first.get("finished_at"),
        utc_offset=utc_offset,
    )

    lines = [
        *_workout_title_lines(first, utc_offset=utc_offset),
        f"Начало тренировки: {started_at.strftime('%H:%M')}",
        f"Продолжительность: {duration_str}",
        "",
    ]
    lines.extend(format_exercise_lines(rows, previous_rows=previous_rows))
    return "\n".join(lines).rstrip()
