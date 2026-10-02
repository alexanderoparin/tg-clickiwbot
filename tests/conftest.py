import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "tests" / "fixtures" / "Топ_поисковых_кластеров_2026-09-17_-_2026-09-23.xlsx"


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Тесты никогда не пишут в боевой data/: БД, выгрузки и кеш file_id — во временной папке."""
    import config
    data = tmp_path / "_data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "DB_PATH", data / "bot.db")
    monkeypatch.setattr(config, "UPLOADS_DIR", data / "uploads")
    monkeypatch.setattr(config, "MEDIA_CACHE", data / "media_cache.json")
    # настройки из боевого .env не влияют на тесты
    monkeypatch.setattr(config, "ALLOWED_USER_IDS", set())
    monkeypatch.setattr(config, "ADMIN_IDS", set())
    monkeypatch.setattr(config, "PRIVACY_URL", "")
    monkeypatch.setattr(config, "NOTIFY_NEW_USERS", True)


@pytest.fixture(scope="session")
def fixture_path() -> Path:
    if not FIXTURE.exists():
        pytest.skip(f"Нет фикстуры {FIXTURE.name}")
    return FIXTURE


@pytest.fixture(scope="session")
def parsed(fixture_path):
    from core.parser import parse_file
    return parse_file(fixture_path)
