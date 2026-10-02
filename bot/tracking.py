"""База пользователей и воронка.

- `track()` — единственная точка записи событий. Ошибка записи не ломает сценарий: warning в лог.
- `UserMiddleware` — при каждом сообщении/нажатии обновляет профиль (username, имя, last_seen)
  и уведомляет админов о новом пользователе (флаг NOTIFY_NEW_USERS).
- `notify_admins()` — сообщение всем ADMIN_IDS; недоступный админ не мешает остальным.
"""
from __future__ import annotations

import html
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.types import TelegramObject, User

import config
from storage.db import Database

log = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


async def track(db: Database, user_id: int, event: str, meta: dict | None = None) -> None:
    """Записать событие воронки. Никогда не бросает исключений."""
    try:
        await db.add_event(user_id, event, meta)
    except Exception:
        log.warning("user %s: не удалось записать событие %s", user_id, event, exc_info=True)


async def notify_admins(bot: Bot, text: str) -> None:
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            log.warning("Не удалось уведомить админа %s", admin_id, exc_info=True)


def user_label(first_name: str | None, last_name: str | None, username: str | None) -> str:
    name = " ".join(p for p in (first_name, last_name) if p) or "Без имени"
    at = f"@{username}" if username else "(без username)"
    return f"{html.escape(name)} {html.escape(at)}"


class UserMiddleware(BaseMiddleware):
    """Подключается после доступа и анти-флуда: учитываем только тех, кого бот обслуживает."""

    def __init__(self, db: Database):
        self.db = db

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user: User | None = data.get("event_from_user")
        if user is not None and not user.is_bot:
            try:
                is_new = await self.db.upsert_user(user.id, user.username, user.first_name,
                                                   user.last_name, user.language_code)
            except Exception:
                log.warning("user %s: не удалось обновить профиль", user.id, exc_info=True)
                is_new = False
            if is_new and config.NOTIFY_NEW_USERS:
                bot: Bot | None = data.get("bot")
                if bot is not None:
                    await notify_admins(bot, "👤 Новый пользователь: "
                                        + user_label(user.first_name, user.last_name, user.username))
        return await handler(event, data)
