"""Хранение исходных выгрузок: {uploads_dir}/{user_id}/{upload_id}.xlsx."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


class FileStore:
    def __init__(self, uploads_dir: Path | str):
        self.root = Path(uploads_dir)

    def path_for(self, user_id: int, upload_id: int) -> Path:
        return self.root / str(user_id) / f"{upload_id}.xlsx"

    def save(self, user_id: int, upload_id: int, data: bytes) -> Path:
        p = self.path_for(user_id, upload_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def read(self, path: str | Path) -> bytes:
        return Path(path).read_bytes()

    def delete(self, path: str | Path | None) -> None:
        if not path:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            log.exception("Не удалось удалить файл %s", path)
