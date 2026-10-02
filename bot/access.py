"""Middleware: доступ (открытый режим / whitelist) и анти-флуд."""
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class AccessMiddleware(BaseMiddleware):
    """Пустой `allowed` — открыто для всех. Иначе только `allowed` и `admins`."""

    def __init__(self, allowed: set[int], admins: set[int] = frozenset()):
        self.allowed = set(allowed) | set(admins) if allowed else set()

    def is_allowed(self, user_id: int) -> bool:
        return not self.allowed or user_id in self.allowed

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is None or not self.is_allowed(user.id):
            if isinstance(event, Message):
                await event.answer("Нет доступа")
            elif isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            return None
        return await handler(event, data)


class ThrottleMiddleware(BaseMiddleware):
    """Не чаще одного сообщения в `interval` секунд от пользователя.
    Лишние сообщения отбрасываются; предупреждаем не чаще раза в `warn_every` секунд."""

    def __init__(self, interval: float, warn_every: float = 5.0,
                 clock: Callable[[], float] = time.monotonic):
        self.interval = interval
        self.warn_every = warn_every
        self.clock = clock
        self.last: dict[int, float] = {}
        self.last_warn: dict[int, float] = {}

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is None or self.interval <= 0:
            return await handler(event, data)
        now = self.clock()
        prev = self.last.get(user.id)
        if prev is not None and now - prev < self.interval:
            if isinstance(event, Message) and now - self.last_warn.get(user.id, -1e9) >= self.warn_every:
                self.last_warn[user.id] = now
                await event.answer("⏳ Не так быстро — не чаще одного сообщения в секунду.")
            return None
        self.last[user.id] = now
        return await handler(event, data)
