"""
workout_states - FSM-состояния aiogram для сценариев бота

Группы состояний для регистрации, записи тренировок, управления
упражнениями, шаблонами и редактирования профиля.

Ключевые компоненты:
- RegistrationStates - регистрация роста и веса
- WorkoutStates - выбор упражнения и ввод подходов
- ExerciseStates, CategoryStates - создание упражнений и категорий
- PresetSaveStates, PresetCreateStates, PresetBulkAddStates - шаблоны
- TemplateEditStates - редактирование подходов в шаблоне
- EditExerciseStates, ProfileEditStates, WorkoutEditStates - правки данных
"""

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    """
    Пошаговая регистрация нового пользователя.

    Состояния:
        height - ожидание ввода роста
        weight - ожидание ввода веса
    """

    height = State()
    weight = State()


class WorkoutStates(StatesGroup):
    """
    Процесс записи активной тренировки.

    Состояния:
        choosing_exercise - выбор упражнения или категории
        waiting_for_set_value - ввод значения подхода
        waiting_for_template_name - имя шаблона при сохранении программы
    """

    choosing_exercise = State()
    waiting_for_set_value = State()
    waiting_for_template_name = State()


class ExerciseStates(StatesGroup):
    """
    Создание нового упражнения в настройках.

    Состояния:
        waiting_for_name - ввод названия упражнения
        waiting_for_type - выбор типа (отягощение, вес, время)
        waiting_for_category - выбор категории
    """

    waiting_for_name = State()
    waiting_for_type = State()
    waiting_for_category = State()


class CategoryStates(StatesGroup):
    """
    Создание категории упражнений.

    Состояния:
        waiting_for_name - ввод названия категории
        waiting_for_rename - ввод нового названия существующей категории
    """

    waiting_for_name = State()
    waiting_for_rename = State()


class PresetSaveStates(StatesGroup):
    """
    Сохранение завершённой тренировки как шаблона.

    Состояния:
        waiting_for_name - ввод имени нового шаблона
    """

    waiting_for_name = State()


class PresetCreateStates(StatesGroup):
    """
    Создание пустого шаблона тренировки в настройках.

    Состояния:
        waiting_for_name - ввод имени шаблона
    """

    waiting_for_name = State()


class PresetBulkAddStates(StatesGroup):
    """
    Пошаговое добавление упражнений в шаблон с указанием подходов.

    Состояния:
        waiting_for_sets_count - ввод числа подходов для текущего упражнения
    """

    waiting_for_sets_count = State()


class TemplateEditStates(StatesGroup):
    """
    Точечное редактирование количества подходов в существующем шаблоне.

    Состояния:
        waiting_for_exercise_selection - выбор упражнения в шаблоне
        waiting_for_sets_count - новое число подходов
    """

    waiting_for_exercise_selection = State()
    waiting_for_sets_count = State()


class EditExerciseStates(StatesGroup):
    """
    Редактирование названия упражнения в профиле.

    Состояния:
        waiting_for_new_name - ввод нового названия
    """

    waiting_for_new_name = State()


class ProfileEditStates(StatesGroup):
    """
    Редактирование роста и веса в профиле пользователя.

    Состояния:
        waiting_for_height - ввод нового роста
        waiting_for_weight - ввод нового веса
    """

    waiting_for_height = State()
    waiting_for_weight = State()


class WorkoutEditStates(StatesGroup):
    """
    Пошаговое редактирование подхода в завершённой тренировке.

    Состояния:
        waiting_for_exercise_number - номер упражнения в отчёте
        waiting_for_set_number - номер подхода
        waiting_for_new_value - новое значение подхода
    """

    waiting_for_exercise_number = State()
    waiting_for_set_number = State()
    waiting_for_new_value = State()
