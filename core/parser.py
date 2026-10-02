"""Чтение и валидация выгрузки WB «Топ поисковых кластеров»."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from config import MAX_CLUSTER_ROWS, MAX_FILE_SIZE

MAIN_SHEET = "Топ поисковых кластеров"

COL_CLUSTER = "Кластер"
COL_BID = "Статус и тип ставки"
COL_POSITION = "Средняя позиция"
COL_CLICKS = "Клики"
COL_CARTS = "Добавления в корзину"
COL_ORDERS_WITH = "Заказов с этим товаром"
COL_ORDERS = "Заказанные товары"
COL_SPEND = "Затраты"
COL_CPC = "CPC"
COL_CURRENCY = "Валюта"
COL_ACTUAL = "Актуальность"

REQUIRED_COLS = (COL_CLUSTER, COL_CLICKS, COL_CARTS, COL_ORDERS, COL_SPEND)
SUM_COLS = (COL_CLICKS, COL_CARTS, COL_ORDERS_WITH, COL_ORDERS, COL_SPEND)

PERIOD_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*_?-_?\s*(\d{4}-\d{2}-\d{2})")

NOT_EXCEL_MSG = "Это не Excel-файл, пришли выгрузку „Топ поисковых кластеров“"


class ParseError(Exception):
    """Ошибка с текстом, который можно показать пользователю."""


@dataclass
class ParsedFile:
    clusters: pd.DataFrame
    period_from: date | None
    period_to: date | None
    warnings: list[str] = field(default_factory=list)


def parse_period(filename: str | None) -> tuple[date | None, date | None]:
    if not filename:
        return None, None
    m = PERIOD_RE.search(filename)
    if not m:
        return None, None
    try:
        return date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
    except ValueError:
        return None, None


def _to_float(series: pd.Series) -> pd.Series:
    if series.dtype == object or pd.api.types.is_string_dtype(series):
        series = (
            series.astype(str)
            .str.replace(" ", "", regex=False)
            .str.replace(" ", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
    return pd.to_numeric(series, errors="coerce").fillna(0.0).astype(float)


def _find_main_sheet(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    if MAIN_SHEET in sheets:
        return sheets[MAIN_SHEET]
    for df in sheets.values():
        cols = {str(c).strip() for c in df.columns}
        if COL_CLUSTER in cols and COL_SPEND in cols:
            return df
    return None


def _normalize_clusters(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    df = df.rename(columns=lambda c: str(c).strip())
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ParseError("В файле не хватает колонок: " + ", ".join(f"«{c}»" for c in missing))

    warnings: list[str] = []
    df = df.copy()
    df[COL_CLUSTER] = df[COL_CLUSTER].fillna("").astype(str).str.strip()
    df = df[df[COL_CLUSTER] != ""]

    for c in SUM_COLS + (COL_POSITION, COL_CPC):
        if c in df.columns:
            df[c] = _to_float(df[c])
        else:
            df[c] = 0.0
    for c in (COL_BID, COL_CURRENCY, COL_ACTUAL):
        if c not in df.columns:
            df[c] = ""
        df[c] = df[c].fillna("").astype(str).str.strip()

    currencies = {v for v in df[COL_CURRENCY].unique() if v}
    if currencies and currencies != {"RUB"}:
        warnings.append("⚠️ Валюта в файле не RUB: " + ", ".join(sorted(currencies)))

    if df[COL_CLUSTER].duplicated().any():
        # средние позиция и CPC пересчитываем взвешенно
        df["_pos_w"] = df[COL_POSITION] * df[COL_CLICKS]
        agg = {c: "sum" for c in SUM_COLS}
        agg.update({"_pos_w": "sum", COL_POSITION: "mean"})
        agg.update({c: "first" for c in (COL_BID, COL_CURRENCY, COL_ACTUAL)})
        g = df.groupby(COL_CLUSTER, sort=False, as_index=False).agg(agg)
        clicks = g[COL_CLICKS]
        g[COL_POSITION] = (g["_pos_w"] / clicks).where(clicks > 0, g[COL_POSITION])
        g[COL_CPC] = (g[COL_SPEND] / clicks).where(clicks > 0, 0.0)
        df = g.drop(columns="_pos_w")

    cols = [COL_CLUSTER, COL_BID, COL_POSITION, COL_CLICKS, COL_CARTS, COL_ORDERS_WITH,
            COL_ORDERS, COL_SPEND, COL_CPC, COL_CURRENCY, COL_ACTUAL]
    return df[cols].reset_index(drop=True), warnings


def too_big_message(max_size: int = MAX_FILE_SIZE) -> str:
    return f"Файл больше {max_size // (1024 * 1024)} МБ. Выгрузи период покороче."


def parse_file(source: str | Path | bytes | BinaryIO, filename: str | None = None,
               max_rows: int = MAX_CLUSTER_ROWS, max_size: int = MAX_FILE_SIZE) -> ParsedFile:
    """Читает выгрузку. `filename` — исходное имя файла (для периода и проверки расширения)."""
    if filename is None and isinstance(source, (str, Path)):
        filename = Path(source).name
    if filename and not filename.lower().endswith(".xlsx"):
        raise ParseError(NOT_EXCEL_MSG)
    if isinstance(source, (str, Path)):
        size = Path(source).stat().st_size
    elif isinstance(source, bytes):
        size = len(source)
        source = BytesIO(source)
    else:
        size = None
    if size is not None and size > max_size:
        raise ParseError(too_big_message(max_size))

    try:
        sheets = pd.read_excel(source, sheet_name=None, engine="openpyxl")
    except Exception as e:  # битый zip, не xlsx и т. п.
        raise ParseError(NOT_EXCEL_MSG) from e

    main = _find_main_sheet(sheets)
    if main is None:
        raise ParseError(
            "Не нашёл лист с кластерами. Нужен лист «Топ поисковых кластеров» "
            "с колонками «Кластер» и «Затраты»."
        )
    if len(main) > max_rows:
        raise ParseError(f"В листе кластеров {len(main):,} строк — это больше лимита "
                         f"{max_rows:,}. Выгрузи период покороче.".replace(",", " "))
    clusters, warnings = _normalize_clusters(main)
    if clusters.empty:
        raise ParseError("В файле нет ни одного кластера.")

    p_from, p_to = parse_period(filename)
    return ParsedFile(clusters=clusters, period_from=p_from, period_to=p_to,
                      warnings=warnings)
