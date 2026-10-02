from aiogram.filters.callback_data import CallbackData
from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           ReplyKeyboardMarkup)

from config import DRR_PRESETS
from core.report import fmt_num, fmt_price

BTN_NEW = "➕ Новый анализ"
BTN_HISTORY = "📂 История"
BTN_SETTINGS = "⚙️ Настройки"
BTN_HELP = "📖 Инструкция"
BTN_CANCEL = "❌ Отмена"


class AnCb(CallbackData, prefix="an"):
    """Действия с анализом: xl, recalc, open, del, delok."""
    action: str
    id: int


class HistCb(CallbackData, prefix="hp"):
    page: int


class DrrCb(CallbackData, prefix="drr"):
    value: str  # число или "custom"


class SetCb(CallbackData, prefix="set"):
    action: str  # price, drr, clear_price, clear_drr


CB_MENU = "menu"
CB_SKIP_LABEL = "skip_label"
CB_USE_PRICE = "use_price"
CB_MATERIALS = "materials"
CB_LEAD_REVIEW = "lead_review"

BTN_MATERIALS = "📚 Полезные материалы"


def lead_offer_kb() -> InlineKeyboardMarkup:
    """После каждого анализа — одна кнопка [🙋 Хочу бесплатный разбор]."""
    from bot.texts import BTN_LEAD_REVIEW
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=BTN_LEAD_REVIEW, callback_data=CB_LEAD_REVIEW)]])


def lead_kb() -> ReplyKeyboardMarkup:
    from bot.texts import BTN_LEAD_CONTACT, BTN_LEAD_LATER
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_LEAD_CONTACT, request_contact=True)],
                  [KeyboardButton(text=BTN_LEAD_LATER)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_NEW)],
            [KeyboardButton(text=BTN_HISTORY), KeyboardButton(text=BTN_SETTINGS)],
            [KeyboardButton(text=BTN_HELP), KeyboardButton(text=BTN_MATERIALS)],
        ],
        resize_keyboard=True,
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_CANCEL)]], resize_keyboard=True)


def _ikb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def skip_label_kb() -> InlineKeyboardMarkup:
    return _ikb([[InlineKeyboardButton(text="Пропустить", callback_data=CB_SKIP_LABEL)]])


def use_price_kb(price: float | None) -> InlineKeyboardMarkup | None:
    if not price:
        return None
    return _ikb([[InlineKeyboardButton(text=f"Взять {fmt_price(price)}", callback_data=CB_USE_PRICE)]])


DRR_ROW = 5


def drr_kb(default: float | None = None) -> InlineKeyboardMarkup:
    """[1 %]…[5 %] / [6 %]…[10 %] / [Свой]. ДРР по умолчанию помечен ⭐ на своей кнопке;
    если его нет среди пресетов (например 4,5 %), — отдельной кнопкой над рядами."""
    def btn(v: float) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=f"{'⭐ ' if v == default else ''}{fmt_num(v, 2)} %",
                                    callback_data=DrrCb(value=f"{v:g}").pack())

    rows = []
    if default and default not in DRR_PRESETS:
        rows.append([btn(default)])
    presets = list(DRR_PRESETS)
    rows += [[btn(v) for v in presets[i:i + DRR_ROW]] for i in range(0, len(presets), DRR_ROW)]
    rows.append([InlineKeyboardButton(text="Свой", callback_data=DrrCb(value="custom").pack())])
    return _ikb(rows)


def _excel_recalc_row(analysis_id: int) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="📥 Excel", callback_data=AnCb(action="xl", id=analysis_id).pack()),
            InlineKeyboardButton(text="🔁 Пересчитать",
                                 callback_data=AnCb(action="recalc", id=analysis_id).pack())]


def result_kb(analysis_id: int) -> InlineKeyboardMarkup:
    """[🔁 Пересчитать][🏠 Меню]. «📥 Excel» нет — файл приходит сам сразу после сводки;
    «📚 Полезные материалы» — в главном меню."""
    return _ikb([[
        InlineKeyboardButton(text="🔁 Пересчитать",
                             callback_data=AnCb(action="recalc", id=analysis_id).pack()),
        InlineKeyboardButton(text="🏠 Меню", callback_data=CB_MENU),
    ]])


def history_item_kb(analysis_id: int, page: int) -> InlineKeyboardMarkup:
    """В истории Excel сам не приходит — поэтому здесь «📥 Excel» есть."""
    return _ikb([
        _excel_recalc_row(analysis_id),
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=AnCb(action="del", id=analysis_id).pack())],
        [InlineKeyboardButton(text="« К истории", callback_data=HistCb(page=page).pack())],
    ])


def confirm_delete_kb(analysis_id: int) -> InlineKeyboardMarkup:
    return _ikb([[
        InlineKeyboardButton(text="Да, удалить", callback_data=AnCb(action="delok", id=analysis_id).pack()),
        InlineKeyboardButton(text="Нет", callback_data=AnCb(action="open", id=analysis_id).pack()),
    ]])


def history_kb(ids: list[int], page: int, pages: int, offset: int) -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, aid in enumerate(ids, offset + 1):
        row.append(InlineKeyboardButton(text=str(i), callback_data=AnCb(action="open", id=aid).pack()))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=HistCb(page=page - 1).pack()))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data=HistCb(page=page).pack()))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=HistCb(page=page + 1).pack()))
    if nav:
        rows.append(nav)
    return _ikb(rows)


def settings_kb(has_price: bool, has_drr: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Изменить цену", callback_data=SetCb(action="price").pack()),
             InlineKeyboardButton(text="Изменить ДРР", callback_data=SetCb(action="drr").pack())]]
    clear = []
    if has_price:
        clear.append(InlineKeyboardButton(text="Сбросить цену", callback_data=SetCb(action="clear_price").pack()))
    if has_drr:
        clear.append(InlineKeyboardButton(text="Сбросить ДРР", callback_data=SetCb(action="clear_drr").pack()))
    if clear:
        rows.append(clear)
    return _ikb(rows)
