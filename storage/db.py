"""SQLite: пользователи, загрузки, анализы."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    user_id       INTEGER PRIMARY KEY,
    default_price REAL,
    default_drr   REAL
);
CREATE TABLE IF NOT EXISTS uploads(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    file_path   TEXT,
    orig_name   TEXT,
    period_from TEXT,
    period_to   TEXT,
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id   INTEGER NOT NULL REFERENCES uploads(id),
    user_id     INTEGER NOT NULL,
    label       TEXT,
    price       REAL NOT NULL,
    drr_norm    REAL NOT NULL,
    cnt_red     INTEGER NOT NULL,
    cnt_yellow  INTEGER NOT NULL,
    cnt_green   INTEGER NOT NULL,
    cnt_gray    INTEGER NOT NULL,
    sum_red     REAL NOT NULL,
    total_spend REAL NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_analyses_user ON analyses(user_id, id DESC);
-- сообщения последней открытой инструкции (оба видео + текст), чтобы удалить их при повторном
CREATE TABLE IF NOT EXISTS help_messages(
    user_id     INTEGER PRIMARY KEY,
    chat_id     INTEGER NOT NULL,
    message_ids TEXT NOT NULL
);
-- воронка: что делал пользователь
CREATE TABLE IF NOT EXISTS events(
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    event      TEXT NOT NULL,
    meta       TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_event_time ON events(event, created_at);
CREATE INDEX IF NOT EXISTS ix_events_user ON events(user_id, created_at);
"""

# Колонки users, добавленные после первой версии: при init() недостающие добавляются
# через ALTER TABLE, поэтому существующая база обновляется без потери данных
USER_COLUMNS = {
    "username": "TEXT",
    "first_name": "TEXT",
    "last_name": "TEXT",
    "language_code": "TEXT",
    "first_seen": "TEXT",
    "last_seen": "TEXT",
    "phone": "TEXT",
    "lead_requested_at": "TEXT",
    "last_step": "TEXT",
    "last_step_at": "TEXT",
}

# Шаги воронки для /stats — в порядке прохождения
FUNNEL = ("start", "new_analysis", "file_ok", "price", "drr", "result_sent", "excel_sent",
          "lead_request", "lead_contact")
# Если последний шаг один из этих — пользователь дошёл до результата, не «застрял».
# materials_open открывают только из готового анализа, поэтому он тоже «дошёл»
FINISHED_STEPS = ("result_sent", "excel_sent", "excel_download", "lead_contact", "materials_open")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


@dataclass
class Stats:
    users: int
    analyses_total: int
    analyses_day: int
    analyses_week: int
    uploads_with_file: int


@dataclass
class UserSettings:
    user_id: int
    default_price: float | None = None
    default_drr: float | None = None


@dataclass
class UserInfo:
    user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    phone: str | None = None
    lead_requested_at: datetime | None = None
    last_step: str | None = None
    last_step_at: datetime | None = None
    analyses: int = 0
    last_label: str | None = None

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p) or f"id{self.user_id}"

    @property
    def mention(self) -> str:
        return f"@{self.username}" if self.username else "(без username)"

    def is_stuck(self, now: datetime, idle: timedelta) -> bool:
        """Остановился не на результате и молчит дольше `idle`."""
        return (self.last_step is not None and self.last_step not in FINISHED_STEPS
                and self.last_step_at is not None and now - self.last_step_at > idle)


@dataclass
class Upload:
    id: int
    user_id: int
    file_path: str | None
    orig_name: str
    period_from: date | None
    period_to: date | None
    uploaded_at: datetime


@dataclass
class Analysis:
    id: int
    upload_id: int
    user_id: int
    label: str | None
    price: float
    drr_norm: float
    cnt_red: int
    cnt_yellow: int
    cnt_green: int
    cnt_gray: int
    sum_red: float
    total_spend: float
    created_at: datetime
    # из uploads
    file_path: str | None  # None — файл удалён по сроку хранения
    orig_name: str
    period_from: date | None
    period_to: date | None


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)

    def _conn(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.path)

    async def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with self._conn() as db:
            await db.executescript(SCHEMA)
            cur = await db.execute("PRAGMA table_info(users)")
            have = {r[1] for r in await cur.fetchall()}
            for col, typ in USER_COLUMNS.items():
                if col not in have:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
            await db.commit()

    # ---- users ----
    async def get_settings(self, user_id: int) -> UserSettings:
        async with self._conn() as db:
            cur = await db.execute(
                "SELECT default_price, default_drr FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
        return UserSettings(user_id, *row) if row else UserSettings(user_id)

    async def set_default(self, user_id: int, *, price: float | None = None,
                          drr: float | None = None) -> None:
        async with self._conn() as db:
            await db.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
            if price is not None:
                await db.execute("UPDATE users SET default_price=? WHERE user_id=?", (price, user_id))
            if drr is not None:
                await db.execute("UPDATE users SET default_drr=? WHERE user_id=?", (drr, user_id))
            await db.commit()

    async def clear_default(self, user_id: int, field: str) -> None:
        assert field in ("default_price", "default_drr")
        async with self._conn() as db:
            await db.execute(f"UPDATE users SET {field}=NULL WHERE user_id=?", (user_id,))
            await db.commit()

    # ---- uploads ----
    async def create_upload(self, user_id: int, orig_name: str, period_from: date | None,
                            period_to: date | None) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                "INSERT INTO uploads(user_id, orig_name, period_from, period_to, uploaded_at) "
                "VALUES (?,?,?,?,?)",
                (user_id, orig_name, period_from and period_from.isoformat(),
                 period_to and period_to.isoformat(), datetime.now().isoformat(timespec="seconds")))
            await db.commit()
            return cur.lastrowid

    async def set_upload_path(self, upload_id: int, file_path: str | None) -> None:
        async with self._conn() as db:
            await db.execute("UPDATE uploads SET file_path=? WHERE id=?", (file_path, upload_id))
            await db.commit()

    async def delete_upload(self, upload_id: int) -> None:
        async with self._conn() as db:
            await db.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
            await db.commit()

    async def get_upload(self, user_id: int, upload_id: int) -> Upload | None:
        async with self._conn() as db:
            cur = await db.execute(
                "SELECT id, user_id, file_path, orig_name, period_from, period_to, uploaded_at "
                "FROM uploads WHERE id=? AND user_id=?", (upload_id, user_id))
            r = await cur.fetchone()
        if not r:
            return None
        return Upload(r[0], r[1], r[2], r[3], _d(r[4]), _d(r[5]), datetime.fromisoformat(r[6]))

    # ---- analyses ----
    async def create_analysis(self, *, upload_id: int, user_id: int, label: str | None,
                              price: float, drr_norm: float, cnt_red: int, cnt_yellow: int,
                              cnt_green: int, cnt_gray: int, sum_red: float,
                              total_spend: float) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                "INSERT INTO analyses(upload_id, user_id, label, price, drr_norm, cnt_red, "
                "cnt_yellow, cnt_green, cnt_gray, sum_red, total_spend, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (upload_id, user_id, label, price, drr_norm, cnt_red, cnt_yellow, cnt_green,
                 cnt_gray, sum_red, total_spend, datetime.now().isoformat(timespec="seconds")))
            await db.commit()
            return cur.lastrowid

    _SELECT = (
        "SELECT a.id, a.upload_id, a.user_id, a.label, a.price, a.drr_norm, a.cnt_red, "
        "a.cnt_yellow, a.cnt_green, a.cnt_gray, a.sum_red, a.total_spend, a.created_at, "
        "u.file_path, u.orig_name, u.period_from, u.period_to "
        "FROM analyses a JOIN uploads u ON u.id = a.upload_id "
    )

    @staticmethod
    def _row(r) -> Analysis:
        return Analysis(*r[:12], datetime.fromisoformat(r[12]), r[13], r[14], _d(r[15]), _d(r[16]))

    async def get_analysis(self, user_id: int, analysis_id: int) -> Analysis | None:
        async with self._conn() as db:
            cur = await db.execute(self._SELECT + "WHERE a.id=? AND a.user_id=?",
                                   (analysis_id, user_id))
            r = await cur.fetchone()
        return self._row(r) if r else None

    async def list_analyses(self, user_id: int, offset: int = 0, limit: int = 10) -> list[Analysis]:
        async with self._conn() as db:
            cur = await db.execute(
                self._SELECT + "WHERE a.user_id=? ORDER BY a.id DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset))
            rows = await cur.fetchall()
        return [self._row(r) for r in rows]

    async def count_analyses(self, user_id: int) -> int:
        async with self._conn() as db:
            cur = await db.execute("SELECT COUNT(*) FROM analyses WHERE user_id=?", (user_id,))
            return (await cur.fetchone())[0]

    async def count_analyses_since(self, user_id: int, since: datetime) -> int:
        async with self._conn() as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM analyses WHERE user_id=? AND created_at>=?",
                (user_id, since.isoformat(timespec="seconds")))
            return (await cur.fetchone())[0]

    # ---- пользователи и воронка ----
    async def upsert_user(self, user_id: int, username: str | None, first_name: str | None,
                          last_name: str | None, language_code: str | None) -> bool:
        """Обновить профиль и last_seen при каждом визите. True — пользователь новый
        (раньше не был виден; строка из настроек без first_seen тоже считается новой)."""
        now = _now()
        async with self._conn() as db:
            cur = await db.execute("SELECT first_seen FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            is_new = row is None or row[0] is None
            await db.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
            await db.execute(
                "UPDATE users SET username=?, first_name=?, last_name=?, language_code=?, "
                "last_seen=?, first_seen=COALESCE(first_seen, ?) WHERE user_id=?",
                (username, first_name, last_name, language_code, now, now, user_id))
            await db.commit()
        return is_new

    async def add_event(self, user_id: int, event: str, meta: dict | None = None,
                        at: datetime | None = None) -> None:
        """Записать событие и обновить last_step / last_step_at пользователя."""
        ts = (at or datetime.now()).isoformat(timespec="seconds")
        async with self._conn() as db:
            await db.execute(
                "INSERT INTO events(user_id, event, meta, created_at) VALUES (?,?,?,?)",
                (user_id, event, json.dumps(meta, ensure_ascii=False) if meta else None, ts))
            await db.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
            await db.execute("UPDATE users SET last_step=?, last_step_at=? WHERE user_id=?",
                             (event, ts, user_id))
            await db.commit()

    async def events_of(self, user_id: int) -> list[tuple[str, dict | None]]:
        async with self._conn() as db:
            cur = await db.execute(
                "SELECT event, meta FROM events WHERE user_id=? ORDER BY id", (user_id,))
            rows = await cur.fetchall()
        return [(e, json.loads(m) if m else None) for e, m in rows]

    _USER_SELECT = (
        "SELECT u.user_id, u.username, u.first_name, u.last_name, u.language_code, u.first_seen, "
        "u.last_seen, u.phone, u.lead_requested_at, u.last_step, u.last_step_at, "
        "(SELECT COUNT(*) FROM analyses a WHERE a.user_id = u.user_id), "
        "(SELECT a.label FROM analyses a WHERE a.user_id = u.user_id ORDER BY a.id DESC LIMIT 1) "
        "FROM users u "
    )

    @staticmethod
    def _user_row(r) -> UserInfo:
        return UserInfo(r[0], r[1], r[2], r[3], r[4], _dt(r[5]), _dt(r[6]), r[7], _dt(r[8]),
                        r[9], _dt(r[10]), r[11], r[12])

    async def get_user(self, user_id: int) -> UserInfo | None:
        async with self._conn() as db:
            cur = await db.execute(self._USER_SELECT + "WHERE u.user_id=?", (user_id,))
            r = await cur.fetchone()
        return self._user_row(r) if r else None

    async def all_users(self) -> list[UserInfo]:
        async with self._conn() as db:
            cur = await db.execute(
                self._USER_SELECT + "ORDER BY COALESCE(u.last_seen, u.first_seen) DESC")
            rows = await cur.fetchall()
        return [self._user_row(r) for r in rows]

    async def set_phone(self, user_id: int, phone: str) -> None:
        async with self._conn() as db:
            await db.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
            await db.execute("UPDATE users SET phone=? WHERE user_id=?", (phone, user_id))
            await db.commit()

    async def mark_lead_requested(self, user_id: int, at: datetime | None = None) -> None:
        ts = (at or datetime.now()).isoformat(timespec="seconds")
        async with self._conn() as db:
            await db.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
            await db.execute("UPDATE users SET lead_requested_at=? WHERE user_id=?",
                             (ts, user_id))
            await db.commit()

    async def funnel(self, since: datetime, steps: tuple[str, ...] = FUNNEL) -> dict[str, int]:
        """Уникальные пользователи по каждому шагу воронки с `since`."""
        ts = since.isoformat(timespec="seconds")
        async with self._conn() as db:
            cur = await db.execute(
                f"SELECT event, COUNT(DISTINCT user_id) FROM events WHERE created_at>=? "
                f"AND event IN ({','.join('?' * len(steps))}) GROUP BY event", (ts, *steps))
            got = dict(await cur.fetchall())
        return {s: got.get(s, 0) for s in steps}

    async def count_users_with_event(self, event: str, since: datetime) -> int:
        return (await self.funnel(since, (event,)))[event]

    async def top_file_errors(self, since: datetime, limit: int = 5) -> list[tuple[str, int]]:
        """Самые частые причины file_error: [(причина, сколько раз)]."""
        async with self._conn() as db:
            cur = await db.execute(
                "SELECT COALESCE(json_extract(meta, '$.reason'), '—') AS r, COUNT(*) AS n "
                "FROM events WHERE event='file_error' AND created_at>=? "
                "GROUP BY r ORDER BY n DESC, r LIMIT ?",
                (since.isoformat(timespec="seconds"), limit))
            return [(r, n) for r, n in await cur.fetchall()]

    # ---- сообщения инструкции ----
    async def get_help_messages(self, user_id: int) -> tuple[int, list[int]] | None:
        """(chat_id, [message_id, …]) последней инструкции пользователя или None."""
        async with self._conn() as db:
            cur = await db.execute(
                "SELECT chat_id, message_ids FROM help_messages WHERE user_id=?", (user_id,))
            r = await cur.fetchone()
        return (r[0], json.loads(r[1])) if r else None

    async def set_help_messages(self, user_id: int, chat_id: int, message_ids: list[int]) -> None:
        async with self._conn() as db:
            await db.execute(
                "INSERT INTO help_messages(user_id, chat_id, message_ids) VALUES (?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id, "
                "message_ids=excluded.message_ids",
                (user_id, chat_id, json.dumps(message_ids)))
            await db.commit()

    # ---- админка и обслуживание ----
    async def stats(self, now: datetime | None = None) -> Stats:
        now = now or datetime.now()
        day = (now - timedelta(days=1)).isoformat(timespec="seconds")
        week = (now - timedelta(days=7)).isoformat(timespec="seconds")
        async with self._conn() as db:
            async def one(sql: str, *args) -> int:
                cur = await db.execute(sql, args)
                return (await cur.fetchone())[0]
            return Stats(
                users=await one("SELECT COUNT(*) FROM (SELECT user_id FROM users UNION "
                                "SELECT user_id FROM uploads UNION SELECT user_id FROM analyses)"),
                analyses_total=await one("SELECT COUNT(*) FROM analyses"),
                analyses_day=await one("SELECT COUNT(*) FROM analyses WHERE created_at>=?", day),
                analyses_week=await one("SELECT COUNT(*) FROM analyses WHERE created_at>=?", week),
                uploads_with_file=await one("SELECT COUNT(*) FROM uploads WHERE file_path IS NOT NULL"),
            )

    async def expired_uploads(self, before: datetime) -> list[tuple[int, str]]:
        """Загрузки старше `before`, у которых ещё есть файл: [(id, file_path)]."""
        async with self._conn() as db:
            cur = await db.execute(
                "SELECT id, file_path FROM uploads WHERE file_path IS NOT NULL AND uploaded_at<?",
                (before.isoformat(timespec="seconds"),))
            return [(r[0], r[1]) for r in await cur.fetchall()]

    async def clear_upload_path(self, upload_id: int) -> None:
        """Файл удалён, запись загрузки и анализы остаются в истории."""
        await self.set_upload_path(upload_id, None)

    async def delete_analysis(self, user_id: int, analysis_id: int) -> str | None:
        """Удаляет анализ. Если на загрузку больше никто не ссылается — удаляет и её,
        возвращая путь к файлу, который нужно стереть. Иначе None."""
        async with self._conn() as db:
            cur = await db.execute("SELECT upload_id FROM analyses WHERE id=? AND user_id=?",
                                   (analysis_id, user_id))
            r = await cur.fetchone()
            if not r:
                return None
            upload_id = r[0]
            await db.execute("DELETE FROM analyses WHERE id=?", (analysis_id,))
            cur = await db.execute("SELECT COUNT(*) FROM analyses WHERE upload_id=?", (upload_id,))
            orphan_path = None
            if (await cur.fetchone())[0] == 0:
                cur = await db.execute("SELECT file_path FROM uploads WHERE id=?", (upload_id,))
                fr = await cur.fetchone()
                orphan_path = fr[0] if fr else None
                await db.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
            await db.commit()
            return orphan_path
