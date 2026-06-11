# Технический аудит: gym_tg_bot

**Дата:** 2026-06-07  
**Стек:** aiogram 3.x, aioodbc, MS SQL Server, asyncio  
**Объём анализа:** `database/`, `handlers/`, `keyboards/`, `utils/`, `bot.py`

---

## Резюме

Проект в целом **корректно построен на async/await**: блокирующих сетевых вызовов в хендлерах нет, пул соединений используется через контекстный менеджер с `release`/`discard`. Основные риски сосредоточены в четырёх зонах:

1. **Неограниченный in-memory кэш** каталога упражнений и **MemoryStorage** FSM при росте пользователей.
2. **Избыточные round-trip'ы к БД** (N+1 при работе с шаблонами и подсказками «прошлая тренировка»).
3. **Синхронный I/O логирования** и **INFO-лог каждого SQL** — скрытая нагрузка на event loop.
4. **Несаржируемые предикаты** в календаре (`YEAR`/`MONTH`/`CAST`) — деградация при росте истории.

Ниже — детальный разбор по блокам и план действий.

---

## 1. Анализ работы с базой данных (`database/`)

### 1.1. Пул соединений и `_pooled_connection`

**Текущая реализация** (`requests.py`):

```python
@asynccontextmanager
async def _pooled_connection() -> AsyncIterator[Any]:
    pool = get_pool()
    conn = await pool.acquire()
    discard = False
    try:
        yield conn
    except Exception as exc:
        if _is_dead_connection_error(exc):
            await discard_connection(conn)
            discard = True
        raise
    finally:
        if not discard:
            await pool.release(conn)
```

| Сценарий | Поведение | Утечка? |
|----------|-----------|---------|
| Успешный запрос | `release(conn)` в `finally` | Нет |
| Обычная ошибка SQL (не обрыв) | `release(conn)` | Нет |
| Обрыв TCP / 08S01 | `discard` + `close`, без `release` | Нет |
| Исключение до `acquire` | `conn` не создан | Нет |

**Вывод:** классической утечки соединений при ошибках **нет** — паттерн реализован правильно.

**Риски (средний приоритет):**

1. **`refresh_db_pool()` при каждом retry** — при массовом обрыве связи несколько корутин одновременно пересоздают глобальный пул (`_pool = None` → `_create_pool()`). Это «thundering herd»: часть запросов может упасть с `RuntimeError: Пул БД не инициализирован`.

2. **Размер пула `maxsize=10`** — при 15+ одновременных апдейтах от разных пользователей остальные будут ждать `acquire()`. Для Telegram-бота обычно достаточно, но при пиках (массовый клик по календарю) возможны задержки 100–500 ms.

3. **`apply_schema_migrations()`** использует ручной `acquire/release` без `_pooled_connection`, но `finally` с `release` присутствует — утечки нет.

**Было → Стало (защита от гонки при refresh):**

```python
# Было (connection.py):
async def refresh_db_pool() -> None:
    global _pool
    old_pool = _pool
    _pool = None
    await _close_pool(old_pool)
    _pool = await _create_pool()

# Стало (рекомендация):
_pool_refresh_lock = asyncio.Lock()

async def refresh_db_pool() -> None:
    global _pool
    async with _pool_refresh_lock:
        if _pool is not None and _pool._free:  # пул уже жив
            return
        old_pool = _pool
        _pool = await _create_pool()
        await _close_pool(old_pool)
```

---

### 1.2. `_run_query` и логирование

Каждый SQL пишется в лог на уровне **INFO** с полным текстом запроса и параметрами:

```python
logger.info(
    "Выполнение SQL (попытка %s/%s): %s с параметрами: %s",
    attempt, MAX_QUERY_ATTEMPTS, sql.strip(), params,
)
```

**Проблема:** при активной тренировке (10–30 запросов на пользователя) это:
- раздувает файлы логов;
- вызывает **синхронную запись на диск** через `logging.FileHandler` в `bot.py` — блокирует event loop на время flush.

**Было → Стало:**

```python
# Было:
logger.info("Выполнение SQL ... %s ... %s", attempt, sql.strip(), params)

# Стало:
if logger.isEnabledFor(logging.DEBUG):
    logger.debug("SQL (попытка %s): %s params=%s", attempt, sql.strip(), params)
```

Дополнительно в `bot.py`:

```python
# Было:
file_handler = logging.FileHandler(log_file, encoding="utf-8")

# Стало:
from logging.handlers import QueueHandler, QueueListener
import queue
log_queue = queue.Queue(-1)
file_handler = logging.FileHandler(log_file, encoding="utf-8")
listener = QueueListener(log_queue, file_handler, console_handler)
listener.start()
root_logger.addHandler(QueueHandler(log_queue))
```

---

### 1.3. Кэш каталога упражнений

```python
_admin_exercises_cache: list[dict[str, Any]] | None = None
_user_exercises_cache: dict[int, list[dict[str, Any]]] = {}
```

| Аспект | Оценка |
|--------|--------|
| Корректность инвалидации | Хорошо: `_invalidate_exercise_cache(user_id)` вызывается при CRUD |
| Рост памяти | **Риск:** `_user_exercises_cache` растёт с каждым новым `id_user` и **никогда не очищается** |
| Утечка? | Формально не «утечка» (ссылки осознанные), но **неограниченный рост ОЗУ** при тысячах пользователей |
| Актуальность | Прямой SQL в БД не сбрасывает кэш — нужен рестарт бота |

**Оценка объёма:** 500 упражнений × 200 байт ≈ 100 KB на пользователя.  
1000 пользователей ≈ **100 MB** только в кэше каталога (плюс копии в FSM).

**Дополнительная неэффективность** — фильтрация категории в Python:

```python
async def get_exercises_by_category(user_id, category_id, *, refresh=False):
    catalog = await get_global_exercises_by_user_id(user_id, refresh=refresh)
    return [row for row in catalog if row.get("category_id") == category_id]
```

Каждый просмотр категории загружает **весь** каталог (admin + user), сортирует и фильтрует в памяти.

**Было → Стало:**

```python
# Было: полный каталог + filter
catalog = await get_global_exercises_by_user_id(user_id)
return [row for row in catalog if row.get("category_id") == category_id]

# Стало: точечный SQL + опциональный LRU-кэш
async def get_exercises_by_category(user_id: int, category_id: int) -> list[dict]:
    return await _run_query(
        f"""
        {_CATALOG_SELECT}
        WHERE workout_id IS NULL AND is_deleted = 0
          AND category_id = ?
          AND (id_user = ? OR id_user IS NULL)
        ORDER BY exercise_name
        """,
        (category_id, user_id),
        fetch="all",
    )
```

**Рекомендация по кэшу:** `cachetools.TTLCache(maxsize=500, ttl=300)` или LRU на 100–200 активных пользователей.

---

### 1.4. SQL-запросы и индексы

#### Частые запросы

| Функция | Запрос | Замечание |
|---------|--------|-----------|
| `get_workout_days_for_month` | `YEAR(started_at)`, `MONTH(started_at)` | Non-sargable, full scan по пользователю |
| `get_detailed_workouts_by_date` | `CAST(started_at AS DATE) = ?` | Non-sargable |
| `get_workout_statistics` | `COUNT(*)` + correlated subquery для тоннажа | Двойной проход по данным |
| `get_previous_set_for_exercise` | 2 запроса: find prev workout + find set | Вызывается **на каждый подход** в тренировке |
| `_WORKOUT_DETAIL_SELECT` | JOIN workouts + exercises + sets | Денормализованный результат: N_sets строк |

#### Рекомендуемые индексы (MS SQL Server)

```sql
-- Календарь и история по пользователю
CREATE NONCLUSTERED INDEX IX_GTB_workouts_user_finished
    ON GTB_workouts (id_user, finished_at DESC)
    INCLUDE (started_at, id_preset);

-- Фильтр по дате (альтернатива CAST)
CREATE NONCLUSTERED INDEX IX_GTB_workouts_user_started
    ON GTB_workouts (id_user, started_at)
    WHERE finished_at IS NOT NULL;

-- Каталог упражнений
CREATE NONCLUSTERED INDEX IX_GTB_workout_exercises_catalog
    ON GTB_workout_exercises (id_user, category_id, exercise_name)
    WHERE workout_id IS NULL AND is_deleted = 0;

-- Упражнения сессии
CREATE NONCLUSTERED INDEX IX_GTB_workout_exercises_workout
    ON GTB_workout_exercises (workout_id)
    INCLUDE (exercise_name, is_bodyweight);

-- Подходы
CREATE NONCLUSTERED INDEX IX_GTB_sets_exercise_number
    ON GTB_sets (id_workout_exercise, set_number)
    INCLUDE (weight, reps, duration_seconds);

-- Поиск предыдущей тренировки по шаблону
CREATE NONCLUSTERED INDEX IX_GTB_workouts_user_preset_finished
    ON GTB_workouts (id_user, id_preset, finished_at DESC)
    WHERE finished_at IS NOT NULL;
```

#### Улучшение календарного фильтра

**Было:**

```sql
WHERE id_user = ?
  AND finished_at IS NOT NULL
  AND YEAR(started_at) = ?
  AND MONTH(started_at) = ?
```

**Стало:**

```sql
WHERE id_user = ?
  AND finished_at IS NOT NULL
  AND started_at >= @month_start
  AND started_at < @next_month_start
```

Параметры `@month_start` / `@next_month_start` вычислять в Python — индекс по `started_at` начнёт работать.

#### N+1: подсказка «прошлая тренировка»

В `handlers/workout.py` на **каждый** ввод подхода:

```python
async def _previous_set_hint(data, set_number):
    prev = await db.get_previous_set_for_exercise(...)  # 2 SQL-запроса
```

Тренировка на 25 подходов = **до 50 лишних запросов**.

**Было → Стало:**

```python
# При старте тренировки по шаблону — один раз:
prev_id = await db.get_previous_finished_workout_id(db_user_id, preset_id, exclude_workout_id=workout_id)
if prev_id:
    prev_rows = await db.get_workout_detail_by_id(prev_id)
    await state.update_data(previous_sets_map=build_previous_sets_map(prev_rows))

# В _previous_set_hint — чтение из FSM, без SQL:
key = (exercise_name, exercise_type, set_number)
row = data.get("previous_sets_map", {}).get(key)
```

---

## 2. Анализ асинхронности и Event Loop

### 2.1. Что сделано правильно

- Все обращения к БД — `await db.*` через aioodbc.
- Нет `time.sleep`, `requests.get`, синхронных файловых операций в хендлерах.
- Парсинг ввода (`set_input.py`, regex) — микросекунды, не bottleneck.
- `datetime` / форматирование отчётов — линейно по числу подходов, для типичной тренировки (< 50 подходов) незаметно.

### 2.2. Скрытые блокировки event loop

| Источник | Файл | Серьёзность |
|----------|------|-------------|
| `logging.FileHandler` — синхронная запись | `bot.py` | **Medium** при высоком трафике |
| `logger.info` на каждый SQL | `requests.py` | **Medium** |
| `print()` при импорте модуля | `bot.py` (токен в консоль!) | Low + **security** |
| `MemoryStorage` — сериализация dict в RAM | `bot.py` | **Medium** при долгой работе |
| `merged.sort(key=casefold)` на каталоге | `requests.py` | Low (до ~1000 строк) |

### 2.3. FSM и память

```python
dp = Dispatcher(storage=MemoryStorage())
```

**Риск:** состояние **всех** активных диалогов хранится в RAM процесса. Длинная тренировка + мульти-выбор + редактирование шаблона накапливают `preset_queue`, `exercise_catalog`, `bulk_selected_ids`.

При рестарте бота — **потеря всех незавершённых сессий**.

**Рекомендация (Medium):** `RedisStorage` (aiogram) или `MemoryStorage` + периодическая очистка stale state.

### 2.4. Последовательные await-цепочки

Примеры лишних round-trip'ов:

```python
# bulk_add_global_exercises_to_preset — N запросов в цикле
for exercise_id in global_exercise_ids:
    exercise = await get_exercise_by_id(exercise_id)  # SQL
    await add_preset_exercise(...)                     # SQL

# _complete_workout_and_show_report
await db.finish_workout(workout_id)           # SQL 1
rows = await db.get_workout_detail_by_id(...) # SQL 2
previous_rows = await _load_previous_workout_rows(...)  # SQL 3-4
```

Для finish-report это приемлемо (разовая операция). Для bulk-add при 20 упражнениях — **40+ запросов**; лучше batch INSERT.

---

## 3. Оптимизация интерфейса и клавиатур (`keyboards/`)

### 3.1. `bulk_select.py`

**callback_data:**

```
bulk:toggle:preset_add:42:1057
```

Длина ≈ 30–45 байт. Лимит Telegram: **64 байта** на `callback_data` — **в пределах нормы**.

**Риски:**

| Риск | Порог | Статус |
|------|-------|--------|
| Длина `callback_data` | 64 байта | OK |
| Длина текста кнопки | 64 символа | ⚠️ Длинные названия упражнений обрезаются Telegram |
| Число кнопок | ~100+ | ⚠️ Сообщение с клавиатурой может превысить лимиты UI |
| Перерисовка при toggle | 1 `edit_text` + полная пересборка клавиатуры | OK для < 50 элементов |

**Было → Стало (защита текста кнопки):**

```python
# Было:
text=f"{check}{shared}{icon} {exercise['name']}"

# Стало:
def _button_label(name: str, prefix: str = "", max_len: int = 60) -> str:
    label = f"{prefix}{name}"
    return label if len(label) <= max_len else f"{label[:max_len - 3]}..."

text=_button_label(exercise['name'], prefix=f"{check}{shared}{icon} ")
```

**Альтернатива при > 30 упражнениях:** пагинация (`bulk:page:2`) или выбор по категориям.

### 3.2. `workout_calendar.py`

- Callback через `SimpleCalendarCallback.pack()` — компактный бинарный формат aiogram-calendar, **в лимите**.
- При каждом перелистывании месяца — `await db.get_workout_days_for_month()` — **1 SQL на действие**, нормально.
- Клавиатура ~7–8 рядов — стандартный размер.

### 3.3. `workout_exercises_keyboard` — индексы в callback

```python
callback_data=f"ex:select:{idx}"
```

Индекс в FSM-кэше `exercise_catalog`, а не `id` — **правильно** (короткий callback). Но при смене категории индексы сбрасываются — логика в хендлере должна держать catalog в state (так и сделано).

### 3.4. Лимит длины сообщения Telegram

Отчёт тренировки (`format_finish_workout`) при 10 упражнениях × 5 подходов может приблизиться к **4096 символам**. Сейчас разбиения нет.

**Рекомендация (Low):** проверка `len(report) > 4000` → разбивка на 2 сообщения.

---

## 4. Точечные баги и архитектурные риски

### 4.1. `root_dir` в `connection.py`

**Актуальный код уже исправлен** (в отличие от ранней версии со `split("gym_tg_bot")`):

```python
root_dir = Path(__file__).resolve().parent.parent
env_path = root_dir / ".env"
```

Это **надёжный** способ: не зависит от имени папки проекта.

**Мелкий техдолг:** осталась неиспользуемая строка:

```python
current_path = os.path.abspath(__file__)  # можно удалить
```

**Дублирование:** `.env` загружается и в `bot.py`, и в `connection.py` — при расхождении путей возможна путаница. Лучше единая точка в `bot.py` до импорта `database`.

### 4.2. `workout_progress.py`

```python
def build_previous_sets_map(rows: list[dict]) -> dict[tuple[str, int, int], dict]:
    for row in rows:
        key = (row["exercise_name"], exercise_type, int(row["set_number"]))
        result[key] = row
    return result
```

| Параметр | Оценка |
|----------|--------|
| Сложность построения map | O(n) по числу подходов одной тренировки |
| Сложность lookup | O(1) |
| Память | Одна предыдущая тренировка (~50–200 строк) — **копейки** |
| Масштабирование | Не строить map по **всей истории** — только last workout |

**Узкое место не здесь**, а в повторных SQL-запросах до построения map (см. §1.4).

### 4.3. Прочие риски

| Риск | Приоритет |
|------|-----------|
| `print(BOT_TOKEN)` при старте | **High** (безопасность) |
| Нет rate limiting / антиспам | Low (личный бот) |
| `get_workout_statistics` вызывается из нескольких мест | Low (кэшировать на 60 сек) |
| Исторические тренировки: `finished_at IS NOT NULL` обязателен для отображения | Документировать в SQL-сидах |

---

## 5. План действий (Action Items)

### High — критично

| # | Задача | Файл | Эффект |
|---|--------|------|--------|
| H1 | Убрать `print` токена; не логировать `BOT_TOKEN` | `bot.py` | Безопасность |
| H2 | Кэшировать `previous_sets_map` / `prev_workout_id` в FSM при старте preset-тренировки | `handlers/workout.py` | −50 SQL на тренировку |
| H3 | SQL-фильтр `category_id` вместо загрузки всего каталога | `requests.py` | −RAM, −latency |
| H4 | Добавить индексы `IX_GTB_workouts_user_*`, `IX_GTB_sets_*` | SQL migration | Ускорение календаря/истории |

### Medium — важно

| # | Задача | Файл | Эффект |
|---|--------|------|--------|
| M1 | LRU/TTL для `_user_exercises_cache` (max 200–500 users) | `requests.py` | Контроль ОЗУ |
| M2 | `asyncio.Lock` на `refresh_db_pool()` | `connection.py` | Стабильность при обрывах |
| M3 | SQL-логи на DEBUG, не INFO | `requests.py` | Меньше блокировок I/O |
| M4 | `QueueHandler` для файлового лога | `bot.py` | Event loop не блокируется |
| M5 | Заменить `YEAR/MONTH/CAST` на диапазон дат | `requests.py` | Index seek |
| M6 | Batch INSERT в `bulk_add_global_exercises_to_preset` | `requests.py` | −N SQL |
| M7 | Рассмотреть `RedisStorage` вместо `MemoryStorage` | `bot.py` | Персистентность FSM |

### Low — улучшения

| # | Задача | Файл | Эффект |
|---|--------|------|--------|
| L1 | Пагинация `bulk_select` при > 25 упражнениях | `bulk_select.py` | UX + лимиты Telegram |
| L2 | Обрезка текста inline-кнопок до 64 символов | `keyboards/*` | Предсказуемый UI |
| L3 | Разбивка отчёта > 4000 символов | `workout_display.py` | Нет ошибок sendMessage |
| L4 | Удалить мёртвый `current_path` | `connection.py` | Чистота кода |
| L5 | Кэш `get_workout_statistics` на 30–60 сек | `handlers/statistics.py` | −1 тяжёлый SQL на просмотр |

---

## 6. Инструменты профайлинга (локально)

### Python / Event Loop

```bash
# 1. Трассировка утечек объектов между сценариями
py -m tracemalloc --module bot.py
# В коде: tracemalloc.start(); snapshot = tracemalloc.take_snapshot()

# 2. Профиль async-кода (кто держит event loop)
pip install yappi
# py -m yappi -b bot.py  — смотреть wall time и call count

# 3. Память по строкам (точечные пики)
pip install memory_profiler
# @profile на get_global_exercises_by_user_id и format_finish_workout

# 4. Встроенный asyncio debug
asyncio.run(main(), debug=True)  # предупреждения о медленных callback (>100ms)
```

### MS SQL Server

```sql
-- План выполнения тяжёлых запросов
SET STATISTICS IO, TIME ON;
EXEC ... -- get_workout_statistics, get_detailed_workouts_by_date

-- DMV: топ запросов по CPU/reads
SELECT TOP 20
    qs.execution_count,
    qs.total_worker_time / qs.execution_count AS avg_cpu,
    qs.total_logical_reads / qs.execution_count AS avg_reads,
    SUBSTRING(st.text, (qs.statement_start_offset/2)+1, 120) AS stmt
FROM sys.dm_exec_query_stats qs
CROSS APPLY sys.dm_exec_sql_text(qs.sql_handle) st
ORDER BY qs.total_worker_time DESC;

-- Проверка использования индексов
SELECT object_name(s.object_id), i.name, s.user_seeks, s.user_scans
FROM sys.dm_db_index_usage_stats s
JOIN sys.indexes i ON s.object_id = i.object_id AND s.index_id = i.index_id
WHERE database_id = DB_ID();
```

### Нагрузочный сценарий для бота

1. 5 виртуальных пользователей параллельно открывают календарь и листают 12 месяцев.
2. 3 пользователя ведут тренировку по шаблону (25 подходов каждый).
3. Мониторить: размер процесса (`psutil.Process().memory_info().rss`), latency ответа, счётчик SQL в логах.

**Ожидаемый выигрыш после H2+H3+H4:** latency карточки тренировки −30–50%, SQL на preset-сессию −60–80%.

---

## Приложение: карта «узких мест»

```
Пользователь → [Handler] → [FSM MemoryStorage] → [db._run_query]
                                    ↓                      ↓
                              RAM растёт            [aioodbc Pool max=10]
                                                           ↓
                                                    [SQL Server]
                                                           ↓
                              ← [_user_exercises_cache] ← (full catalog)
                              ← [get_previous_set × N]  ← (N+1 на подход)
```

---

*Отчёт подготовлен по состоянию кодовой базы в `project_summary.txt` / рабочей директории проекта.*
