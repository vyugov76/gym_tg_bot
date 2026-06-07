-- Удаляем старые таблицы (в обратном порядке из-за связей)
IF OBJECT_ID(N'dbo.GTB_sets', N'U') IS NOT NULL DROP TABLE GTB_sets;
IF OBJECT_ID(N'dbo.GTB_workout_exercises', N'U') IS NOT NULL DROP TABLE GTB_workout_exercises;
IF OBJECT_ID(N'dbo.GTB_workouts', N'U') IS NOT NULL DROP TABLE GTB_workouts;
IF OBJECT_ID(N'dbo.GTB_users', N'U') IS NOT NULL DROP TABLE GTB_users;
GO

-- 1. Пользователи
CREATE TABLE GTB_users (
    id_user INT IDENTITY(1, 1) PRIMARY KEY,
    telegram_id BIGINT NOT NULL UNIQUE,
    height DECIMAL(5, 2) NOT NULL,
    weight DECIMAL(5, 2) NOT NULL,
    created_at DATETIME2 NOT NULL DEFAULT SYSDATETIME()
);
GO

-- 2. Тренировки
CREATE TABLE GTB_workouts (
    id_workout INT IDENTITY(1, 1) PRIMARY KEY,
    user_id INT NOT NULL,
    started_at DATETIME2 NOT NULL DEFAULT SYSDATETIME(),
    finished_at DATETIME2 NULL,
    total_tonnage DECIMAL(12, 2) NOT NULL DEFAULT 0,
    CONSTRAINT FK_GTB_workouts_GTB_users FOREIGN KEY (user_id)
        REFERENCES GTB_users(id_user)
);
GO

-- 3. Упражнения в тренировке (без category)
CREATE TABLE GTB_workout_exercises (
    id_workout_exercise INT IDENTITY(1, 1) PRIMARY KEY,
    workout_id INT NOT NULL,
    user_id INT NOT NULL,
    exercise_name NVARCHAR(100) NOT NULL,
    is_bodyweight BIT NOT NULL DEFAULT 0,
    CONSTRAINT FK_GTB_workout_exercises_GTB_workouts FOREIGN KEY (workout_id)
        REFERENCES GTB_workouts(id_workout),
    CONSTRAINT FK_GTB_workout_exercises_GTB_users FOREIGN KEY (user_id)
        REFERENCES GTB_users(id_user)
);
GO

-- 4. Подходы (weight NULL — собственный вес)
CREATE TABLE GTB_sets (
    id_set INT IDENTITY(1, 1) PRIMARY KEY,
    workout_exercise_id INT NOT NULL,
    set_number INT NOT NULL,
    weight DECIMAL(6, 2) NULL,
    reps INT NOT NULL,
    CONSTRAINT FK_GTB_sets_GTB_workout_exercises FOREIGN KEY (workout_exercise_id)
        REFERENCES GTB_workout_exercises(id_workout_exercise) ON DELETE CASCADE
);
GO
