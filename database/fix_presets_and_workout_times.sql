-- Индекс для быстрого поиска тренировок конкретного пользователя по шаблонам и дате
CREATE NONCLUSTERED INDEX IX_GTB_workouts_user_preset_date
ON dbo.GTB_workouts (id_user, id_preset, started_at)
INCLUDE (finished_at);

-- Индекс для мгновенной выборки всех упражнений конкретной тренировочной сессии
CREATE NONCLUSTERED INDEX IX_GTB_workout_exercises_workout_user
ON dbo.GTB_workout_exercises (workout_id, id_user)
INCLUDE (exercise_name, is_bodyweight, category_id);

-- Индекс для вычитки всех подходов по ID упражнения
CREATE NONCLUSTERED INDEX IX_GTB_sets_exercise_number
ON dbo.GTB_sets (id_workout_exercise, set_number)
INCLUDE (weight, reps, duration_seconds);