"""Настройки из файла .env. Всё, что меняется без правки кода, лежит здесь."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_env(path: Path) -> None:
    """Простая загрузка .env без лишних библиотек. Уже заданные переменные не трогает."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


ROOT = Path(__file__).resolve().parent.parent
_load_env(ROOT / ".env")


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_IDS = {int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x.lstrip("-").isdigit()}

# Нейросеть: любой сервис с API как у OpenAI (DeepSeek, OpenRouter, GigaChat через прокси и т.д.)
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")
AI_TIMEOUT = _float("AI_TIMEOUT", 40)
AI_MAX_TOKENS = _int("AI_MAX_TOKENS", 160)
AI_TEMPERATURE = _float("AI_TEMPERATURE", 1.1)

# Цены модели в долларах за 1 млн токенов, нужны для подсчёта расхода
PRICE_IN = _float("PRICE_IN", 0.30)
PRICE_OUT = _float("PRICE_OUT", 1.20)
# Сколько долларов в сутки можно потратить. Кончились, бот отвечает фразами из базы.
DAILY_LIMIT_USD = _float("DAILY_LIMIT_USD", 0.30)

# Сколько последних сообщений чата видит нейросеть
CONTEXT_MESSAGES = _int("CONTEXT_MESSAGES", 20)
# Сколько сообщений чата хранить в базе (для памяти о юзерах нужно больше, чем контекст)
HISTORY_KEEP = _int("HISTORY_KEEP", 2000)
# Через сколько сообщений юзера обновлять заметки о нём (0 = не обновлять)
MEMORY_EVERY = _int("MEMORY_EVERY", 25)

TZ = ZoneInfo(os.getenv("TZ_NAME", "Asia/Almaty"))
DATA_DIR = ROOT / os.getenv("DATA_DIR", "data")
DB_PATH = DATA_DIR / "bot.db"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Значения по умолчанию для нового чата (потом меняются в /admin)
DEFAULT_NAME = os.getenv("DEFAULT_NAME", "Марат")
DEFAULT_PERSONA = os.getenv(
    "DEFAULT_PERSONA",
    "свой пацан из чата, дерзкий и весёлый, любит подколоть, но не злой. "
    "отвечает коротко, по-простому, со сленгом",
)
DEFAULT_TOPIC = os.getenv("DEFAULT_TOPIC", "общение обо всём, болтовня, приколы")
DEFAULT_CHANCE = _float("DEFAULT_CHANCE", 0.04)      # шанс влезть в чужой разговор
DEFAULT_AI_SHARE = _float("DEFAULT_AI_SHARE", 0.30)  # доля таких влезаний через ИИ
DEFAULT_COOLDOWN = _int("DEFAULT_COOLDOWN", 90)      # пауза между самовольными влезаниями, сек


def check() -> None:
    if not BOT_TOKEN:
        raise SystemExit("В .env не задан BOT_TOKEN")
    if not OWNER_IDS:
        raise SystemExit("В .env не задан OWNER_IDS (твой Telegram ID)")
