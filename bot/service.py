"""Связка core + storage: расчёт, сохранение, пересборка отчёта."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import config

from core.analyzer import AnalysisResult, Status, analyze
from core.parser import ParsedFile, parse_file
from core.report import ReportMeta, build_excel, excel_filename, format_summary
from storage.db import Analysis, Database
from storage.files import FileStore

log = logging.getLogger(__name__)

FILE_EXPIRED_MSG = "Файл устарел, загрузи заново."


class FileExpired(Exception):
    """Исходная выгрузка удалена по сроку хранения (или пропала с диска)."""


class DailyLimit(Exception):
    def __init__(self, limit: int):
        super().__init__(f"Лимит: {limit} анализов за сутки. Попробуй позже.")


@dataclass
class Report:
    analysis_id: int
    summary: str
    excel: bytes
    excel_name: str


def _compute(data: bytes, orig_name: str, price: float, drr: float
             ) -> tuple[ParsedFile, AnalysisResult]:
    parsed = parse_file(data, filename=orig_name)
    return parsed, analyze(parsed.clusters, price, drr)


def _render(result: AnalysisResult, meta: ReportMeta) -> tuple[str, bytes]:
    return format_summary(result, meta), build_excel(result, meta)


class Service:
    def __init__(self, db: Database, files: FileStore):
        self.db = db
        self.files = files

    def _read_source(self, a: Analysis) -> bytes:
        if not a.file_path or not Path(a.file_path).exists():
            raise FileExpired
        return self.files.read(a.file_path)

    async def check_daily_limit(self, user_id: int, now: datetime | None = None) -> None:
        """Бросает DailyLimit, если за последние 24 часа уже MAX_ANALYSES_PER_DAY анализов."""
        limit = config.MAX_ANALYSES_PER_DAY
        since = (now or datetime.now()) - timedelta(days=1)
        if await self.db.count_analyses_since(user_id, since) >= limit:
            raise DailyLimit(limit)

    async def cleanup_old_files(self, now: datetime | None = None,
                                ttl_days: int | None = None) -> int:
        """Удаляет файлы выгрузок старше срока хранения. Записи в истории остаются."""
        ttl = config.FILE_TTL_DAYS if ttl_days is None else ttl_days
        cutoff = (now or datetime.now()) - timedelta(days=ttl)
        expired = await self.db.expired_uploads(cutoff)
        for upload_id, path in expired:
            self.files.delete(path)
            await self.db.clear_upload_path(upload_id)
        if expired:
            log.info("Очистка: удалено файлов старше %s дн.: %s", ttl, len(expired))
        return len(expired)

    async def _save_analysis(self, user_id: int, upload_id: int, label: str | None,
                             result: AnalysisResult) -> int:
        bs = result.by_status
        return await self.db.create_analysis(
            upload_id=upload_id, user_id=user_id, label=label, price=result.price,
            drr_norm=result.drr_norm, cnt_red=bs[Status.RED].count,
            cnt_yellow=bs[Status.YELLOW].count, cnt_green=bs[Status.GREEN].count,
            cnt_gray=bs[Status.GRAY].count, sum_red=bs[Status.RED].spend,
            total_spend=result.total_spend)

    async def _finish(self, parsed, result, analysis_id: int, label: str | None,
                      orig_name: str) -> Report:
        meta = ReportMeta(analysis_id=analysis_id, label=label, orig_name=orig_name,
                          warnings=parsed.warnings)
        summary, excel = await asyncio.to_thread(_render, result, meta)
        return Report(analysis_id, summary, excel, excel_filename(label, analysis_id))

    async def new_analysis(self, user_id: int, data: bytes, orig_name: str, label: str | None,
                           price: float, drr: float) -> Report:
        await self.check_daily_limit(user_id)
        parsed, result = await asyncio.to_thread(_compute, data, orig_name, price, drr)
        upload_id = await self.db.create_upload(user_id, orig_name, parsed.period_from,
                                                parsed.period_to)
        path = self.files.save(user_id, upload_id, data)
        await self.db.set_upload_path(upload_id, str(path))
        aid = await self._save_analysis(user_id, upload_id, label, result)
        return await self._finish(parsed, result, aid, label, orig_name)

    async def recalc(self, user_id: int, source_analysis_id: int, price: float,
                     drr: float) -> Report | None:
        src = await self.db.get_analysis(user_id, source_analysis_id)
        if src is None:
            return None
        data = self._read_source(src)
        await self.check_daily_limit(user_id)
        parsed, result = await asyncio.to_thread(_compute, data, src.orig_name, price, drr)
        aid = await self._save_analysis(user_id, src.upload_id, src.label, result)
        return await self._finish(parsed, result, aid, src.label, src.orig_name)

    async def rebuild(self, user_id: int, analysis_id: int) -> tuple[Analysis, Report] | None:
        """Пересобирает сводку и Excel сохранённого анализа из исходного файла."""
        a = await self.db.get_analysis(user_id, analysis_id)
        if a is None:
            return None
        data = self._read_source(a)
        parsed, result = await asyncio.to_thread(_compute, data, a.orig_name, a.price,
                                                        a.drr_norm)
        meta = ReportMeta(analysis_id=a.id, label=a.label, orig_name=a.orig_name,
                          created_at=a.created_at, warnings=parsed.warnings)
        summary, excel = await asyncio.to_thread(_render, result, meta)
        return a, Report(a.id, summary, excel, excel_filename(a.label, a.id))

    async def delete(self, user_id: int, analysis_id: int) -> None:
        orphan = await self.db.delete_analysis(user_id, analysis_id)
        self.files.delete(orphan)
