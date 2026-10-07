"""Настройки из окружения и параметры расчёта."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --- окружение ---
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
# Исходящий прокси к Telegram API (socks5://host:port или http://host:port).
# Пусто — прямое подключение. Нужен, если с сервера api.telegram.org недоступен.
TELEGRAM_PROXY: str = os.getenv("TELEGRAM_PROXY", "").strip()


def _ids(name: str) -> set[int]:
    return {int(x) for x in os.getenv(name, "").replace(" ", "").split(",") if x}


# пустой ALLOWED_USER_IDS = бот открыт для всех
ALLOWED_USER_IDS: set[int] = _ids("ALLOWED_USER_IDS")
ADMIN_IDS: set[int] = _ids("ADMIN_IDS")
DATA_DIR: Path = Path(os.getenv("DATA_DIR", "data"))
if not DATA_DIR.is_absolute():
    DATA_DIR = BASE_DIR / DATA_DIR
DB_PATH: Path = DATA_DIR / "bot.db"
UPLOADS_DIR: Path = DATA_DIR / "uploads"
LOG_DIR: Path = BASE_DIR / "logs"
# Видео-подсказка «как скачать выгрузку» (MP4 H.264 без звука или GIF, до 10 МБ)
HOW_TO_VIDEO: Path = BASE_DIR / "assets" / "how_to_download.mp4"
# Видео-подсказка «где смотреть цену реализации» (шаг цены и инструкция)
HOW_TO_PRICE_VIDEO: Path = BASE_DIR / "assets" / "how_to_price.mp4"
# Кеш file_id загруженных в Telegram медиа и документов
MEDIA_CACHE: Path = DATA_DIR / "media_cache.json"
# Логотип в шапке Excel-отчёта (PNG с прозрачным фоном)
LOGO_PATH: Path = BASE_DIR / "assets" / "logo.png"
# «📚 Полезные материалы»: папка с PDF (список — bot/texts.py → MATERIALS)
MATERIALS_DIR: Path = BASE_DIR / "assets" / "materials"
MATERIALS_REPEAT_SEC: int = 60      # повторное нажатие раньше — файлы не шлём заново

# --- лиды и уведомления ---
# Ссылка на политику обработки персональных данных; пусто — строку со ссылкой не показываем
PRIVACY_URL: str = os.getenv("PRIVACY_URL", "").strip()
# Уведомлять админов о новом пользователе
NOTIFY_NEW_USERS: bool = os.getenv("NOTIFY_NEW_USERS", "true").strip().lower() not in (
    "0", "false", "no", "off", "")
STUCK_MINUTES: int = 30             # «застрял», если с последнего шага прошло больше
STUCK_DAYS: int = 7                 # /stuck — за сколько дней

# --- параметры расчёта ---
# Доля от допустимого CPO, начиная с которой кластер без заказов идёт в «Работать»
WORK_SHARE: float = 0.5
# Порог доли расхода «мало данных», после которого советуем взять период длиннее
LOW_DATA_SHARE_WARN: float = 0.30
# Сколько строк показывать в сводке
SUMMARY_TOP_RED: int = 5
SUMMARY_TOP_YELLOW: int = 5
# Ожидаемая валюта выгрузки
EXPECTED_CURRENCY: str = "RUB"

# Варианты нормы ДРР на кнопках
DRR_PRESETS: tuple[float, ...] = tuple(range(1, 11))  # 1–10 %
PRICE_MIN, PRICE_MAX = 1, 10_000_000
DRR_MIN, DRR_MAX = 0.1, 100

# --- ограничения (важно для открытого режима) ---
MAX_FILE_SIZE: int = 10 * 1024 * 1024       # байт
MAX_CLUSTER_ROWS: int = 20_000              # строк в листе кластеров
MAX_ANALYSES_PER_DAY: int = 20              # на пользователя за последние 24 часа
FLOOD_INTERVAL: float = 1.0                 # секунд между сообщениями пользователя
FILE_TTL_DAYS: int = 60                     # сколько хранить загруженные файлы
CLEANUP_INTERVAL_SEC: int = 24 * 60 * 60    # как часто запускать очистку

# --- история ---
HISTORY_PAGE_SIZE: int = 10
