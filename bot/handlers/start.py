"""/start, главное меню и отмена. Этот роутер подключается первым, поэтому кнопки
меню и «Отмена» срабатывают на любом шаге раньше хендлеров состояний."""
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from bot import texts
from bot.cleanup import leave_flow, safe_delete
from bot.materials import Materials
from bot.tracking import track
from bot.handlers.history import show_history
from bot.handlers.new_analysis import start_new
from bot.handlers.settings import show_settings
from bot.keyboards import (BTN_CANCEL, BTN_HELP, BTN_HISTORY, BTN_NEW, BTN_SETTINGS,
                           BTN_MATERIALS, CB_MATERIALS, CB_MENU, main_menu)
from bot.media import MediaSender
from storage.db import Database

router = Router(name="start")

WELCOME = texts.WELCOME


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot, db: Database) -> None:
    await leave_flow(state, bot, message.chat.id)
    await track(db, message.from_user.id, "start")
    # превью ссылки на сайт Clicki не нужно — под приветствием не должно быть карточки сайта
    await message.answer(WELCOME, reply_markup=main_menu(),
                         link_preview_options=LinkPreviewOptions(is_disabled=True))


@router.message(F.text == BTN_HELP)
@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext, bot: Bot, media: MediaSender,
                   price_media: MediaSender, db: Database) -> None:
    await leave_flow(state, bot, message.chat.id)
    await track(db, message.from_user.id, "instruction_open")
    # прошлая инструкция — удалить, чтобы видео не копились в чате
    prev = await db.get_help_messages(message.from_user.id)
    if prev:
        chat_id, ids = prev
        for mid in ids:
            await safe_delete(bot, chat_id, mid)
    # оба видео с короткими подписями (к пунктам 1 и 4), затем инструкция отдельно:
    # подпись к медиа ограничена 1024 символами. Каждое видео само падает в текст, если его нет.
    sent = [
        await media.send_howto(bot, message.chat.id, texts.HOWTO_CAPTION),
        await price_media.send_howto(bot, message.chat.id, texts.PRICE_CAPTION),
        await message.answer(texts.INSTRUCTION, reply_markup=main_menu()),
    ]
    await db.set_help_messages(message.from_user.id, message.chat.id,
                               [m.message_id for m in sent])


@router.message(F.text == BTN_CANCEL)
@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext, bot: Bot, db: Database) -> None:
    current = await state.get_state()  # «NewAnalysis:price» → «price»
    step = current.split(":")[-1] if current else "меню"
    await leave_flow(state, bot, message.chat.id)
    await track(db, message.from_user.id, "cancel", {"step": step})
    await message.answer("Отменено.", reply_markup=main_menu())


@router.message(F.text == BTN_MATERIALS)
async def open_materials(message: Message, state: FSMContext, bot: Bot, db: Database,
                         materials: Materials) -> None:
    """«📚 Полезные материалы» из главного меню. Как и другие кнопки меню, выходит из сценария."""
    await leave_flow(state, bot, message.chat.id)
    uid = message.from_user.id
    if materials.recently_sent(uid):
        await message.answer(texts.MATERIALS_ALREADY, reply_markup=main_menu())
        return
    await track(db, uid, "materials_open")
    await materials.send(bot, message.chat.id, uid)


@router.callback_query(F.data == CB_MATERIALS)
async def open_materials_old_button(cb: CallbackQuery, bot: Bot, db: Database,
                                    materials: Materials) -> None:
    """Inline-кнопка под сводками, отправленными до переноса материалов в меню."""
    uid = cb.from_user.id
    if materials.recently_sent(uid):
        await cb.answer(texts.MATERIALS_ALREADY)
        return
    await cb.answer()
    await track(db, uid, "materials_open")
    await materials.send(bot, cb.message.chat.id, uid)


@router.callback_query(F.data == CB_MENU)
async def to_menu(cb: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await leave_flow(state, bot, cb.message.chat.id)
    await cb.answer()
    await cb.message.answer("Главное меню", reply_markup=main_menu())


router.message.register(start_new, F.text == BTN_NEW)
router.message.register(show_history, F.text == BTN_HISTORY)
router.message.register(show_settings, F.text == BTN_SETTINGS)
