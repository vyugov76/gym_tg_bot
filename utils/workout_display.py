"""
workout_display - форматирование отчётов о тренировках

Преобразует строки БД в читаемые сообщения: локальное время, длительность,
списки упражнений с подходами и отчёты для календаря и завершения тренировки.

Ключевые компоненты:
- infer_user_utc_offset, to_local_datetime - перевод UTC в локальное время
- utc_offset_to_seconds, utc_offset_from_seconds - сериализация смещения
- format_weight, format_duration - форматирование веса и длительности
- get_exercises_from_rows, format_exercise_lines - блоки упражнений
- format_calendar_workout, format_finish_workout - итоговые отчёты
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from utils.exercise_types import normalize_exercise_type
from utils.text_helpers import get_approach_string
from utils.workout_progress import (
    build_previous_sets_map,
    compare_set_progress,
    format_set_value_for_display,
)


def infer_user_utc_offset(telegram_date: datetime | None) -> timedelta:
    """
    Оценивает смещение локального времени пользователя от UTC.

    Telegram передаёт date как UTC-instant. Сравниваем наивное локальное
    отображение этого момента с текущим UTC - получаем timedelta для
    перевода UTC из БД в локальное wall-clock время пользователя.

    Параметры:
        telegram_date: метка времени сообщения Telegram или None

    Возвращает:
        Смещение timedelta; нулевое, если telegram_date равен None
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
    """
    Преобразует смещение UTC в целое число секунд для хранения в FSM.

    Параметры:
        offset: смещение timedelta или None

    Возвращает:
        Число секунд; 0, если offset равен None
    """
    if offset is None:
        return 0
    return int(offset.total_seconds())


def utc_offset_from_seconds(seconds: int | None) -> timedelta:
    """
    Восстанавливает смещение UTC из сохранённого числа секунд.

    Параметры:
        seconds: смещение в секундах или None

    Возвращает:
        timedelta; нулевой, если seconds равен None
    """
    if seconds is None:
        return timedelta(0)
    return timedelta(seconds=seconds)


def to_local_datetime(
    dt: datetime | None,
    utc_offset: timedelta | None = None,
) -> datetime | None:
    """
    Переводит naive UTC из БД в локальное время пользователя.

    Параметры:
        dt: дата-время из БД (naive UTC) или None
        utc_offset: смещение пользователя от UTC

    Возвращает:
        Локальное naive datetime или None, если dt равен None
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        utc_dt = dt.replace(tzinfo=timezone.utc)
    else:
        utc_dt = dt.astimezone(timezone.utc)

    offset = utc_offset or timedelta(0)
    return (utc_dt + offset).replace(tzinfo=None)


def format_weight(value: float | None) -> str:
    """
    Форматирует вес для отображения без лишних нулей после запятой.

    Параметры:
        value: вес в килограммах или None

    Возвращает:
        Строку с весом или пустую строку, если value равен None
    """
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
    """
    Рассчитывает и форматирует длительность тренировки.

    Параметры:
        started_at: время начала (naive UTC из БД)
        finished_at: время окончания или None для незавершённой
        utc_offset: смещение локального времени пользователя

    Возвращает:
        Строку «N минут», «N ч. M мин.» или «-», если finished_at отсутствует
    """
    if not finished_at:
        return "-"

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


def _format_set_parts(
    exercise_type: int,
    sets: list[dict],
    *,
    exercise_name: str | None = None,
    previous_sets_map: dict[tuple[str, int, int], dict] | None = None,
) -> str:
    """
    Собирает строку значений подходов с опциональными индикаторами прогресса.

    Параметры:
        exercise_type: тип упражнения (0, 1 или 2)
        sets: список словарей подходов, отсортированный по set_number
        exercise_name: имя упражнения для сопоставления с предыдущей тренировкой
        previous_sets_map: карта подходов предыдущей тренировки или None

    Возвращает:
        Строку значений подходов через пробел
    """
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
    """
    Извлекает уникальные упражнения из плоских строк БД.

    Параметры:
        rows: строки с полями id_workout_exercise, exercise_name, is_bodyweight

    Возвращает:
        Список словарей упражнений в порядке id_workout_exercise
    """
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
    """
    Форматирует блоки упражнений с нумерацией и значениями подходов.

    Параметры:
        rows: строки текущей тренировки из БД
        previous_rows: строки предыдущей тренировки для сравнения или None

    Возвращает:
        Список строк сообщения (заголовок упражнения, подходы, пустая строка)
    """
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
    """
    Формирует заголовок отчёта: дата и название шаблона.

    Параметры:
        first: первая строка тренировки из БД
        selected_date: дата из календаря или None для даты начала
        utc_offset: смещение локального времени пользователя

    Возвращает:
        Список из одной-двух строк заголовка
    """
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
    """
    Формирует детализацию тренировки для экрана календаря статистики.

    Параметры:
        rows: строки тренировки из БД
        selected_date: дата, выбранная в календаре
        previous_rows: строки предыдущей тренировки для сравнения или None
        utc_offset: смещение локального времени пользователя

    Возвращает:
        Многострочный текст отчёта
    """
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
    """
    Формирует отчёт при завершении тренировки.

    Параметры:
        rows: строки завершённой тренировки из БД
        previous_rows: строки предыдущей тренировки для сравнения или None
        utc_offset: смещение локального времени пользователя

    Возвращает:
        Многострочный текст отчёта
    """
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
