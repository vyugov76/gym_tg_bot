"""Собирает все .py и .sql файлы проекта в project_summary.txt."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "project_summary.txt"

SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", ".cursor"}

# Логический порядок: конфиг/БД -> утилиты -> состояния -> клавиатуры -> хендлеры -> main
ORDERED_FILES = [
    "database/connection.py",
    "database/requests.py",
    "database/fix_presets_and_workout_times.sql",
    "database/relink_workout_exercises.sql",
    "utils/__init__.py",
    "utils/exercise_types.py",
    "utils/text_helpers.py",
    "utils/set_input.py",
    "utils/preset_helpers.py",
    "utils/workout_progress.py",
    "utils/workout_display.py",
    "states/workout_states.py",
    "keyboards/bulk_select.py",
    "keyboards/menu.py",
    "keyboards/workout_calendar.py",
    "keyboards/workout_report.py",
    "handlers/start.py",
    "handlers/exercises.py",
    "handlers/workout.py",
    "handlers/settings.py",
    "handlers/statistics.py",
    "bot.py",
]


def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def discover_files() -> list[Path]:
    found: list[Path] = []
    for pattern in ("**/*.py", "**/*.sql"):
        for path in ROOT.glob(pattern):
            if should_skip(path.relative_to(ROOT)):
                continue
            if path.name == Path(__file__).name:
                continue
            found.append(path)
    return found


def relative_posix(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> None:
    discovered = {relative_posix(p): p for p in discover_files()}
    ordered_keys = [key for key in ORDERED_FILES if key in discovered]
    remaining = sorted(set(discovered) - set(ordered_keys))
    file_keys = ordered_keys + remaining

    parts: list[str] = []
    for key in file_keys:
        path = discovered[key]
        content = path.read_text(encoding="utf-8")
        parts.append(
            "=========================================\n"
            f"ФАЙЛ: {key}\n"
            "=========================================\n"
            f"{content.rstrip()}\n"
        )

    OUTPUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"Записано файлов: {len(file_keys)} -> {OUTPUT}")


if __name__ == "__main__":
    main()
