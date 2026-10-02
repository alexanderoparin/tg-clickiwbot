"""⚙️ Настройки: цена и ДРР по умолчанию."""
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.cleanup import leave_flow
from bot.keyboards import DrrCb, SetCb, cancel_kb, drr_kb, main_menu, settings_kb
from bot.states import SettingsForm
from bot.validators import InputError, parse_drr, parse_price
from core.report import fmt_num, fmt_price
from storage.db import Database

router = Router(name="settings")


async def settings_text(db: Database, user_id: int) -> tuple[str, object]:
    s = await db.get_settings(user_id)
    price = fmt_price(s.default_price) if s.default_price else "не задана"
    drr = f"{fmt_num(s.default_drr)} %" if s.default_drr else "не задана"
    text = (f"<b>⚙️ Настройки</b>\n\nЦена по умолчанию: {price}\nДРР по умолчанию: {drr}\n\n"
            "Они подставляются кнопками при новом анализе.")
    return text, settings_kb(bool(s.default_price), bool(s.default_drr))


async def show_settings(message: Message, state: FSMContext, db: Database, bot: Bot) -> None:
    await leave_flow(state, bot, message.chat.id)
    text, kb = await settings_text(db, message.from_user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(SetCb.filter())
async def settings_action(cb: CallbackQuery, callback_data: SetCb, state: FSMContext,
                          db: Database) -> None:
    await cb.answer()
    uid = cb.from_user.id
    action = callback_data.action
    if action == "price":
        await state.set_state(SettingsForm.price)
        await cb.message.answer("Пришли цену по умолчанию, ₽", reply_markup=cancel_kb())
    elif action == "drr":
        await state.set_state(SettingsForm.drr)
        await cb.message.answer("Выбери норму ДРР по умолчанию или напиши число, %",
                                reply_markup=drr_kb())
    elif action in ("clear_price", "clear_drr"):
        await db.clear_default(uid, "default_price" if action == "clear_price" else "default_drr")
        text, kb = await settings_text(db, uid)
        await cb.message.edit_text(text, reply_markup=kb)


async def _saved(message: Message, state: FSMContext, db: Database, user_id: int) -> None:
    await state.clear()
    await message.answer("Сохранено ✅", reply_markup=main_menu())
    text, kb = await settings_text(db, user_id)
    await message.answer(text, reply_markup=kb)


@router.message(SettingsForm.price, F.text)
async def set_price(message: Message, state: FSMContext, db: Database) -> None:
    try:
        price = parse_price(message.text)
    except InputError as e:
        await message.answer(str(e))
        return
    await db.set_default(message.from_user.id, price=price)
    await _saved(message, state, db, message.from_user.id)


@router.callback_query(SettingsForm.drr, DrrCb.filter())
async def set_drr_button(cb: CallbackQuery, callback_data: DrrCb, state: FSMContext,
                         db: Database) -> None:
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    if callback_data.value == "custom":
        await cb.message.answer("Пришли число, например 4,5")
        return
    await db.set_default(cb.from_user.id, drr=float(callback_data.value))
    await _saved(cb.message, state, db, cb.from_user.id)


@router.message(SettingsForm.drr, F.text)
async def set_drr_text(message: Message, state: FSMContext, db: Database) -> None:
    try:
        drr = parse_drr(message.text)
    except InputError as e:
        await message.answer(str(e))
        return
    await db.set_default(message.from_user.id, drr=drr)
    await _saved(message, state, db, message.from_user.id)
