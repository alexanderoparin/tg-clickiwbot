import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage

import config
from bot.access import AccessMiddleware, ThrottleMiddleware
from bot.handlers import admin, fallback, history, new_analysis, settings, start
from bot import lead
from bot.materials import Materials
from bot.media import MediaSender, reset_cache_for_bot
from bot.service import Service
from bot.tracking import UserMiddleware
from storage.db import Database
from storage.files import FileStore


STARTUP_RETRY_SEC = 5.0


def setup_logging() -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        config.LOG_DIR / "bot.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    handlers: list[logging.Handler] = [file_handler]
    if sys.stderr is not None:  # под pythonw консоли нет — пишем только в файл
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        handlers.append(console)
    logging.basicConfig(level=logging.INFO, handlers=handlers)


def build_dispatcher(db: Database, files: FileStore, flood_interval: float | None = None,
                     media: MediaSender | None = None,
                     price_media: MediaSender | None = None,
                     materials: Materials | None = None) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    # доступны в хендлерах как аргументы db, files, service, media, price_media, materials
    dp["db"] = db
    dp["files"] = files
    dp["service"] = Service(db, files)
    dp["media"] = media or MediaSender(config.HOW_TO_VIDEO, config.MEDIA_CACHE)
    dp["price_media"] = price_media or MediaSender(config.HOW_TO_PRICE_VIDEO, config.MEDIA_CACHE)
    dp["materials"] = materials or Materials(config.MATERIALS_DIR, config.MEDIA_CACHE,
                                             repeat_sec=config.MATERIALS_REPEAT_SEC)
    # анти-флуд раньше доступа: чужой спам тоже гасится
    interval = config.FLOOD_INTERVAL if flood_interval is None else flood_interval
    dp.message.outer_middleware(ThrottleMiddleware(interval))
    access = AccessMiddleware(config.ALLOWED_USER_IDS, config.ADMIN_IDS)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    # профиль пользователя — только для тех, кого пропустили доступ и анти-флуд
    users = UserMiddleware(db)
    dp.message.outer_middleware(users)
    dp.callback_query.outer_middleware(users)
    # start первым: кнопки меню и «Отмена» важнее хендлеров состояний;
    # lead — сразу за ним: контакт и «Не сейчас» принимаются на любом шаге
    dp.include_routers(start.router, lead.router, admin.router, new_analysis.router,
                       history.router, settings.router, fallback.router)
    return dp


async def cleanup_loop(service: Service) -> None:
    """Раз в CLEANUP_INTERVAL_SEC удаляет выгрузки старше FILE_TTL_DAYS (первый прогон — сразу)."""
    while True:
        try:
            await service.cleanup_old_files()
        except Exception:
            logging.exception("Ошибка очистки старых файлов")
        await asyncio.sleep(config.CLEANUP_INTERVAL_SEC)


async def main() -> None:
    setup_logging()
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан в .env")
    if not config.ALLOWED_USER_IDS:
        logging.warning("ALLOWED_USER_IDS пуст — открытый режим, бот доступен всем")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = Database(config.DB_PATH)
    await db.init()
    session = None
    if config.TELEGRAM_PROXY:
        session = AiohttpSession(proxy=config.TELEGRAM_PROXY)
        logging.info("Telegram API через прокси: %s", _mask_proxy(config.TELEGRAM_PROXY))
    bot = Bot(
        config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    # file_id привязаны к боту: сменили BOT_TOKEN → кеш видео и PDF сбрасывается.
    # bot.id — из токена (<id>:<секрет>), совпадает с id из getMe и не требует сети
    reset_cache_for_bot(config.MEDIA_CACHE, bot.id)
    dp = build_dispatcher(db, FileStore(config.UPLOADS_DIR))
    cleanup = asyncio.create_task(cleanup_loop(dp["service"]))
    logging.info("Бот запущен")
    try:
        await poll_forever(dp, bot)
    finally:
        cleanup.cancel()
        if session is not None:
            await session.close()


def _mask_proxy(url: str) -> str:
    """Скрывает логин/пароль в URL прокси для логов."""
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1) if "://" in url else ("", url)
    creds, host = rest.rsplit("@", 1)
    return f"{scheme}://***@{host}" if scheme else f"***@{host}"


async def poll_forever(dp: Dispatcher, bot: Bot, retry_delay: float = STARTUP_RETRY_SEC) -> None:
    """Сеть на старте (getMe) aiogram не повторяет — повторяем сами, иначе бот молча умирает."""
    while True:
        try:
            await dp.start_polling(bot, handle_signals=True)
            return  # штатная остановка (Ctrl+C / SIGTERM)
        except TelegramNetworkError as e:
            logging.warning("Нет связи с Telegram при старте (%s) — повтор через %s с", e, retry_delay)
            await asyncio.sleep(retry_delay)


def run() -> None:
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        # под pythonw нет консоли — без этого трейсбек потеряется
        logging.exception("Бот упал")
        raise


if __name__ == "__main__":
    run()
