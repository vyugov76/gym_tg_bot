"""Форматирование времени и детализации тренировок."""

from __future__ import annotations

from datetime import date, datetime, timezone


def to_local_datetime(dt: datetime | None) -> datetime | None:
    """Приводит naive datetime из БД (UTC) к локальному времени."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().replace(tzinfo=None)


def approaches_label(count: int) -> str:
    """Склонение слова «подход»."""
    if count % 10 == 1 and count % 100 != 11:
        suffix = "подход"
    elif 2 <= count % 10 <= 4 and not (12 <= count % 100 <= 14):
        suffix = "подхода"
    else:
        suffix = "подходов"
    return f"{count} {suffix}"


def format_weight(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return str(value).rstrip("0").rstrip(".")


def format_duration(started_at: datetime, finished_at: datetime | None) -> str:
    """Рассчитывает длительность через разницу datetime в Python."""
    if not finished_at:
        return "—"

    start_local = to_local_datetime(started_at)
    finish_local = to_local_datetime(finished_at)
    minutes = round((finish_local - start_local).total_seconds() / 60)

    if minutes >= 60:
        hours = minutes // 60
        mins = minutes % 60
        if mins:
            return f"{hours} ч. {mins} мин."
        return f"{hours} ч."
    return f"{minutes} минут"


def format_exercise_lines(rows: list[dict]) -> list[str]:
    """Форматирует блоки упражнений из строк детализации."""
    exercises: dict[int, dict] = {}
    for row in rows:
        if row.get("set_number") is None:
            continue
        we_id = row["id_workout_exercise"]
        if we_id not in exercises:
            exercises[we_id] = {
                "name": row["exercise_name"],
                "is_bodyweight": row["is_bodyweight"],
                "sets": [],
            }
        exercises[we_id]["sets"].append(row)

    lines: list[str] = []
    for ex_data in exercises.values():
        sets = sorted(ex_data["sets"], key=lambda s: s["set_number"])
        lines.append(f"· {ex_data['name']} — {approaches_label(len(sets))}")

        if ex_data["is_bodyweight"]:
            parts = [f"{s['reps']} повт." for s in sets]
        else:
            parts = [
                f"{format_weight(s['weight'])}/{s['reps']}"
                for s in sets
            ]
        lines.append(" ".join(parts))
        lines.append("")

    return lines


def format_calendar_workout(rows: list[dict], selected_date: date) -> str:
    """Формат детализации для календаря статистики."""
    first = rows[0]
    started_at = to_local_datetime(first["started_at"])
    finished_at = to_local_datetime(first.get("finished_at"))

    lines = [
        f"📅 Тренировка на {selected_date.strftime('%d.%m.%Y')}",
        f"Начало тренировки: {started_at.strftime('%H:%M')}",
        f"Продолжительность: {format_duration(first['started_at'], first.get('finished_at'))}",
        "",
    ]
    lines.extend(format_exercise_lines(rows))
    return "\n".join(lines).rstrip()


def format_finish_workout(rows: list[dict]) -> str:
    """Формат отчёта при завершении тренировки."""
    first = rows[0]
    started_at = to_local_datetime(first["started_at"])
    duration_str = format_duration(first["started_at"], first.get("finished_at"))

    lines = [
        "🎉 Тренировка завершена! Отличная работа!",
        f"⏱️ Время: {started_at.strftime('%H:%M')}",
        f"⏳ Продолжительность: {duration_str}",
        "",
    ]
    lines.extend(format_exercise_lines(rows))
    return "\n".join(lines).rstrip()
