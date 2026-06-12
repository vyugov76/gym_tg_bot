"""
screen_message - единое экранное сообщение бота

Хранит chat_id и message_id в FSM, чтобы после ввода текста
редактировать одно сообщение вместо отправки новых.
"""

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

SCREEN_CHAT_KEY = "screen_chat_id"
SCREEN_MESSAGE_KEY = "screen_message_id"


async def store_screen_message(state: FSMContext, message: Message) -> None:
    """
    Сохраняет идентификаторы экранного сообщения в FSM.

    Параметры:
        state: контекст FSM
        message: сообщение бота для последующего edit_text
    """
    await state.update_data(
        **{
            SCREEN_CHAT_KEY: message.chat.id,
            SCREEN_MESSAGE_KEY: message.message_id,
        }
    )


async def edit_screen_message(
    bot,
    state: FSMContext,
    text: str,
    reply_markup=None,
) -> bool:
    """
    Редактирует сохранённое экранное сообщение.

    Параметры:
        bot: экземпляр бота aiogram
        state: контекст FSM с screen_chat_id и screen_message_id
        text: новый текст сообщения
        reply_markup: новая inline-клавиатура

    Возвращает:
        True, если сообщение успешно отредактировано
    """
    data = await state.get_data()
    chat_id = data.get(SCREEN_CHAT_KEY)
    message_id = data.get(SCREEN_MESSAGE_KEY)
    if not chat_id or not message_id:
        return False

    try:
        await bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest:
        return False
    return True


async def show_screen_callback(
    callback: CallbackQuery,
    state: FSMContext,
    text: str,
    reply_markup=None,
) -> None:
    """
    Обновляет экран через edit_text callback-сообщения.

    Параметры:
        callback: callback-запрос с сообщением бота
        state: контекст FSM
        text: текст экрана
        reply_markup: inline-клавиатура
    """
    await callback.message.edit_text(text, reply_markup=reply_markup)
    await store_screen_message(state, callback.message)


async def show_screen_message(
    message: Message,
    state: FSMContext,
    text: str,
    reply_markup=None,
) -> None:
    """
    Обновляет экран после текстового ввода пользователя.

    Сначала пробует edit сохранённого сообщения, иначе отправляет новое.

    Параметры:
        message: сообщение пользователя из FSM
        state: контекст FSM
        text: текст экрана
        reply_markup: inline-клавиатура
    """
    if await edit_screen_message(message.bot, state, text, reply_markup):
        return
    sent = await message.answer(text, reply_markup=reply_markup)
    await store_screen_message(state, sent)
