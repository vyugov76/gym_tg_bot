-- ===================================================================
-- 3. ИСПРАВЛЕНИЕ ТАБЛИЦЫ GTB_workout_exercises (Безопасный вариант)
-- ===================================================================
-- Создаем внешний ключ БЕЗ ON DELETE CASCADE (используем NO ACTION)
IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_GTB_workout_exercises_Users')
    ALTER TABLE GTB_workout_exercises ADD CONSTRAINT FK_GTB_workout_exercises_Users 
    FOREIGN KEY (id_user) REFERENCES GTB_users(id_user) ON DELETE NO ACTION;


-- ===================================================================
-- 4. ИСПРАВЛЕНИЕ ТАБЛИЦЫ GTB_preset_workouts
-- ===================================================================
-- Если этот блок не успел выполниться в прошлый раз из-за ошибки выше:
DECLARE @SqlPresets NVARCHAR(MAX) = (
    SELECT 'ALTER TABLE GTB_preset_workouts DROP CONSTRAINT ' + name
    FROM sys.foreign_keys
    WHERE parent_object_id = OBJECT_ID('GTB_preset_workouts') 
      AND referenced_object_id = OBJECT_ID('GTB_users')
);
IF @SqlPresets IS NOT NULL EXEC sp_executesql @SqlPresets;

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('GTB_preset_workouts') AND name = 'user_id')
    EXEC sp_rename 'GTB_preset_workouts.user_id', 'id_user', 'COLUMN';

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_GTB_preset_workouts_Users')
    ALTER TABLE GTB_preset_workouts ADD CONSTRAINT FK_GTB_preset_workouts_Users 
    FOREIGN KEY (id_user) REFERENCES GTB_users(id_user) ON DELETE CASCADE;


-- ===================================================================
-- 5. ИСПРАВЛЕНИЕ ТАБЛИЦЫ GTB_preset_exercises
-- ===================================================================
DECLARE @SqlPresetEx NVARCHAR(MAX) = (
    SELECT 'ALTER TABLE GTB_preset_exercises DROP CONSTRAINT ' + name
    FROM sys.foreign_keys
    WHERE parent_object_id = OBJECT_ID('GTB_preset_exercises') 
      AND referenced_object_id = OBJECT_ID('GTB_preset_workouts')
);
IF @SqlPresetEx IS NOT NULL EXEC sp_executesql @SqlPresetEx;

IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('GTB_preset_exercises') AND name = 'preset_id')
    EXEC sp_rename 'GTB_preset_exercises.preset_id', 'id_preset', 'COLUMN';

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = 'FK_GTB_preset_exercises_Presets')
    ALTER TABLE GTB_preset_exercises ADD CONSTRAINT FK_GTB_preset_exercises_Presets 
    FOREIGN KEY (id_preset) REFERENCES GTB_preset_workouts(id_preset) ON DELETE CASCADE;


-- ===================================================================
-- 6. ИСПРАВЛЕНИЕ ТАБЛИЦЫ GTB_sets
-- ===================================================================
IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('GTB_sets') AND name = 'workout_exercise_id')
    EXEC sp_rename 'GTB_sets.workout_exercise_id', 'id_workout_exercise', 'COLUMN';