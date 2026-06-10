/*
  Исправление названий шаблонов и времени исторических тренировок (id_user = 1).

  Время в GTB_workouts:
    - Бот и SQL должны хранить «настенное» локальное время (МСК), как видит пользователь.
    - НЕ используйте GETUTCDATE() для started_at/finished_at, если хотите видеть те же часы в боте.
    - Пример: тренировка в 23:41 МСК -> started_at = '2026-06-08 23:41:00'.

  Если ранее вставляли 23:41, а бот показывал 02:41 (+3 ч) - данные уже лежат верно,
  ломала отображение конвертация UTC->MSK в Python (исправлена в utils/workout_display.py).
  Откатывать DATEADD не нужно.

  Если же вы заливали время уже в UTC (вычитали 3 часа) - верните обратно:
    UPDATE GTB_workouts SET started_at = DATEADD(HOUR, 3, started_at) WHERE ...
*/

SET NOCOUNT ON;

DECLARE @UserId INT = 1;

-- 1. Полные названия шаблонов
UPDATE GTB_preset_workouts
SET preset_name = N'День 1. PUSH (Грудь + Плечи + Трицепс)'
WHERE id_user = @UserId
  AND is_deleted = 0
  AND preset_name IN (N'PUSH', N'День 1. PUSH (Грудь + Плечи + Трицепс)');

UPDATE GTB_preset_workouts
SET preset_name = N'День 2. PULL (Спина + Бицепс)'
WHERE id_user = @UserId
  AND is_deleted = 0
  AND preset_name IN (N'PULL', N'День 2. PULL (Спина + Бицепс)');

UPDATE GTB_preset_workouts
SET preset_name = N'День 3. LEGS (Ноги + Пресс)'
WHERE id_user = @UserId
  AND is_deleted = 0
  AND preset_name IN (N'LEGS', N'День 3. LEGS (Ноги + Пресс)');

-- Проверка
SELECT id_preset, preset_name, LEN(preset_name) AS name_len
FROM GTB_preset_workouts
WHERE id_user = @UserId AND is_deleted = 0
ORDER BY preset_name;

-- 2. Пример вставки исторической тренировки с корректным локальным временем
/*
DECLARE @WorkoutId INT;
DECLARE @PresetId INT = (
    SELECT TOP 1 id_preset
    FROM GTB_preset_workouts
    WHERE id_user = @UserId AND preset_name LIKE N'%PUSH%' AND is_deleted = 0
);

INSERT INTO GTB_workouts (id_user, id_preset, started_at, finished_at)
VALUES (
    @UserId,
    @PresetId,
    '2026-06-08 23:41:00',   -- локальное МСК, как в журнале
    '2026-06-09 00:35:00'
);

SET @WorkoutId = SCOPE_IDENTITY();
-- далее GTB_workout_exercises и GTB_sets для @WorkoutId
*/

PRINT N'Готово. Перезапустите бота и проверьте список шаблонов и время тренировок.';
