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
# у копий white label свой файл настроек: LINKHUB_ENV=/opt/linkhub/instances/<имя>/.env
_load_env(Path(os.getenv("LINKHUB_ENV") or ROOT / ".env"))


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


# main: твой основной бот (продаёт рекламу, аренду и white label). client: копия для клиента
EDITION = os.getenv("EDITION", "main")
IS_MAIN = EDITION == "main"
INSTANCES_DIR = Path(os.getenv("INSTANCES_DIR", str(ROOT / "instances")))
# у копии: имя в папке instances, по нему она находит свою лицензию
INSTANCE_NAME = os.getenv("INSTANCE_NAME", "")

# Оплата USDT в сети TON: адрес кошелька для приёма и бесплатный ключ toncenter
PAY_TON_ADDRESS = os.getenv("PAY_TON_ADDRESS", "")
TONCENTER_API_KEY = os.getenv("TONCENTER_API_KEY", "")
TONCENTER_URL = os.getenv("TONCENTER_URL", "https://toncenter.com/api/v3").rstrip("/")
USDT_MASTER = os.getenv("USDT_MASTER", "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs")
# канал для формата «закреп в канале» (бот должен быть админом с правом закреплять), например -1001234567890
AD_CHANNEL_ID = int(os.getenv("AD_CHANNEL_ID", "0") or 0)
# сколько часов ждать одобрения чата, потом бот сам выходит
APPROVAL_HOURS = _int("APPROVAL_HOURS", 24)


def check() -> None:
    if not BOT_TOKEN:
        raise SystemExit("В .env не задан BOT_TOKEN")
    if not OWNER_IDS:
        raise SystemExit("В .env не задан OWNER_IDS (твой Telegram ID)")
