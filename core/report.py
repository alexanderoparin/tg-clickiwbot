"""Текстовая сводка для чата и Excel-отчёт."""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import config
from config import SUMMARY_TOP_RED, SUMMARY_TOP_YELLOW
from core.analyzer import (COL_CPO, COL_DRR, COL_STATUS, AnalysisResult, Status,
                           StatusTotals)
from core.parser import (COL_CARTS, COL_CLICKS, COL_CLUSTER, COL_CPC, COL_ORDERS, COL_POSITION,
                         COL_SPEND)

FILLS = {
    Status.RED.value: "FFC7CE",
    Status.YELLOW.value: "FFEB9C",
    Status.GREEN.value: "C6EFCE",
    Status.GRAY.value: "EDEDED",
}

FILENAME_MAX = 60
FORBIDDEN_CHARS = re.compile(r'[\\/:*?"<>|]')

log = logging.getLogger(__name__)


@dataclass
class ReportMeta:
    analysis_id: int | None = None
    label: str | None = None
    orig_name: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    warnings: list[str] = field(default_factory=list)


# ---------- форматирование ----------

def fmt_int(x: float) -> str:
    return f"{round(x):,}".replace(",", " ")


def fmt_rub(x: float) -> str:
    return f"{fmt_int(x)} ₽"


def fmt_num(x: float, digits: int = 1) -> str:
    """4 → «4», 2.08 → «2,1», 9500.5 → «9 500,5»."""
    if float(x).is_integer():
        return fmt_int(x)
    s = f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")
    return s.rstrip("0").rstrip(",") if "," in s else s


def fmt_price(x: float) -> str:
    return f"{fmt_num(x, 2)} ₽"


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def excel_filename(label: str | None, analysis_id: int | None) -> str:
    """«Бомбер.xlsx»; запрещённые символы → «_», не длиннее 60; без названия — «Анализ_{id}.xlsx»."""
    name = FORBIDDEN_CHARS.sub("_", label or "").strip()[:FILENAME_MAX].rstrip(" .")
    if not name:
        name = f"Анализ_{analysis_id if analysis_id is not None else 'новый'}"
    return f"{name}.xlsx"


# ---------- сводка ----------

def keys_word(n: int) -> str:
    """1 ключ, 2 ключа, 5 ключей."""
    return f"{fmt_int(n)} {plural(n, 'ключ', 'ключа', 'ключей')}"


def clicks_word(n: float) -> str:
    """1 клик, 2 клика, 5 кликов."""
    n = round(n)
    return f"{fmt_int(n)} {plural(n, 'клик', 'клика', 'кликов')}"


def _line_stats(r: pd.Series) -> str:
    return (f"{fmt_rub(r[COL_SPEND])}, {clicks_word(r[COL_CLICKS])}, "
            f"{fmt_int(r[COL_CARTS])} корз., {fmt_int(r[COL_ORDERS])} зак.")


def block_line(status: Status, t: StatusTotals, share: bool = False) -> str:
    """🔴 Возможно удалить: 1 ключ · 409 ₽ · 94 клика · 5 корз. · 0 зак."""
    if t.count == 0:
        return f"{status.label}: 0"
    parts = [keys_word(t.count), fmt_rub(t.spend), clicks_word(t.clicks),
             f"{fmt_int(t.carts)} корз.", f"{fmt_int(t.orders)} зак."]
    if t.drr is not None:
        parts.append(f"ДРР {fmt_num(t.drr)} %")
    s = f"{status.label}: " + " · ".join(parts)
    if share:
        s += f" ({round(t.share)} % расхода)"
    return s


def format_summary(result: AnalysisResult, meta: ReportMeta) -> str:
    e = html.escape
    title = "📊 Анализ"
    if meta.label:
        title += f": {e(meta.label)}"

    bs = result.by_status
    red, yellow = bs[Status.RED], bs[Status.YELLOW]
    search_drr = result.search_drr
    drr_txt = f"{fmt_num(search_drr)} %" if search_drr is not None else "— (нет заказов)"

    lines = [
        f"<b>{title}</b>",
        f"Цена {fmt_price(result.price)} · норма ДРР {fmt_num(result.drr_norm)} % · "
        f"допустимый CPO {fmt_rub(result.cpo_limit)}",
        "",
        f"Расход на поиск: {fmt_rub(result.total_spend)} · ДРР поиска {drr_txt}",
        block_line(Status.RED, red),
        block_line(Status.YELLOW, yellow),
        block_line(Status.GREEN, bs[Status.GREEN]),
        block_line(Status.GRAY, bs[Status.GRAY], share=True),
    ]

    if red.count:
        lines.append("\n<b>Возможно удалить:</b>")
        top = result.of_status(Status.RED).head(SUMMARY_TOP_RED)
        for i, (_, r) in enumerate(top.iterrows(), 1):
            lines.append(f"{i}. {e(r[COL_CLUSTER])} — {_line_stats(r)}")
        if red.count > SUMMARY_TOP_RED:
            lines.append(f"…и ещё {red.count - SUMMARY_TOP_RED} — в Excel")

    if yellow.count:
        lines.append("\n<b>Работать (снизить ставку, проверить карточку):</b>")
        top = result.of_status(Status.YELLOW).head(SUMMARY_TOP_YELLOW)
        for i, (_, r) in enumerate(top.iterrows(), 1):
            drr = f", ДРР {fmt_num(r[COL_DRR])} %" if pd.notna(r[COL_DRR]) else ""
            lines.append(f"{i}. {e(r[COL_CLUSTER])} — {_line_stats(r)}{drr}")
        if yellow.count > SUMMARY_TOP_YELLOW:
            lines.append(f"…и ещё {yellow.count - SUMMARY_TOP_YELLOW} — в Excel")

    tips = []
    if result.low_data_warning:
        tips.append("💡 Много кластеров без статистики — загрузи статистику за 30 дней")
    tips.extend(e(w) for w in meta.warnings)
    if tips:
        lines.append("")
        lines.extend(tips)
    return "\n".join(lines)


# ---------- Excel ----------

HEADER_FONT = Font(bold=True)
HEADER_FILL = PatternFill("solid", fgColor="D9D9D9")
MONEY = "#,##0.00"

MAIN_HEADERS = ["Кластер", "Статус", "Клики", "Корзины", "Заказы", "Затраты",
                "CPC", "CPO", "ДРР %", "Ср. позиция"]
BLOCK_HEADERS = ["Блок", "Ключей", "Затраты, ₽", "Доля расхода", "Клики", "Корзины", "Заказы",
                 "CPO", "ДРР %"]
BLOCK_FORMATS = [None, "0", MONEY, "0.0", "0", "0", "0", MONEY, "0.00"]


# ---------- фирменная шапка ----------

SITE_URL = "https://click-i.ru"
BRAND = "Clicki"
BRAND_ROWS = 4             # строки 1–4 — шапка, данные сразу с 5-й (без пустой строки)
BRAND_ROW_HEIGHT = 18      # pt; 4 × 18 pt = 72 pt = 96 px ≥ 90 px логотипа — не налезает
LOGO_PX = 90               # логотип круглый: ширина = высота, пропорции не искажаем
TABLE_HEADER_ROW = 5       # лист «Анализ»: шапка таблицы, данные с 6-й строки
DATA_START_ROW = 5         # «Минус-фразы» и «Параметры»: данные с 5-й строки
GRAY = "808080"


def _brand_header(ws, logo_path: Path | None, subtitle: str | None = None,
                  details: str | None = None) -> None:
    """Логотип в A1 (90×90), «Clicki» со ссылкой в B1, подзаголовки в B2–B3.
    Нет логотипа — только текст и warning в лог, отчёт собирается дальше."""
    for r in range(1, BRAND_ROWS + 1):
        ws.row_dimensions[r].height = BRAND_ROW_HEIGHT
    if logo_path is not None and Path(logo_path).is_file():
        try:
            from openpyxl.drawing.image import Image
            img = Image(str(logo_path))
            img.width = img.height = LOGO_PX
            ws.add_image(img, "A1")
        except Exception:
            log.warning("Не удалось вставить логотип %s в Excel", logo_path, exc_info=True)
    else:
        log.warning("Нет логотипа %s — шапка Excel без картинки", logo_path)
    b1 = ws["B1"]
    b1.value = BRAND
    b1.hyperlink = SITE_URL
    b1.font = Font(bold=True, size=16, color="0563C1", underline="single")
    b1.alignment = Alignment(vertical="center")
    if subtitle:
        ws["B2"].value = subtitle
        ws["B2"].font = Font(size=11, color=GRAY)
    if details:
        ws["B3"].value = details
        ws["B3"].font = Font(size=10, color=GRAY)


def _details_line(result: AnalysisResult, meta: ReportMeta) -> str:
    """«Бомбер · цена 9 500 ₽ · норма ДРР 4 % · 24.09.2026»"""
    parts = [meta.label] if meta.label else []
    parts += [f"цена {fmt_price(result.price)}", f"норма ДРР {fmt_num(result.drr_norm)} %",
              meta.created_at.strftime("%d.%m.%Y")]
    return " · ".join(parts)


def _write_table(ws, headers: list[str], rows: list[list], widths: dict[int, int] | None = None,
                 fills: list[str | None] | None = None, num_formats: dict[int, str] | None = None,
                 header_row: int = 1) -> None:
    """Таблица с шапкой в строке `header_row`: закрепление и автофильтр — по ней."""
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=header_row, column=j, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for i, row in enumerate(rows):
        r = header_row + 1 + i
        fill = PatternFill("solid", fgColor=fills[i]) if fills and fills[i] else None
        for j, v in enumerate(row, 1):
            if v is None and fill is None:
                continue  # пустая строка-разделитель
            cell = ws.cell(row=r, column=j, value=v)
            if fill:
                cell.fill = fill
            if num_formats and j in num_formats:
                cell.number_format = num_formats[j]
    ws.freeze_panes = f"A{header_row + 1}"
    if rows:
        last_col = get_column_letter(len(headers))
        ws.auto_filter.ref = f"A{header_row}:{last_col}{header_row + len(rows)}"
    # ширина по содержимому, с ограничением
    for j, h in enumerate(headers, 1):
        if widths and j in widths:
            w = widths[j]
        else:
            # +3 к заголовку — место под кнопку автофильтра, чтобы название не обрезалось
            vals = [len(str(h)) + 3] + [len(str(r[j - 1])) for r in rows[:500]
                                        if r[j - 1] is not None]
            w = min(max(vals) + 2, 60)
        ws.column_dimensions[get_column_letter(j)].width = w


def _nan_to_none(x):
    return None if x is None or (isinstance(x, float) and pd.isna(x)) else x


def _block_values(name: str, t: StatusTotals) -> list:
    return [name, t.count, round(t.spend, 2), round(t.share, 1), t.clicks, t.carts, t.orders,
            round(t.cpo, 2) if t.cpo is not None else "—",
            round(t.drr, 2) if t.drr is not None else "—"]


def _write_block_summary(ws, result: AnalysisResult, block_rows: dict[Status, int],
                         total_row: int, first_col: int) -> None:
    """Итоги блоков справа от таблицы. Над каждой строкой итогов — своя строка заголовков:
    у первого блока это шапка таблицы (строка 1), у следующих — пустая строка-разделитель
    перед блоком. Итог блока — в первой строке блока, «Итого» — со своим заголовком под таблицей."""
    def put(row: int, values: list, fill: PatternFill | None, bold: bool = False) -> None:
        for j, (v, fmt) in enumerate(zip(values, BLOCK_FORMATS)):
            c = ws.cell(row=row, column=first_col + j, value=v)
            if fill:
                c.fill = fill
            if bold:
                c.font = HEADER_FONT
            if fmt and not isinstance(v, str):
                c.number_format = fmt
            if isinstance(v, str) and j > 0:
                # без переноса: иначе Excel раздувает высоту строки-разделителя
                c.alignment = Alignment(horizontal="right" if not bold else "center")

    for st, row in block_rows.items():
        put(row - 1, BLOCK_HEADERS, HEADER_FILL, bold=True)
        put(row, _block_values(st.label, result.by_status[st]),
            PatternFill("solid", fgColor=FILLS[st.value]))
    put(total_row - 1, BLOCK_HEADERS, HEADER_FILL, bold=True)
    put(total_row, _block_values("Итого", result.total), HEADER_FILL, bold=True)

    ws.column_dimensions[get_column_letter(first_col)].width = 21
    for j in range(1, len(BLOCK_HEADERS)):
        ws.column_dimensions[get_column_letter(first_col + j)].width = 14  # «Доля расхода»


def build_excel(result: AnalysisResult, meta: ReportMeta,
                logo_path: Path | str | None = None) -> bytes:
    """`logo_path` — логотип шапки; по умолчанию config.LOGO_PATH."""
    logo = Path(logo_path) if logo_path is not None else config.LOGO_PATH
    wb = Workbook()

    # --- Анализ ---
    ws = wb.active
    ws.title = "Анализ"
    _brand_header(ws, logo, "Анализ рекламных ключей WB по ДРР", _details_line(result, meta))
    d = result.with_spend()
    rows, fills = [], []
    block_rows: dict[Status, int] = {}  # статус → строка листа с первым ключом блока
    for _, r in d.iterrows():
        st = Status(r[COL_STATUS])
        if st not in block_rows:
            if block_rows:  # пустая строка-разделитель между блоками
                rows.append([None] * len(MAIN_HEADERS))
                fills.append(None)
            block_rows[st] = TABLE_HEADER_ROW + 1 + len(rows)
        rows.append([
            r[COL_CLUSTER], Status(r[COL_STATUS]).label,
            r[COL_CLICKS], r[COL_CARTS], r[COL_ORDERS], r[COL_SPEND], r[COL_CPC],
            None if pd.isna(r[COL_CPO]) else round(float(r[COL_CPO]), 2),
            None if pd.isna(r[COL_DRR]) else round(float(r[COL_DRR]), 2),
            _nan_to_none(r[COL_POSITION]) or None,
        ])
        fills.append(FILLS.get(r[COL_STATUS]))
    _write_table(ws, MAIN_HEADERS, rows, fills=fills, widths={2: 21},
                 num_formats={3: "0", 4: "0", 5: "0", 6: MONEY, 7: MONEY, 8: MONEY, 9: "0.00",
                              10: "0.0"},
                 header_row=TABLE_HEADER_ROW)
    if rows:
        # одна пустая колонка после «Ср. позиция»; «Итого» с заголовком — под таблицей:
        # заголовок в первой строке после таблицы, «Итого» — во второй
        _write_block_summary(ws, result, block_rows,
                             total_row=TABLE_HEADER_ROW + len(rows) + 2,
                             first_col=len(MAIN_HEADERS) + 2)

    # --- Минус-фразы ---
    ws = wb.create_sheet("Минус-фразы")
    _brand_header(ws, logo)
    head = ws.cell(row=DATA_START_ROW, column=1, value="Минус-фразы")
    head.font = HEADER_FONT
    reds = result.of_status(Status.RED)[COL_CLUSTER].tolist()
    # сплошной столбец без пустых строк — копируется в кабинет одним выделением
    for i, c in enumerate(reds, DATA_START_ROW + 1):
        ws.cell(row=i, column=1, value=c)
    ws.column_dimensions["A"].width = min(max([len(c) for c in reds] + [14]) + 2, 80)

    # --- Параметры ---
    ws = wb.create_sheet("Параметры")
    params = [
        ("Цена товара, ₽", result.price),
        ("Норма ДРР, %", result.drr_norm),
        ("Допустимый CPO, ₽", round(result.cpo_limit, 2)),
        ("WORK_SHARE", result.work_share),
        ("Исходный файл", meta.orig_name or ""),
        ("Название", meta.label or ""),
        ("Дата анализа", meta.created_at.strftime("%d.%m.%Y %H:%M")),
        ("Расход на поиск, ₽", round(result.total_spend, 2)),
        ("ДРР поиска, %", round(result.search_drr, 2) if result.search_drr is not None else "—"),
    ]
    _brand_header(ws, logo)
    for i, (k, v) in enumerate(params, DATA_START_ROW):
        ws.cell(row=i, column=1, value=k).font = HEADER_FONT
        ws.cell(row=i, column=2, value=v)
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = max(40, len(meta.orig_name or "") + 2)

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
