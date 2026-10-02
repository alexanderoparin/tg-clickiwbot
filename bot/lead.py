"""Заявки на бесплатный разбор.

После каждого анализа — сообщение с одной inline-кнопкой «🙋 Хочу бесплатный разбор».
- Телефона ещё нет → просим контакт (reply-кнопка «📱 Оставить контакт», строка о согласии).
  Принимаем только контакт самого пользователя; получили → «🔥 Новый лид» всем ADMIN_IDS.
- Телефон уже есть → заявка принята сразу, «🔥 Заявка на разбор» всем ADMIN_IDS.
"""
from __future__ import annotations

import html
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message, User

import config
from bot import texts
from bot.keyboards import CB_LEAD_REVIEW, lead_kb, lead_offer_kb, main_menu
from bot.tracking import notify_admins, track, user_label
from storage.db import Database

log = logging.getLogger(__name__)
router = Router(name="lead")


async def offer_review(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Сообщение с кнопкой «🙋 Хочу бесплатный разбор» — после каждого анализа.
    Ошибка отправки не ломает выдачу результата."""
    try:
        await bot.send_message(chat_id, texts.LEAD_ASK, reply_markup=lead_offer_kb())
        return True
    except Exception:
        log.warning("user %s: не удалось предложить разбор", user_id, exc_info=True)
        return False


async def _lead_summary(db: Database, u: User, phone: str) -> str:
    info = await db.get_user(u.id)
    analyses = info.analyses if info else 0
    last = html.escape(info.last_label) if info and info.last_label else "без названия"
    return (f"{user_label(u.first_name, u.last_name, u.username)} {html.escape(phone)}, "
            f"анализов: {analyses}, последний: {last}")


@router.callback_query(F.data == CB_LEAD_REVIEW)
async def want_review(cb: CallbackQuery, bot: Bot, db: Database) -> None:
    await cb.answer()
    u = cb.from_user
    await track(db, u.id, "lead_request")
    info = await db.get_user(u.id)
    if info is not None and info.phone:
        # контакт уже есть — заявка сразу, без повторного запроса телефона
        await cb.message.answer(texts.LEAD_THANKS, reply_markup=main_menu())
        await notify_admins(bot, "🔥 Заявка на разбор: " + await _lead_summary(db, u, info.phone))
        return
    await cb.message.answer(texts.lead_contact_ask(config.PRIVACY_URL), reply_markup=lead_kb(),
                            link_preview_options=LinkPreviewOptions(is_disabled=True))
    await db.mark_lead_requested(u.id)


@router.message(F.contact)
async def got_contact(message: Message, bot: Bot, db: Database) -> None:
    contact = message.contact
    if contact.user_id != message.from_user.id:
        # пересланный или чужой контакт — не принимаем
        await message.answer(texts.LEAD_FOREIGN_CONTACT, reply_markup=lead_kb())
        return
    phone = contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await db.set_phone(message.from_user.id, phone)
    await track(db, message.from_user.id, "lead_contact")
    await message.answer(texts.LEAD_THANKS, reply_markup=main_menu())

    await notify_admins(bot, "🔥 Новый лид: " + await _lead_summary(db, message.from_user, phone))


@router.message(F.text == texts.BTN_LEAD_LATER)
async def lead_later(message: Message) -> None:
    await message.answer(texts.LEAD_LATER, reply_markup=main_menu())
