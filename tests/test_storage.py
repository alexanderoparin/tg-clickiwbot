from datetime import date

import pytest

from storage.db import Database
from storage.files import FileStore


@pytest.fixture
async def db(tmp_path):
    d = Database(tmp_path / "bot.db")
    await d.init()
    return d


def _stats(**kw):
    base = dict(label="ИП", price=9500, drr_norm=4, cnt_red=1, cnt_yellow=0, cnt_green=13,
                cnt_gray=138, sum_red=408.9, total_spend=4532.7)
    base.update(kw)
    return base


async def test_settings(db):
    s = await db.get_settings(1)
    assert s.default_price is None and s.default_drr is None
    await db.set_default(1, price=9500)
    await db.set_default(1, drr=4)
    s = await db.get_settings(1)
    assert (s.default_price, s.default_drr) == (9500, 4)
    await db.clear_default(1, "default_price")
    assert (await db.get_settings(1)).default_price is None


async def test_analyses_and_delete(db, tmp_path):
    fs = FileStore(tmp_path / "uploads")
    up = await db.create_upload(1, "f.xlsx", date(2026, 9, 17), date(2026, 9, 23))
    p = fs.save(1, up, b"data")
    await db.set_upload_path(up, str(p))
    a1 = await db.create_analysis(upload_id=up, user_id=1, **_stats())
    a2 = await db.create_analysis(upload_id=up, user_id=1, **_stats(drr_norm=3, label=None))

    assert await db.count_analyses(1) == 2
    lst = await db.list_analyses(1)
    assert [a.id for a in lst] == [a2, a1]
    assert lst[1].period_from == date(2026, 9, 17) and lst[1].file_path == str(p)

    # чужой пользователь не видит и не удаляет
    assert await db.get_analysis(2, a1) is None
    assert await db.delete_analysis(2, a1) is None
    assert await db.count_analyses(1) == 2

    # файл ещё нужен второму анализу
    assert await db.delete_analysis(1, a1) is None
    assert await db.get_upload(1, up) is not None
    # последний анализ — возвращается путь к файлу
    orphan = await db.delete_analysis(1, a2)
    assert orphan == str(p)
    fs.delete(orphan)
    assert not p.exists()
    assert await db.get_upload(1, up) is None


async def test_pagination(db):
    up = await db.create_upload(1, "f.xlsx", None, None)
    ids = [await db.create_analysis(upload_id=up, user_id=1, **_stats()) for _ in range(12)]
    page2 = await db.list_analyses(1, offset=10, limit=10)
    assert [a.id for a in page2] == ids[1::-1]
    assert page2[0].period_from is None


async def _age_upload(db, upload_id, days):
    import aiosqlite
    from datetime import datetime, timedelta
    async with aiosqlite.connect(db.path) as c:
        ts = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        await c.execute("UPDATE uploads SET uploaded_at=? WHERE id=?", (ts, upload_id))
        await c.execute("UPDATE analyses SET created_at=? WHERE upload_id=?", (ts, upload_id))
        await c.commit()


async def test_limits_stats_and_expiry(db):
    from datetime import datetime, timedelta
    old = await db.create_upload(1, "old.xlsx", None, None)
    await db.set_upload_path(old, "/x/old.xlsx")
    await db.create_analysis(upload_id=old, user_id=1, **_stats())
    await _age_upload(db, old, 61)
    new = await db.create_upload(2, "new.xlsx", None, None)
    await db.set_upload_path(new, "/x/new.xlsx")
    for _ in range(3):
        await db.create_analysis(upload_id=new, user_id=2, **_stats())
    await db.set_default(3, price=100)

    day_ago = datetime.now() - timedelta(days=1)
    assert await db.count_analyses_since(1, day_ago) == 0
    assert await db.count_analyses_since(2, day_ago) == 3

    s = await db.stats()
    assert (s.users, s.analyses_total, s.analyses_day, s.analyses_week, s.uploads_with_file) == \
        (3, 4, 3, 3, 2)

    expired = await db.expired_uploads(datetime.now() - timedelta(days=60))
    assert expired == [(old, "/x/old.xlsx")]
    await db.clear_upload_path(old)
    assert await db.expired_uploads(datetime.now() - timedelta(days=60)) == []
    a = (await db.list_analyses(1))[0]
    assert a.file_path is None, "запись в истории остаётся без файла"
