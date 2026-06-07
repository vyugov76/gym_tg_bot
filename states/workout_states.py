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
