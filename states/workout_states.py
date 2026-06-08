"""FSM-состояния для регистрации, тренировки и управления упражнениями."""

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """Пошаговая регистрация нового пользователя."""

    height = State()
    weight = State()


class WorkoutStates(StatesGroup):
    """Процесс записи тренировки."""

    choosing_exercise = State()
    entering_set = State()


class ExerciseStates(StatesGroup):
    """Создание нового упражнения."""

    waiting_for_name = State()
    waiting_for_type = State()


class EditExerciseStates(StatesGroup):
    """Редактирование упражнения в профиле."""

    waiting_for_new_name = State()


class ProfileEditStates(StatesGroup):
    """Редактирование роста и веса в профиле."""

    waiting_for_height = State()
    waiting_for_weight = State()


class WorkoutEditStates(StatesGroup):
    """Пошаговое редактирование подхода в завершённой тренировке."""

    waiting_for_exercise_number = State()
    waiting_for_set_number = State()
    waiting_for_new_value = State()
