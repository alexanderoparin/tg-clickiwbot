"""Middleware доступа и анти-флуда — без Telegram."""
from datetime import datetime
from unittest.mock import AsyncMock

from aiogram.types import Chat, Message, User

from bot.access import AccessMiddleware, ThrottleMiddleware


def msg(uid: int) -> tuple[Message, dict]:
    m = Message(message_id=1, date=datetime.now(), chat=Chat(id=uid, type="private"),
                from_user=User(id=uid, is_bot=False, first_name="u"), text="hi")
    return m, {"event_from_user": m.from_user}


async def call(mw, uid: int, answer: AsyncMock | None = None):
    m, data = msg(uid)
    handler = AsyncMock(return_value="ok")
    ans = answer or AsyncMock()
    object.__setattr__(m, "answer", ans)  # Message — frozen pydantic-модель
    res = await mw(handler, m, data)
    return res, handler.await_count, ans


async def test_open_mode_when_allowed_empty():
    mw = AccessMiddleware(set(), admins={1})
    assert mw.is_allowed(12345)
    res, called, ans = await call(mw, 999)
    assert res == "ok" and called == 1 and not ans.await_count


async def test_whitelist():
    mw = AccessMiddleware({10, 11}, admins={1})
    assert (await call(mw, 10))[0] == "ok"
    assert (await call(mw, 1))[0] == "ok", "админ всегда имеет доступ"
    res, called, ans = await call(mw, 999)
    assert res is None and called == 0
    ans.assert_awaited_once_with("Нет доступа")


async def test_throttle_one_per_second():
    t = [0.0]
    mw = ThrottleMiddleware(interval=1.0, warn_every=5.0, clock=lambda: t[0])

    async def at(sec, uid=1):
        t[0] = sec
        return await call(mw, uid)

    assert (await at(0.0))[0] == "ok"
    res, called, ans = await at(0.3)
    assert res is None and called == 0
    assert "Не так быстро" in ans.await_args.args[0]
    res, _, ans = await at(0.6)
    assert res is None and not ans.await_count, "повторно не предупреждаем в течение 5 с"
    assert (await at(0.5, uid=2))[0] == "ok", "лимит у каждого пользователя свой"
    assert (await at(1.0))[0] == "ok", "через секунду после пропущенного — снова можно"
    assert (await at(1.9))[0] is None
    assert (await at(2.05))[0] == "ok"


async def test_throttle_disabled():
    mw = ThrottleMiddleware(interval=0)
    for _ in range(3):
        assert (await call(mw, 1))[0] == "ok"


async def test_poll_forever_retries_network_errors_on_start(caplog):
    from aiogram.exceptions import TelegramNetworkError
    from aiogram.methods import GetMe

    from main import poll_forever

    class FakeDp:
        calls = 0

        async def start_polling(self, bot, **kw):
            FakeDp.calls += 1
            if FakeDp.calls < 3:
                raise TelegramNetworkError(method=GetMe(), message="Server disconnected")

    with caplog.at_level("WARNING"):
        await poll_forever(FakeDp(), bot=None, retry_delay=0)
    assert FakeDp.calls == 3, "две сетевые ошибки на старте — третья попытка успешна"
    assert caplog.text.count("Нет связи с Telegram при старте") == 2


def test_media_cache_reset_on_bot_change(tmp_path, caplog):
    import json

    from bot.media import MediaSender, reset_cache_for_bot
    cache = tmp_path / "media_cache.json"
    video = tmp_path / "how_to_download.mp4"
    video.write_bytes(b"fake")
    m = MediaSender(video, cache)
    # кеш старого формата (без id бота) — сбрасывается при первом старте
    m._remember("OLD_BOT_FILE_ID")
    assert reset_cache_for_bot(cache, 111) is True
    assert json.loads(cache.read_text(encoding="utf-8")) == {"_bot_id": 111}
    assert m.cached_file_id() is None
    # тот же бот — кеш не трогаем
    m._remember("BOT111_FILE_ID")
    assert reset_cache_for_bot(cache, 111) is False
    assert m.cached_file_id() == "BOT111_FILE_ID"
    # новый токен (другой бот) — сброс всех file_id, запоминаем нового бота
    with caplog.at_level("INFO"):
        assert reset_cache_for_bot(cache, 222) is True
    assert json.loads(cache.read_text(encoding="utf-8")) == {"_bot_id": 222}
    assert m.cached_file_id() is None and "сброшен (1 записей): how_to_download" in caplog.text
    # запись нового file_id не теряет id бота
    m._remember("BOT222_FILE_ID")
    assert json.loads(cache.read_text(encoding="utf-8"))["_bot_id"] == 222
    # кеша ещё нет — создаётся с id бота
    assert reset_cache_for_bot(tmp_path / "new" / "cache.json", 5) is True
