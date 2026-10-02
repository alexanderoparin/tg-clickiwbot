"""📂 История: список, открытие, Excel, удаление."""
import html
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.cleanup import leave_flow
from bot.tracking import track
from bot.keyboards import (AnCb, HistCb, confirm_delete_kb, history_item_kb,
                           history_kb)
from bot.service import FILE_EXPIRED_MSG, FileExpired, Service
from config import HISTORY_PAGE_SIZE
from core.report import fmt_num, fmt_price, fmt_rub
from storage.db import Analysis, Database

log = logging.getLogger(__name__)
router = Router(name="history")


def history_line(a: Analysis) -> str:
    parts = [f"{a.created_at:%d.%m}"]
    if a.label:
        parts.append(html.escape(a.label))
    parts.append(fmt_price(a.price))
    parts.append(f"ДРР {fmt_num(a.drr_norm)} %")
    parts.append(f"🔴{a.cnt_red} 🟡{a.cnt_yellow}")
    return " · ".join(parts)


def stored_summary(a: Analysis) -> str:
    """Сводка из сохранённых итогов — когда исходный файл уже удалён."""
    lines = [f"<b>📊 Анализ №{a.id}</b>", history_line(a), "",
             f"Расход на поиск: {fmt_rub(a.total_spend)}",
             f"🔴 Возможно удалить: {a.cnt_red} · {fmt_rub(a.sum_red)}",
             f"🟡 Работать: {a.cnt_yellow}", f"🟢 Норма: {a.cnt_green}",
             f"⚪ Мало данных: {a.cnt_gray}", "",
             f"⌛ Исходный файл удалён по сроку хранения. {FILE_EXPIRED_MSG}"]
    return "\n".join(lines)


async def render_page(db: Database, user_id: int, page: int) -> tuple[str, object]:
    total = await db.count_analyses(user_id)
    if total == 0:
        return "История пуста. Нажми «➕ Новый анализ».", None
    pages = (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE
    page = max(0, min(page, pages - 1))
    offset = page * HISTORY_PAGE_SIZE
    items = await db.list_analyses(user_id, offset, HISTORY_PAGE_SIZE)
    lines = [f"<b>📂 История</b> ({total})", ""]
    lines += [f"{i}. {history_line(a)}" for i, a in enumerate(items, offset + 1)]
    lines += ["", "Выбери номер, чтобы открыть."]
    return "\n".join(lines), history_kb([a.id for a in items], page, pages, offset)


async def show_history(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    await leave_flow(state, bot, message.chat.id)
    await track(db, message.from_user.id, "history_open")
    text, kb = await render_page(db, message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)


@router.callback_query(HistCb.filter())
async def history_page(cb: CallbackQuery, callback_data: HistCb, db: Database) -> None:
    await cb.answer()
    text, kb = await render_page(db, cb.from_user.id, callback_data.page)
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:  # не изменилось или сообщение — документ
        await cb.message.answer(text, reply_markup=kb)


async def _page_of(db: Database, user_id: int, analysis_id: int) -> int:
    # страница, на которой анализ стоит в истории (сортировка по id ↓)
    items = await db.list_analyses(user_id, 0, 10_000)
    ids = [a.id for a in items]
    return ids.index(analysis_id) // HISTORY_PAGE_SIZE if analysis_id in ids else 0


@router.callback_query(AnCb.filter(F.action == "open"))
async def open_analysis(cb: CallbackQuery, callback_data: AnCb, service: Service,
                        db: Database) -> None:
    await cb.answer()
    uid = cb.from_user.id
    page = await _page_of(db, uid, callback_data.id)
    kb = history_item_kb(callback_data.id, page)
    try:
        res = await service.rebuild(uid, callback_data.id)
    except FileExpired:
        a = await db.get_analysis(uid, callback_data.id)
        if a is not None:
            await cb.message.answer(stored_summary(a), reply_markup=kb)
        return
    except Exception:
        log.exception("user %s: не удалось открыть анализ %s", uid, callback_data.id)
        await cb.message.answer("Не получилось открыть анализ.")
        return
    if res is None:
        await cb.message.answer("Анализ не найден — возможно, он удалён.")
        return
    _, report = res
    await cb.message.answer(report.summary, reply_markup=kb)


@router.callback_query(AnCb.filter(F.action == "xl"))
async def send_excel(cb: CallbackQuery, callback_data: AnCb, service: Service,
                     db: Database) -> None:
    await cb.answer("Собираю Excel…")
    try:
        res = await service.rebuild(cb.from_user.id, callback_data.id)
    except FileExpired:
        await cb.message.answer(FILE_EXPIRED_MSG)
        return
    except Exception:
        log.exception("user %s: не удалось собрать Excel %s", cb.from_user.id, callback_data.id)
        await cb.message.answer("Не получилось собрать Excel.")
        return
    if res is None:
        await cb.message.answer("Анализ не найден — возможно, он удалён.")
        return
    _, report = res
    await cb.message.answer_document(BufferedInputFile(report.excel, filename=report.excel_name))
    await track(db, cb.from_user.id, "excel_download", {"analysis_id": callback_data.id})


@router.callback_query(AnCb.filter(F.action == "del"))
async def ask_delete(cb: CallbackQuery, callback_data: AnCb, db: Database) -> None:
    await cb.answer()
    a = await db.get_analysis(cb.from_user.id, callback_data.id)
    if a is None:
        await cb.message.answer("Анализ не найден — возможно, он уже удалён.")
        return
    await cb.message.answer(f"Удалить анализ?\n{history_line(a)}",
                            reply_markup=confirm_delete_kb(a.id))


@router.callback_query(AnCb.filter(F.action == "delok"))
async def do_delete(cb: CallbackQuery, callback_data: AnCb, service: Service,
                    db: Database) -> None:
    await service.delete(cb.from_user.id, callback_data.id)
    await cb.answer("Удалено")
    text, kb = await render_page(db, cb.from_user.id, 0)
    await cb.message.edit_text("🗑 Анализ удалён.")
    await cb.message.answer(text, reply_markup=kb)
