"""FSM «Новый анализ» и пересчёт существующего."""
import html
import logging
from io import BytesIO
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

import config
from bot import texts
from bot.cleanup import drop_step_media, leave_flow, remember_step_media
from bot.lead import offer_review
from bot.tracking import track
from bot.keyboards import (CB_SKIP_LABEL, CB_USE_PRICE, AnCb, DrrCb, cancel_kb, drr_kb,
                           main_menu, result_kb, skip_label_kb, use_price_kb)
from bot.media import MediaSender
from bot.service import FILE_EXPIRED_MSG, DailyLimit, FileExpired, Report, Service
from bot.states import NewAnalysis
from bot.validators import InputError, parse_drr, parse_label, parse_price
from core.parser import ParseError, parse_file, too_big_message
from core.report import fmt_num, fmt_price
from storage.db import Database

log = logging.getLogger(__name__)
router = Router(name="new_analysis")

ASK_FILE = texts.ASK_FILE
ASK_LABEL = texts.ASK_LABEL
ASK_PRICE = texts.ASK_PRICE
ASK_DRR = "До какого % ДРР считаем нормой?"
ASK_DRR_CUSTOM = "Пришли свой % ДРР числом, например 4,5"


async def send_report(message: Message, report: Report) -> None:
    await message.answer(report.summary, reply_markup=result_kb(report.analysis_id))
    await message.answer_document(BufferedInputFile(report.excel, filename=report.excel_name),
                                  reply_markup=main_menu())


# ---------- шаг 1: файл ----------

async def start_new(message: Message, state: FSMContext, service: Service, bot: Bot,
                    media: MediaSender, db: Database) -> None:
    await leave_flow(state, bot, message.chat.id)  # видео прошлого незавершённого анализа
    try:
        await service.check_daily_limit(message.from_user.id)
    except DailyLimit as e:
        await message.answer(str(e), reply_markup=main_menu())
        return
    await track(db, message.from_user.id, "new_analysis")
    await state.set_state(NewAnalysis.file)
    msg = await media.send_howto(bot, message.chat.id, ASK_FILE, reply_markup=cancel_kb())
    await remember_step_media(state, msg)


@router.message(NewAnalysis.file, F.document)
async def got_file(message: Message, state: FSMContext, bot: Bot, db: Database) -> None:
    doc = message.document
    name = doc.file_name or "file.xlsx"
    uid = message.from_user.id
    if not name.lower().endswith(".xlsx"):
        await track(db, uid, "file_error", {"reason": "не .xlsx", "file": name})
        await message.answer("Это не Excel-файл, пришли выгрузку „Топ поисковых кластеров“")
        return
    if doc.file_size and doc.file_size > config.MAX_FILE_SIZE:
        await track(db, uid, "file_error", {"reason": "больше лимита размера", "file": name})
        await message.answer(too_big_message(config.MAX_FILE_SIZE))
        return
    buf = BytesIO()
    await bot.download(doc, destination=buf)
    try:
        parsed = parse_file(buf.getvalue(), filename=name, max_rows=config.MAX_CLUSTER_ROWS,
                            max_size=config.MAX_FILE_SIZE)
    except ParseError as e:
        log.info("user %s: файл %s отклонён: %s", uid, name, e)
        await track(db, uid, "file_error", {"reason": str(e), "file": name})
        await message.answer(str(e))
        return
    except Exception:
        log.exception("user %s: ошибка разбора файла %s", uid, name)
        await track(db, uid, "file_error", {"reason": "ошибка чтения файла", "file": name})
        await message.answer("Не получилось прочитать файл. Пришли выгрузку „Топ поисковых кластеров“")
        return

    # файл принят — видео шага больше не нужно, вместо него строка-итог
    await drop_step_media(state, bot, message.chat.id, note=f"📄 Файл: {html.escape(name)}")
    await state.update_data(file_id=doc.file_id, orig_name=name, source_id=None)
    await track(db, uid, "file_ok", {"file": name, "clusters": len(parsed.clusters)})
    info = f"Файл принят: {len(parsed.clusters)} кластеров."
    for w in parsed.warnings:
        info += f"\n{w}"
    await message.answer(info)
    await state.set_state(NewAnalysis.label)
    await message.answer(ASK_LABEL, reply_markup=skip_label_kb())


@router.message(NewAnalysis.file)
async def file_expected(message: Message) -> None:
    await message.answer(ASK_FILE)


# ---------- шаг 2: название ----------

async def ask_price(message: Message, state: FSMContext, db: Database, user_id: int,
                    bot: Bot, price_media: MediaSender) -> None:
    """Видео «где смотреть цену» с подписью; под ним — «Взять N ₽», если цена есть в настройках.
    Reply-клавиатура с «❌ Отмена» остаётся с шага «пришли файл»."""
    settings = await db.get_settings(user_id)
    await state.set_state(NewAnalysis.price)
    msg = await price_media.send_howto(bot, message.chat.id, ASK_PRICE,
                                       reply_markup=use_price_kb(settings.default_price))
    await remember_step_media(state, msg)


async def price_accepted(message: Message, state: FSMContext, bot: Bot, price: float,
                         db: Database, user_id: int) -> None:
    await drop_step_media(state, bot, message.chat.id,
                          note=f"💰 Цена реализации: {fmt_price(price)}")
    await state.update_data(price=price)
    await track(db, user_id, "price", {"price": price})


@router.callback_query(NewAnalysis.label, F.data == CB_SKIP_LABEL)
async def skip_label(cb: CallbackQuery, state: FSMContext, db: Database, bot: Bot,
                     price_media: MediaSender) -> None:
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    await state.update_data(label=None)
    await track(db, cb.from_user.id, "label", {"skipped": True})
    await ask_price(cb.message, state, db, cb.from_user.id, bot, price_media)


@router.message(NewAnalysis.label, F.text)
async def got_label(message: Message, state: FSMContext, db: Database, bot: Bot,
                    price_media: MediaSender) -> None:
    try:
        label = parse_label(message.text)
    except InputError as e:
        await message.answer(str(e))
        return
    await state.update_data(label=label)
    await track(db, message.from_user.id, "label", {"label": label})
    await ask_price(message, state, db, message.from_user.id, bot, price_media)


# ---------- шаг 3: цена ----------

async def ask_drr(message: Message, state: FSMContext, db: Database, user_id: int) -> None:
    settings = await db.get_settings(user_id)
    await state.set_state(NewAnalysis.drr)
    await message.answer(ASK_DRR, reply_markup=drr_kb(settings.default_drr))


@router.callback_query(NewAnalysis.price, F.data == CB_USE_PRICE)
async def use_default_price(cb: CallbackQuery, state: FSMContext, db: Database,
                            bot: Bot) -> None:
    settings = await db.get_settings(cb.from_user.id)
    await cb.answer()
    if not settings.default_price:  # цену успели сбросить в настройках — видео оставляем
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.answer(ASK_PRICE)
        return
    await price_accepted(cb.message, state, bot, settings.default_price, db, cb.from_user.id)
    await ask_drr(cb.message, state, db, cb.from_user.id)


@router.message(NewAnalysis.price, F.text)
async def got_price(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    try:
        price = parse_price(message.text)
    except InputError as e:
        await message.answer(str(e))  # видео шага не трогаем — только текст ошибки
        return
    await price_accepted(message, state, bot, price, db, message.from_user.id)
    await ask_drr(message, state, db, message.from_user.id)


# ---------- шаг 4: ДРР ----------

@router.callback_query(NewAnalysis.drr, DrrCb.filter())
async def got_drr_button(cb: CallbackQuery, callback_data: DrrCb, state: FSMContext,
                         bot: Bot, service: Service, db: Database) -> None:
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    if callback_data.value == "custom":
        await state.set_state(NewAnalysis.drr_custom)
        await cb.message.answer(ASK_DRR_CUSTOM)
        return
    await run(cb.message, state, bot, service, db, cb.from_user.id, float(callback_data.value))


@router.message(NewAnalysis.drr_custom, F.text)
@router.message(NewAnalysis.drr, F.text)
async def got_drr_text(message: Message, state: FSMContext, bot: Bot, service: Service,
                       db: Database) -> None:
    try:
        drr = parse_drr(message.text)
    except InputError as e:
        await message.answer(str(e))
        return
    await run(message, state, bot, service, db, message.from_user.id, drr)


# ---------- шаг 5: расчёт ----------

async def run(message: Message, state: FSMContext, bot: Bot, service: Service, db: Database,
              user_id: int, drr: float) -> None:
    data = await state.get_data()
    price = data.get("price")
    if price is None:  # состояние потерялось (например, после рестарта)
        await state.clear()
        await message.answer("Сессия устарела, начни заново.", reply_markup=main_menu())
        return
    await track(db, user_id, "drr", {"drr": drr})
    wait = await message.answer(f"Считаю при цене {fmt_num(price, 2)} ₽ и ДРР {fmt_num(drr)} %…")
    try:
        if data.get("source_id"):
            report = await service.recalc(user_id, data["source_id"], price, drr)
            if report is None:
                raise LookupError("анализ не найден")
        else:
            buf = BytesIO()
            await bot.download(data["file_id"], destination=buf)
            report = await service.new_analysis(user_id, buf.getvalue(), data["orig_name"],
                                                data.get("label"), price, drr)
    except DailyLimit as e:
        await state.clear()
        await message.answer(str(e), reply_markup=main_menu())
        return
    except FileExpired:
        await state.clear()
        await message.answer(FILE_EXPIRED_MSG, reply_markup=main_menu())
        return
    except Exception:
        log.exception("user %s: ошибка расчёта", user_id)
        await state.clear()
        await message.answer("Не получилось посчитать 😔 Попробуй ещё раз.", reply_markup=main_menu())
        return
    finally:
        try:
            await wait.delete()
        except Exception:
            pass
    await state.clear()
    await send_report(message, report)  # сводка и сразу за ней Excel, без нажатия
    meta = {"analysis_id": report.analysis_id, "recalc": bool(data.get("source_id"))}
    await track(db, user_id, "result_sent", meta)
    await track(db, user_id, "excel_sent", meta)
    await offer_review(bot, message.chat.id, user_id)


# ---------- пересчёт ----------

@router.callback_query(AnCb.filter(F.action == "recalc"))
async def start_recalc(cb: CallbackQuery, callback_data: AnCb, state: FSMContext,
                       db: Database, service: Service, bot: Bot,
                       price_media: MediaSender) -> None:
    a = await db.get_analysis(cb.from_user.id, callback_data.id)
    await cb.answer()
    if a is None:
        await cb.message.answer("Анализ не найден — возможно, он удалён.")
        return
    if not a.file_path or not Path(a.file_path).exists():
        await cb.message.answer(FILE_EXPIRED_MSG)
        return
    try:
        await service.check_daily_limit(cb.from_user.id)
    except DailyLimit as e:
        await cb.message.answer(str(e))
        return
    await leave_flow(state, bot, cb.message.chat.id)
    await track(db, cb.from_user.id, "recalc", {"analysis_id": a.id})
    await state.update_data(source_id=a.id)
    title = f"«{a.label}»" if a.label else f"№{a.id}"
    await cb.message.answer(f"Пересчёт анализа {title}. Файл тот же.", reply_markup=cancel_kb())
    await ask_price(cb.message, state, db, cb.from_user.id, bot, price_media)
