"""FSM-состояния для регистрации и записи тренировки."""

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """Пошаговая регистрация нового пользователя."""

    height = State()  # Ввод роста (см)
    weight = State()  # Ввод веса (кг)


class WorkoutStates(StatesGroup):
    """Процесс записи тренировки."""

    choosing_category = State()   # Выбор категории упражнения
    choosing_exercise = State()   # Выбор конкретного упражнения
    entering_set = State()        # Ввод подхода в формате вес/повторения
