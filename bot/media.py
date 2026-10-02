"""Видео-подсказки (MP4 без звука или GIF) с кешем file_id.

Первый раз файл загружается в Telegram, file_id из ответа сохраняется в JSON-кеш,
дальше видео уходит по file_id. Если файл на диске изменился (размер или дата изменения),
кеш сбрасывается и файл загружается заново. Любая проблема с видео не ломает бота:
вместо анимации уходит текст подписи, в лог — warning.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile, Message

log = logging.getLogger(__name__)

BOT_ID_KEY = "_bot_id"


def reset_cache_for_bot(cache_path: Path | str, bot_id: int) -> bool:
    """file_id действуют только для бота, который загрузил файл. Если кеш сохранён другим ботом
    (сменили BOT_TOKEN), очищаем его и запоминаем id текущего. True — кеш сброшен."""
    cache_path = Path(cache_path)
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if data.get(BOT_ID_KEY) == bot_id:
        return False
    dropped = [k for k in data if k != BOT_ID_KEY]
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({BOT_ID_KEY: bot_id}, indent=2), encoding="utf-8")
    except OSError:
        log.warning("Не удалось сбросить кеш медиа %s", cache_path, exc_info=True)
        return False
    if dropped:
        log.info("Кеш file_id сохранён другим ботом — сброшен (%s записей): %s",
                 len(dropped), ", ".join(dropped))
    return True

class MediaSender:
    def __init__(self, video_path: Path | str, cache_path: Path | str, key: str | None = None,
                 kind: str = "animation"):
        self.video_path = Path(video_path)
        self.cache_path = Path(cache_path)
        # ключ в общем JSON-кеше: по умолчанию имя файла без расширения («how_to_download»)
        self.key = key or self.video_path.stem
        self.kind = kind  # "animation" — видео-подсказки, "document" — PDF материалов

    # ---- кеш ----
    def _signature(self) -> dict[str, int]:
        st = self.video_path.stat()
        return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}

    def _load_cache(self) -> dict[str, Any]:
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_cache(self, data: dict[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        except OSError:
            log.warning("Не удалось сохранить кеш медиа %s", self.cache_path, exc_info=True)

    def cached_file_id(self) -> str | None:
        """file_id из кеша, если он есть и файл с тех пор не менялся."""
        entry = self._load_cache().get(self.key)
        if not entry or not entry.get("file_id"):
            return None
        if {k: entry.get(k) for k in ("size", "mtime_ns")} != self._signature():
            log.info("Видео-подсказка %s изменилась — сбрасываю кеш file_id", self.video_path.name)
            self.forget()
            return None
        return entry["file_id"]

    def _remember(self, file_id: str) -> None:
        data = self._load_cache()
        data[self.key] = {"file_id": file_id, "path": str(self.video_path), **self._signature()}
        self._save_cache(data)

    def forget(self) -> None:
        data = self._load_cache()
        if data.pop(self.key, None) is not None:
            self._save_cache(data)

    # ---- отправка ----
    @staticmethod
    def _file_id_of(msg: Message) -> str | None:
        # mp4 без звука Telegram возвращает как animation; на всякий случай — video/document
        for media in (msg.animation, msg.video, msg.document):
            if media is not None:
                return media.file_id
        return None

    async def _send(self, bot: Bot, chat_id: int, file: Any, caption: str,
                    reply_markup: Any) -> Message:
        send = bot.send_document if self.kind == "document" else bot.send_animation
        return await send(chat_id, file, caption=caption, reply_markup=reply_markup)

    async def deliver(self, bot: Bot, chat_id: int, caption: str,
                      reply_markup: Any = None) -> Message | None:
        """Отправить файл по кешированному file_id, иначе загрузить и закешировать.
        None — файла нет или Telegram его не принял (вызывающий решает, что делать)."""
        if not self.video_path.is_file():
            return None

        file_id = self.cached_file_id()
        if file_id:
            try:
                return await self._send(bot, chat_id, file_id, caption, reply_markup)
            except Exception:
                # file_id мог протухнуть (другой бот, чистка на стороне Telegram) — загрузим заново
                log.warning("Не удалось отправить %s по file_id — загружаю файл заново",
                            self.video_path.name, exc_info=True)
                self.forget()

        try:
            msg = await self._send(bot, chat_id, FSInputFile(self.video_path), caption,
                                   reply_markup)
        except Exception:
            log.warning("Telegram не принял %s", self.video_path.name, exc_info=True)
            return None

        new_id = self._file_id_of(msg)
        if new_id:
            self._remember(new_id)
        return msg

    async def send_howto(self, bot: Bot, chat_id: int, caption: str,
                         reply_markup: Any = None) -> Message:
        """Отправляет видео с подписью. Возвращает отправленное сообщение — анимацию или,
        если видео не получилось, текст подписи (его message_id нужен, чтобы потом удалить)."""
        if not self.video_path.is_file():
            log.warning("Нет видео-подсказки %s — отправляю только текст", self.video_path)
            return await bot.send_message(chat_id, caption, reply_markup=reply_markup)
        msg = await self.deliver(bot, chat_id, caption, reply_markup)
        if msg is None:
            log.warning("Не удалось отправить видео-подсказку — отправляю только текст")
            return await bot.send_message(chat_id, caption, reply_markup=reply_markup)
        return msg
