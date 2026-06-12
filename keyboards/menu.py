"""
Назначение: inline- и reply-клавиатуры бота для меню, настроек и тренировок.

Ключевые компоненты:
- main_menu_keyboard, settings_menu_keyboard - главное меню и настройки
- categories_list_keyboard - управление категориями
- presets_list_keyboard, preset_detail_keyboard - готовые тренировки
- workout_start_choice_keyboard, workout_categories_keyboard - сценарий тренировки
- after_set_keyboard, preset_after_set_keyboard - действия после подхода
- my_exercises_keyboard, exercise_manage_keyboard - каталог упражнений
- profile_keyboard - редактирование профиля
"""

from typing import Any

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from utils.exercise_types import EXERCISE_ICONS, NEXT_TYPE_BUTTON, normalize_exercise_type
from utils.preset_helpers import preset_button_text


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Reply-клавиатура главного меню бота.

    Возвращает:
        ReplyKeyboardMarkup: кнопки старта тренировки, статистики и настроек.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🏋️ Начать тренировку")],
            [KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие…",
    )


def settings_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Inline-меню раздела настроек.

    Возвращает:
        InlineKeyboardMarkup: переходы к упражнениям, шаблонам и профилю.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📂 Мои упражнения",
                callback_data="settings:categories",
            )],
            [InlineKeyboardButton(
                text="📋 Мои готовые тренировки",
                callback_data="settings:presets",
            )],
            [InlineKeyboardButton(
                text="👤 Профиль",
                callback_data="settings:profile",
            )],
        ]
    )


def categories_list_keyboard(categories: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Список категорий упражнений в настройках.

    Параметры:
        categories: список категорий с полями id и name.

    Возвращает:
        InlineKeyboardMarkup: категории, несортированные, создание и возврат.
    """
    buttons = [
        [InlineKeyboardButton(
            text=f"📂 {cat['name']}",
            callback_data=f"cat:view:{cat['id']}",
        )]
        for cat in categories
    ]
    buttons.append([InlineKeyboardButton(
        text="📁 Несортированные",
        callback_data="cat:unsorted",
    )])
    buttons.append([InlineKeyboardButton(
        text="➕ Создать категорию",
        callback_data="cat:create",
    )])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад в настройки",
        callback_data="settings:back",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def presets_list_keyboard(presets: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Список готовых тренировок в настройках.

    Параметры:
        presets: список шаблонов с полями id и именем.

    Возвращает:
        InlineKeyboardMarkup: шаблоны, создание нового и возврат в настройки.
    """
    buttons = [
        [InlineKeyboardButton(
            text=preset_button_text(preset),
            callback_data=f"preset:view:{preset['id']}",
        )]
        for preset in presets
    ]
    if not buttons:
        buttons.append([InlineKeyboardButton(
            text="Пока нет готовых тренировок",
            callback_data="preset:noop",
        )])
    buttons.append([InlineKeyboardButton(
        text="➕ Создать шаблон",
        callback_data="preset:create",
    )])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад в настройки",
        callback_data="settings:back",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def template_edit_sets_keyboard(
    preset_id: int,
    exercises: list[dict[str, Any]],
) -> InlineKeyboardMarkup:
    """
    Выбор упражнения для изменения количества подходов в шаблоне.

    Параметры:
        preset_id: идентификатор шаблона.
        exercises: упражнения шаблона с полем name.

    Возвращает:
        InlineKeyboardMarkup: нумерованный список упражнений и кнопка завершения.
    """
    buttons = [
        [InlineKeyboardButton(
            text=f"{idx}) {ex['name']}",
            callback_data=f"preset:edit_sets:pick:{preset_id}:{idx - 1}",
        )]
        for idx, ex in enumerate(exercises, start=1)
    ]
    buttons.append([InlineKeyboardButton(
        text="✅ Готово / Назад",
        callback_data=f"preset:edit_sets:done:{preset_id}",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def preset_detail_keyboard(preset_id: int) -> InlineKeyboardMarkup:
    """
    Действия внутри готовой тренировки.

    Параметры:
        preset_id: идентификатор шаблона.

    Возвращает:
        InlineKeyboardMarkup: редактирование состава, подходов и удаление шаблона.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="➕ Добавить упражнения",
                callback_data=f"preset:bulk_add:{preset_id}",
            )],
            [InlineKeyboardButton(
                text="➖ Удалить упражнения",
                callback_data=f"preset:bulk_rm:{preset_id}",
            )],
            [InlineKeyboardButton(
                text="✏️ Изменить подходы",
                callback_data=f"preset:edit_sets:{preset_id}",
            )],
            [InlineKeyboardButton(
                text="❌ Удалить тренировку",
                callback_data=f"preset:delete:{preset_id}",
            )],
            [InlineKeyboardButton(
                text="◀️ К списку программ",
                callback_data="settings:presets",
            )],
        ]
    )


def workout_start_choice_keyboard() -> InlineKeyboardMarkup:
    """
    Выбор режима старта тренировки при наличии пресетов.

    Возвращает:
        InlineKeyboardMarkup: пустая тренировка или выбор готовой программы.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="📝 Начать пустую тренировку",
                callback_data="workout:start:empty",
            )],
            [InlineKeyboardButton(
                text="📋 Выбрать готовую программу",
                callback_data="workout:start:preset_list",
            )],
        ]
    )


def workout_preset_list_keyboard(presets: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Список пресетов для старта тренировки.

    Параметры:
        presets: доступные шаблоны с полем id.

    Возвращает:
        InlineKeyboardMarkup: кнопки шаблонов и возврат к выбору режима.
    """
    buttons = [
        [InlineKeyboardButton(
            text=preset_button_text(preset),
            callback_data=f"workout:start:preset:{preset['id']}",
        )]
        for preset in presets
    ]
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="workout:start:back",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _exercise_icon(exercise: dict[str, Any]) -> str:
    """
    Эмодзи-иконка типа упражнения.

    Параметры:
        exercise: словарь упражнения с exercise_type или is_bodyweight.

    Возвращает:
        str: символ из EXERCISE_ICONS или значение по умолчанию.
    """
    exercise_type = normalize_exercise_type(
        exercise.get("exercise_type", exercise.get("is_bodyweight", 0))
    )
    return EXERCISE_ICONS.get(exercise_type, "🏋️‍♂️")


def workout_categories_keyboard(categories: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Выбор категории при добавлении упражнения в тренировку.

    Параметры:
        categories: список категорий с полями id и name.

    Возвращает:
        InlineKeyboardMarkup: категории, несортированные, создание и завершение.
    """
    buttons = [
        [InlineKeyboardButton(
            text=f"📂 {cat['name']}",
            callback_data=f"wex:cat:{cat['id']}",
        )]
        for cat in categories
    ]
    buttons.append([InlineKeyboardButton(
        text="📁 Несортированные",
        callback_data="wex:unsorted",
    )])
    buttons.append([InlineKeyboardButton(
        text="➕ Создать новое упражнение",
        callback_data="ex:create",
    )])
    buttons.append([InlineKeyboardButton(
        text="✅ Завершить тренировку",
        callback_data="set:finish",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def workout_exercises_keyboard(
    exercises: list[dict[str, Any]],
    *,
    back_callback: str = "wex:back_cats",
    show_finish: bool = True,
) -> InlineKeyboardMarkup:
    """
    Список упражнений внутри категории для тренировки.

    Параметры:
        exercises: упражнения категории с полем name.
        back_callback: callback_data кнопки возврата к категориям.
        show_finish: показывать ли кнопку завершения тренировки.

    Возвращает:
        InlineKeyboardMarkup: упражнения с иконками, создание и навигация.
    """
    buttons = []
    for idx, ex in enumerate(exercises):
        icon = _exercise_icon(ex)
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {ex['name']}",
            callback_data=f"ex:select:{idx}",
        )])
    if not exercises:
        buttons.append([InlineKeyboardButton(
            text="В этой категории пока нет упражнений",
            callback_data="ex:noop",
        )])
    buttons.append([InlineKeyboardButton(
        text="➕ Создать новое упражнение",
        callback_data="ex:create",
    )])
    buttons.append([InlineKeyboardButton(
        text="◀️ К категориям",
        callback_data=back_callback,
    )])
    if show_finish:
        buttons.append([InlineKeyboardButton(
            text="✅ Завершить тренировку",
            callback_data="set:finish",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def exercise_category_keyboard(categories: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """
    Выбор категории при создании нового упражнения.

    Параметры:
        categories: список категорий с полями id и name.

    Возвращает:
        InlineKeyboardMarkup: категории и вариант без категории.
    """
    buttons = [
        [InlineKeyboardButton(
            text=f"📂 {cat['name']}",
            callback_data=f"ex:cat:{cat['id']}",
        )]
        for cat in categories
    ]
    buttons.append([InlineKeyboardButton(
        text="Оставить без категории (Несортированное)",
        callback_data="ex:cat:none",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def exercise_type_keyboard() -> InlineKeyboardMarkup:
    """
    Выбор типа упражнения при создании.

    Возвращает:
        InlineKeyboardMarkup: с отягощением, с весом тела или на время.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏋️‍♂️ С отягощением", callback_data="ex:type:0")],
            [InlineKeyboardButton(text="🤸‍♂️ С собственным весом", callback_data="ex:type:1")],
            [InlineKeyboardButton(text="⏱️ На время", callback_data="ex:type:2")],
        ]
    )


def after_set_keyboard(*, show_preset_next: bool = False) -> InlineKeyboardMarkup:
    """
    Действия после записи подхода в свободной тренировке.

    Параметры:
        show_preset_next: True - кнопка «Следующее упражнение», иначе «Другое упражнение».

    Возвращает:
        InlineKeyboardMarkup: исправление, повтор, смена упражнения и завершение.
    """
    next_ex_text = "➡️ Следующее упражнение" if show_preset_next else "🔄 Другое упражнение"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✏️ Исправить последний подход",
                callback_data="set:edit_last",
            )],
            [InlineKeyboardButton(text="➕ Ещё подход", callback_data="set:more")],
            [InlineKeyboardButton(text=next_ex_text, callback_data="set:next_ex")],
            [InlineKeyboardButton(
                text="✅ Завершить тренировку",
                callback_data="set:finish",
            )],
        ]
    )


def preset_after_set_keyboard(
    *,
    show_extra_menu: bool = False,
    completed_sets: int = 0,
    planned_sets: int = 0,
    show_preset_next: bool = True,
) -> InlineKeyboardMarkup:
    """
    Двухуровневые действия после подхода в тренировке по шаблону.

    Параметры:
        show_extra_menu: показать расширенное меню дополнительных действий.
        completed_sets: число выполненных подходов текущего упражнения.
        planned_sets: запланированное число подходов по шаблону.
        show_preset_next: True - кнопка «Следующее упражнение», иначе «Другое упражнение».

    Возвращает:
        InlineKeyboardMarkup: компактное или расширенное меню в зависимости от плана.
    """
    next_ex_text = (
        "➡️ Следующее упражнение"
        if show_preset_next
        else "🔄 Другое упражнение"
    )

    if show_extra_menu:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ Ещё подход", callback_data="set:more")],
                [InlineKeyboardButton(text=next_ex_text, callback_data="set:next_ex")],
                [InlineKeyboardButton(
                    text="✅ Завершить тренировку",
                    callback_data="set:finish",
                )],
                [InlineKeyboardButton(text="Назад", callback_data="set:toggle_extra")],
            ]
        )

    plan_complete = planned_sets > 0 and completed_sets >= planned_sets
    if plan_complete:
        buttons: list[list[InlineKeyboardButton]] = [
            [InlineKeyboardButton(
                text="✏️ Исправить последний подход",
                callback_data="set:edit_last",
            )],
            [InlineKeyboardButton(text=next_ex_text, callback_data="set:next_ex")],
            [InlineKeyboardButton(text="...", callback_data="set:toggle_extra")],
        ]
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➡️ Следующий подход",
                    callback_data="set:next_set_step",
                ),
                InlineKeyboardButton(
                    text="✏️ Исправить последний подход",
                    callback_data="set:edit_last",
                ),
            ],
            [InlineKeyboardButton(text="...", callback_data="set:toggle_extra")],
        ]
    )


def extra_set_confirm_keyboard() -> InlineKeyboardMarkup:
    """
    Подтверждение дополнительного подхода сверх плана шаблона.

    Возвращает:
        InlineKeyboardMarkup: подтверждение или отмена добавления подхода.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, добавить",
                    callback_data="set:more:confirm",
                ),
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="set:more:cancel",
                ),
            ],
        ]
    )


def preset_program_complete_keyboard() -> InlineKeyboardMarkup:
    """
    Экран после выполнения всех упражнений программы.

    Возвращает:
        InlineKeyboardMarkup: другое упражнение или завершение тренировки.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🔄 Другое упражнение",
                callback_data="set:next_ex",
            )],
            [InlineKeyboardButton(
                text="✅ Завершить тренировку",
                callback_data="set:finish",
            )],
        ]
    )


def template_save_keyboard() -> InlineKeyboardMarkup:
    """
    Выбор действия при завершении изменённой тренировки по шаблону.

    Возвращает:
        InlineKeyboardMarkup: перезапись, сохранение как новый шаблон или пропуск.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="💾 Перезаписать текущий шаблон",
                callback_data="template:overwrite",
            )],
            [InlineKeyboardButton(
                text="➕ Сохранить как новый шаблон",
                callback_data="template:save_new",
            )],
            [InlineKeyboardButton(
                text="❌ Не сохранять изменения",
                callback_data="template:skip",
            )],
        ]
    )


def my_exercises_keyboard(
    exercises: list[dict[str, Any]],
    *,
    category_token: str,
) -> InlineKeyboardMarkup:
    """
    Список упражнений пользователя в категории настроек.

    Параметры:
        exercises: упражнения с полями id, name и опционально id_user
        category_token: id категории в виде строки или none для несортированных

    Возвращает:
        InlineKeyboardMarkup: упражнения, bulk-действия, создание и управление категорией
    """
    buttons = []
    for ex in exercises:
        icon = _exercise_icon(ex)
        shared = "🌐 " if ex.get("id_user") is None else ""
        buttons.append([InlineKeyboardButton(
            text=f"{shared}{icon} {ex['name']}",
            callback_data=f"myex:view:{ex['id']}",
        )])
    if not buttons:
        empty_text = (
            "Упражнений пока нет"
            if category_token == "none"
            else "Упражнений в этой категории пока нет"
        )
        buttons.append([InlineKeyboardButton(
            text=empty_text,
            callback_data="myex:noop",
        )])
    buttons.append([InlineKeyboardButton(
        text="➕ Создать упражнение",
        callback_data=f"shortcut_add_ex:{category_token}",
    )])
    if category_token != "none":
        category_id = category_token
        buttons.append([
            InlineKeyboardButton(
                text="📥 Добавить из несортированных",
                callback_data=f"cat:bulk_add:{category_id}",
            ),
            InlineKeyboardButton(
                text="📤 Исключить из категории",
                callback_data=f"cat:bulk_rm:{category_id}",
            ),
        ])
        buttons.append([
            InlineKeyboardButton(
                text="✏️ Изменить название",
                callback_data=f"cat:rename:{category_id}",
            ),
            InlineKeyboardButton(
                text="🗑️ Удалить категорию",
                callback_data=f"cat:delete:{category_id}",
            ),
        ])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="settings:categories",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def exercise_manage_keyboard(exercise: dict[str, Any]) -> InlineKeyboardMarkup:
    """
    Меню управления конкретным упражнением.

    Параметры:
        exercise: упражнение с полями id, name, exercise_type и id_user.

    Возвращает:
        InlineKeyboardMarkup: переименование, смена типа и удаление для своих записей.
    """
    exercise_type = normalize_exercise_type(
        exercise.get("exercise_type", exercise.get("is_bodyweight", 0))
    )
    toggle_text = NEXT_TYPE_BUTTON[exercise_type]
    is_owned = exercise.get("id_user") is not None
    buttons: list[list[InlineKeyboardButton]] = []

    if is_owned:
        buttons.extend([
            [InlineKeyboardButton(
                text="✏️ Изменить название",
                callback_data=f"myex:rename:{exercise['id']}",
            )],
            [InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"myex:toggle:{exercise['id']}",
            )],
            [InlineKeyboardButton(
                text="❌ Удалить из каталога",
                callback_data=f"myex:delete:{exercise['id']}",
            )],
        ])
    buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="myex:back_ctx",
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def profile_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопки редактирования профиля пользователя.

    Возвращает:
        InlineKeyboardMarkup: изменение роста, веса и возврат в настройки.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="✏️ Изменить рост",
                callback_data="profile:edit_height",
            )],
            [InlineKeyboardButton(
                text="✏️ Изменить вес",
                callback_data="profile:edit_weight",
            )],
            [InlineKeyboardButton(
                text="◀️ Назад в настройки",
                callback_data="settings:back",
            )],
        ]
    )
