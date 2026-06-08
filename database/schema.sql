-- 1. Сначала вручную удаляем зависимый объект-ограничение
ALTER TABLE GTB_workouts
DROP CONSTRAINT DF__GTB_worko__total__4924D839;

-- 2. И теперь спокойно удаляем саму колонку total_tonnage
ALTER TABLE GTB_workouts
DROP COLUMN total_tonnage;