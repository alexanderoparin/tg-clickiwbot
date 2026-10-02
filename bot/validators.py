"""Разбор пользовательского ввода цены и ДРР."""
from __future__ import annotations

import re

from config import DRR_MAX, DRR_MIN, PRICE_MAX, PRICE_MIN

LABEL_MAX = 64


class InputError(ValueError):
    pass


def _number(text: str, suffixes: str) -> float:
    s = (text or "").strip().lower()
    s = re.sub(rf"[{suffixes}]+$", "", s).strip()
    s = s.replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise InputError
    return float(s)


def parse_price(text: str) -> float:
    try:
        v = _number(text, "₽рубр.")
    except InputError:
        raise InputError("Не понял цену. Пришли число, например 9500 или 9 500,50") from None
    if not PRICE_MIN <= v <= PRICE_MAX:
        raise InputError(f"Цена должна быть от {PRICE_MIN} до {PRICE_MAX:,} ₽".replace(",", " "))
    return round(v, 2)


def parse_drr(text: str) -> float:
    try:
        v = _number(text, "%")
    except InputError:
        raise InputError("Не понял процент. Пришли число, например 4 или 4,5") from None
    if not DRR_MIN <= v <= DRR_MAX:
        raise InputError(f"ДРР должна быть от {DRR_MIN:g} до {DRR_MAX:g} %".replace(".", ","))
    return round(v, 2)


def parse_label(text: str) -> str:
    s = " ".join((text or "").split())
    if not s:
        raise InputError("Пришли название текстом или нажми «Пропустить»")
    return s[:LABEL_MAX]
