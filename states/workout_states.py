"""FSM-состояния для регистрации, тренировки и управления упражнениями."""

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """Пошаговая регистрация нового пользователя."""

    height = State()
    weight = State()


class WorkoutStates(StatesGroup):
    """Процесс записи тренировки."""

    choosing_exercise = State()
    waiting_for_set_value = State()
    waiting_for_template_name = State()


class ExerciseStates(StatesGroup):
    """Создание нового упражнения."""

    waiting_for_name = State()
    waiting_for_type = State()
    waiting_for_category = State()


class CategoryStates(StatesGroup):
    """Создание категории упражнений."""

    waiting_for_name = State()


class PresetSaveStates(StatesGroup):
    """Сохранение завершённой тренировки как пресета."""

    waiting_for_name = State()


class PresetCreateStates(StatesGroup):
    """Создание пустого шаблона тренировки в настройках."""

    waiting_for_name = State()


class PresetBulkAddStates(StatesGroup):
    """Пошаговое добавление упражнений в шаблон с указанием подходов."""

    waiting_for_sets_count = State()


class TemplateEditStates(StatesGroup):
    """Точечное редактирование количества подходов в существующем шаблоне."""

    waiting_for_exercise_selection = State()
    waiting_for_sets_count = State()


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
