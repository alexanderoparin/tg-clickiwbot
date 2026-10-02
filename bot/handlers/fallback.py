"""Подключается последним: устаревшие кнопки и непонятные сообщения."""
from aiogram import Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards import main_menu

router = Router(name="fallback")


@router.callback_query()
async def stale_button(cb: CallbackQuery) -> None:
    await cb.answer("Кнопка устарела — начни заново из меню.", show_alert=True)


@router.message()
async def unknown(message: Message) -> None:
    await message.answer("Выбери действие в меню.", reply_markup=main_menu())
