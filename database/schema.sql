-- ===================================================================
-- 1. МОДЕРНИЗАЦИЯ ТАБЛИЦЫ ПОДХОДОВ (GTB_sets)
-- Добавляем универсальные поля для учета времени и дистанции
-- ===================================================================
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('GTB_sets') AND name = 'duration_seconds')
    ALTER TABLE GTB_sets ADD duration_seconds INT NULL;

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('GTB_sets') AND name = 'distance_meters')
    ALTER TABLE GTB_sets ADD distance_meters INT NULL;

-- Поля weight и reps делаем необязательными (NULL), чтобы для планки можно было заполнять только время
ALTER TABLE GTB_sets ALTER COLUMN weight DECIMAL(5,2) NULL;
ALTER TABLE GTB_sets ALTER COLUMN reps INT NULL;


-- ===================================================================
-- 2. ВНЕДРЕНИЕ МЯГКОГО УДАЛЕНИЯ (Soft Delete)
-- Добавляем флаг избыточности, чтобы данные не удалялись физически
-- ===================================================================
IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('GTB_workout_exercises') AND name = 'is_deleted')
    ALTER TABLE GTB_workout_exercises ADD is_deleted TINYINT NOT NULL DEFAULT 0;

IF NOT EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('GTB_preset_workouts') AND name = 'is_deleted')
    ALTER TABLE GTB_preset_workouts ADD is_deleted TINYINT NOT NULL DEFAULT 0;


-- ===================================================================
-- 3. БЕЗОПАСНОСТЬ ИСТОРИИ ТРЕНИРОВОК
-- Перестраиваем связь GTB_sets -> GTB_workout_exercises.
-- Если пользователь уберет упражнение из каталога, его старые подходы в истории ДОЛЖНЫ ОСТАТЬСЯ!
-- ===================================================================
DECLARE @SqlSetsFK NVARCHAR(MAX) = (
    SELECT 'ALTER TABLE GTB_sets DROP CONSTRAINT ' + name
    FROM sys.foreign_keys
    WHERE parent_object_id = OBJECT_ID('GTB_sets') 
      AND referenced_object_id = OBJECT_ID('GTB_workout_exercises')
);
IF @SqlSetsFK IS NOT NULL EXEC sp_executesql @SqlSetsFK;

-- Пересоздаем внешний ключ с ON DELETE NO ACTION вместо CASCADE
ALTER TABLE GTB_sets ADD CONSTRAINT FK_GTB_sets_WorkoutExercises 
FOREIGN KEY (id_workout_exercise) REFERENCES GTB_workout_exercises(id_workout_exercise) ON DELETE NO ACTION;


-- ===================================================================
-- 4. ПОДДЕРЖКА АДМИНСКОГО КАТАЛОГА (Глобальные упражнения)
-- Чтобы отличать общедоступные упражнения от созданных лично пользователем,
-- поле id_user в таблице упражнений теперь может принимать значение NULL (значит, упражнение общее)
-- ===================================================================
ALTER TABLE GTB_workout_exercises ALTER COLUMN id_user INT NULL;