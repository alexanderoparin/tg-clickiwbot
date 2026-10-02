"""«📚 Полезные материалы»: PDF из assets/materials/ со списком в bot/texts.py → MATERIALS.

Каждый PDF — отдельный документ с подписью = title. Кеш file_id — тот же, что у видео
(data/media_cache.json, ключ «material:{файл}»), сброс при изменении размера или даты.
Нет файла — пропускаем, warning в лог. Повтор в течение MATERIALS_REPEAT_SEC — не шлём заново.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from aiogram import Bot
from aiogram.types import LinkPreviewOptions

from bot import texts
from bot.media import MediaSender

log = logging.getLogger(__name__)


@dataclass
class Material:
    file: str
    title: str
    sender: MediaSender


class Materials:
    def __init__(self, folder: Path | str, cache_path: Path | str, items: list[dict] | None = None,
                 repeat_sec: float = 60, clock: Callable[[], float] = time.monotonic):
        folder = Path(folder)
        self.items = [
            Material(m["file"], m["title"],
                     MediaSender(folder / m["file"], cache_path, key=f"material:{m['file']}",
                                 kind="document"))
            for m in (texts.MATERIALS if items is None else items)
        ]
        self.repeat_sec = repeat_sec
        self.clock = clock
        self._last_sent: dict[int, float] = {}

    def recently_sent(self, user_id: int) -> bool:
        last = self._last_sent.get(user_id)
        return last is not None and self.clock() - last < self.repeat_sec

    async def send(self, bot: Bot, chat_id: int, user_id: int) -> int:
        """Отправить вступление и все доступные PDF. Возвращает число отправленных файлов."""
        available = []
        for m in self.items:
            if m.sender.video_path.is_file():
                available.append(m)
            else:
                log.warning("Нет файла материала %s — пропускаю", m.sender.video_path)
        if not available:
            await bot.send_message(chat_id, texts.MATERIALS_EMPTY)
            return 0

        await bot.send_message(chat_id, texts.MATERIALS_INTRO,
                               link_preview_options=LinkPreviewOptions(is_disabled=True))
        sent = 0
        for m in available:
            if await m.sender.deliver(bot, chat_id, m.title) is not None:
                sent += 1
            else:
                log.warning("Не удалось отправить материал %s", m.file)
        if sent:
            self._last_sent[user_id] = self.clock()
        return sent
