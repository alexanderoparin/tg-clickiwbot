"""Расчёт ДРР и статусов по кластерам."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from config import LOW_DATA_SHARE_WARN, WORK_SHARE
from core.parser import COL_CARTS, COL_CLICKS, COL_ORDERS, COL_SPEND


class Status(str, Enum):
    NO_SPEND = "no_spend"
    RED = "red"
    YELLOW = "yellow"
    GREEN = "green"
    GRAY = "gray"

    @property
    def label(self) -> str:
        return STATUS_LABELS[self]


STATUS_LABELS = {
    Status.NO_SPEND: "— Без расхода",
    Status.RED: "🔴 Возможно удалить",
    Status.YELLOW: "🟡 Работать",
    Status.GREEN: "🟢 Норма",
    Status.GRAY: "⚪ Мало данных",
}

# Порядок в отчёте: 🔴 → 🟡 → ⚪ → 🟢
STATUS_ORDER = {Status.RED: 0, Status.YELLOW: 1, Status.GRAY: 2, Status.GREEN: 3, Status.NO_SPEND: 4}

COL_REVENUE = "revenue"
COL_DRR = "drr"
COL_CPO = "cpo"
COL_STATUS = "status"  # хранит Status.value (строку)


def classify(spend: float, orders: float, drr: float | None, drr_norm: float,
             cpo_limit: float, work_share: float = WORK_SHARE) -> Status:
    """Статус кластера. Порядок проверок важен — см. ТЗ."""
    if spend == 0:
        return Status.NO_SPEND
    if orders == 0 and spend >= cpo_limit:
        return Status.RED
    if orders > 0 and drr is not None and drr > drr_norm:
        return Status.YELLOW
    if orders == 0 and spend >= cpo_limit * work_share:
        return Status.YELLOW
    if orders > 0 and drr is not None and drr <= drr_norm:
        return Status.GREEN
    return Status.GRAY


# Блоки в отчёте (без «Без расхода»)
BLOCKS = (Status.RED, Status.YELLOW, Status.GRAY, Status.GREEN)


@dataclass
class StatusTotals:
    """Итоги блока статуса (или всего поиска). CPO и ДРР — по сумме блока, None если заказов 0."""
    count: int
    spend: float
    clicks: float = 0.0
    carts: float = 0.0
    orders: float = 0.0
    share: float = 0.0  # доля от общего расхода, %
    cpo: float | None = None
    drr: float | None = None


def _totals(part: pd.DataFrame, price: float, total_spend: float) -> StatusTotals:
    spend = float(part[COL_SPEND].sum())
    orders = float(part[COL_ORDERS].sum())
    return StatusTotals(
        count=len(part), spend=spend, clicks=float(part[COL_CLICKS].sum()),
        carts=float(part[COL_CARTS].sum()), orders=orders,
        share=spend / total_spend * 100 if total_spend else 0.0,
        cpo=spend / orders if orders > 0 else None,
        drr=spend / (orders * price) * 100 if orders > 0 else None,
    )


@dataclass
class AnalysisResult:
    df: pd.DataFrame  # все кластеры + revenue, drr, cpo, status
    price: float
    drr_norm: float
    cpo_limit: float
    work_share: float
    total_spend: float
    total_orders: float
    by_status: dict[Status, StatusTotals]
    total: StatusTotals  # «Итого» по кластерам с расходом

    @property
    def search_drr(self) -> float | None:
        revenue = self.total_orders * self.price
        return self.total_spend / revenue * 100 if revenue > 0 else None

    @property
    def low_data_share(self) -> float:
        return self.by_status[Status.GRAY].spend / self.total_spend if self.total_spend else 0.0

    @property
    def low_data_warning(self) -> bool:
        return self.low_data_share > LOW_DATA_SHARE_WARN

    def with_spend(self) -> pd.DataFrame:
        """Кластеры с расходом, отсортированные 🔴 → 🟡 → ⚪ → 🟢, внутри по затратам ↓."""
        d = self.df[self.df[COL_STATUS] != Status.NO_SPEND.value].copy()
        d["_ord"] = d[COL_STATUS].map({k.value: v for k, v in STATUS_ORDER.items()})
        d = d.sort_values(["_ord", COL_SPEND], ascending=[True, False], kind="stable")
        return d.drop(columns="_ord")

    def of_status(self, status: Status) -> pd.DataFrame:
        d = self.df[self.df[COL_STATUS] == Status(status).value]
        return d.sort_values(COL_SPEND, ascending=False, kind="stable")


def analyze(clusters: pd.DataFrame, price: float, drr_norm: float,
            work_share: float = WORK_SHARE) -> AnalysisResult:
    if price <= 0:
        raise ValueError("price должна быть > 0")
    cpo_limit = price * drr_norm / 100
    df = clusters.copy()
    orders = df[COL_ORDERS]
    spend = df[COL_SPEND]
    df[COL_REVENUE] = orders * price
    df[COL_DRR] = (spend / df[COL_REVENUE] * 100).where(df[COL_REVENUE] > 0)
    df[COL_CPO] = (spend / orders).where(orders > 0)
    df[COL_STATUS] = [
        classify(s, o, None if pd.isna(d) else d, drr_norm, cpo_limit, work_share).value
        for s, o, d in zip(spend, orders, df[COL_DRR])
    ]

    total_spend = float(spend.sum())
    by_status = {st: _totals(df[df[COL_STATUS] == st.value], price, total_spend) for st in Status}
    total = _totals(df[df[COL_STATUS] != Status.NO_SPEND.value], price, total_spend)

    return AnalysisResult(
        df=df, price=price, drr_norm=drr_norm, cpo_limit=cpo_limit, work_share=work_share,
        total_spend=total_spend, total_orders=float(orders.sum()), by_status=by_status,
        total=total,
    )
