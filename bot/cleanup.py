"""Удаление видео-подсказок, чтобы они не копились в чате.

- Видео шага «Новый анализ» (how_to_download, how_to_price): message_id — в FSM data.
  При переходе на следующий шаг видео удаляется, вместо него — короткая строка
  («📄 Файл: …», «💰 Цена реализации: …»). При отмене и выходе в меню — просто удаляется.
- Сообщения инструкции хранятся в БД (переживают перезапуск), при повторном открытии
  прошлые удаляются.
- Ошибки удаления (старше 48 часов, уже удалено и т. п.) не ломают бота: debug в лог.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

log = logging.getLogger(__name__)

STEP_MEDIA_KEY = "step_media_id"


async def safe_delete(bot: Bot, chat_id: int, message_id: int) -> bool:
    try:
        await bot.delete_message(chat_id, message_id)
        return True
    except Exception as e:
        log.debug("Не удалось удалить сообщение %s в чате %s: %s", message_id, chat_id, e)
        return False


async def remember_step_media(state: FSMContext, msg: Message | None) -> None:
    """Запомнить видео текущего шага (или текст-фолбэк вместо него)."""
    await state.update_data({STEP_MEDIA_KEY: msg.message_id if msg else None})


async def drop_step_media(state: FSMContext, bot: Bot, chat_id: int,
                          note: str | None = None) -> None:
    """Удалить видео текущего шага; `note` — короткая строка вместо него."""
    data = await state.get_data()
    message_id = data.get(STEP_MEDIA_KEY)
    if message_id:
        await safe_delete(bot, chat_id, message_id)
        await state.update_data({STEP_MEDIA_KEY: None})
    if note:
        await bot.send_message(chat_id, note)


async def leave_flow(state: FSMContext, bot: Bot, chat_id: int) -> None:
    """Выход из сценария (отмена, меню, /start): убрать видео шага и сбросить состояние."""
    await drop_step_media(state, bot, chat_id)
    await state.clear()
