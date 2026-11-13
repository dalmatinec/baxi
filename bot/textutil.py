"""Мелкие помощники для текста без Telegram-зависимостей."""

import html
import re

_URL = re.compile(r"^(https?://|tg://|t\.me/)\S+$", re.I)


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


# Вид VIP-участников: user_id → (id премиум-эмодзи, запасной эмодзи, ник). Заполняет services/stars.refresh_looks
VIP_LOOK: dict[int, tuple[str, str, str]] = {}


def mention(user_id: int, name: str) -> str:
    """Кликабельное имя. У VIP: свой премиум-эмодзи (или 👑) и жирный ник, который он задал сам."""
    look = VIP_LOOK.get(user_id)
    if look is None:
        return f'<a href="tg://user?id={user_id}">{esc(name) or "аноним"}</a>'
    emoji_id, alt, nick = look
    icon = f'<tg-emoji emoji-id="{emoji_id}">{esc(alt or "👑")}</tg-emoji>' if emoji_id else "👑"
    return f'{icon} <b><a href="tg://user?id={user_id}">{esc(nick or name) or "аноним"}</a></b>'


def full_name(first: str | None, last: str | None, username: str | None = None) -> str:
    """Имя человека. Если в имени нет ни одной буквы (одни эмодзи), берём юзернейм:
    иначе нейросеть не может обратиться к человеку и начинает путать имена."""
    name = " ".join(x for x in (first, last) if x).strip()
    if not any(ch.isalpha() for ch in name):
        return username or name or "аноним"
    return name


COLORS = {"зел": "success", "green": "success", "син": "primary", "blue": "primary",
          "крас": "danger", "red": "danger"}
COLOR_NAMES = {"success": "зелёная", "primary": "синяя", "danger": "красная"}


def parse_buttons(text: str) -> tuple[list[list[list[str]]], list[str]]:
    """Кнопки из текста. Каждая строка — ряд, кнопки в ряду через «|», цвет можно дописать третьим:

        Общение - https://t.me/chat | Найти - https://t.me/bot - зелёная
        Хочу 💋 - https://example.com - красная

    Возвращает (ряды, ошибки). Кнопка: [текст, ссылка] или [текст, ссылка, primary|success|danger]."""
    rows, errors = [], []
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        row = []
        for part in line.split("|"):
            part = part.strip()
            pieces = re.split(r"\s+[-—–]\s+", part)
            if len(pieces) < 2:
                errors.append(f"строка {n}: «{part}» — нужно «Текст - ссылка»")
                continue
            style = ""
            if len(pieces) >= 3:
                word = pieces[-1].strip().lower()
                style = next((v for k, v in COLORS.items() if word.startswith(k)), "")
                if not style:
                    errors.append(f"строка {n}: цвет «{pieces[-1]}» не знаю, есть зелёная, синяя, красная")
                    continue
                pieces = pieces[:-1]
            label, url = " - ".join(pieces[:-1]).strip(), pieces[-1].strip()
            if url.lower().startswith("t.me/"):
                url = "https://" + url
            if not _URL.match(url):
                errors.append(f"строка {n}: «{url}» не похоже на ссылку")
                continue
            row.append([label[:64], url] + ([style] if style else []))
        if row:
            rows.append(row[:8])
    return rows, errors


def buttons_to_text(rows: list) -> str:
    def one(b: list) -> str:
        return f"{b[0]} - {b[1]}" + (f" - {COLOR_NAMES[b[2]]}" if len(b) > 2 and b[2] in COLOR_NAMES else "")
    return "\n".join(" | ".join(one(b) for b in row) for row in rows)


def short(text: str, n: int = 40) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------- чтобы бот не палился как ИИ ----------

_HUMANIZE = str.maketrans({"—": "-", "–": "-", "−": "-", "«": '"', "»": '"', "„": '"', "“": '"', "”": '"'})


def humanize(text: str) -> str:
    """Убирает то, что выдаёт нейросеть: длинные тире, кавычки-ёлочки, многоточие одним символом."""
    return (text or "").translate(_HUMANIZE).replace("…", "...")


# ---------- мат, смех, спасибо ----------

_WORD = re.compile(r"[а-яёa-z]+", re.I)
_MAT_PARTS = re.compile(r"(хуй|хуе|хуё|хуя|хуи|хую|пизд|бля|залуп|гандон|шлюх|дроч|мудак|мудил|мудач|"
                        r"пидор|пидар|пидр|нахер|похер|херн)")
_MAT_EB = re.compile(r"^(за|на|по|от|у|вы|до|раз|рас|при|об|съ|въ|подъ|недо|пере|про|из|с)?[её]б"
                     r"(а|у|л|н|и|ы|о|ё|к|$)")
_MAT_WORDS = {"сука", "суки", "суке", "суку", "сукой", "сучка", "сучара", "манда", "ёб", "еб"}
_NOT_MAT = ("страх", "застрах", "употребл", "скребл", "колебл", "гребл", "психбля")


def is_mat(text: str) -> bool:
    for w in _WORD.findall((text or "").lower()):
        if w.startswith(_NOT_MAT):
            continue
        if w in _MAT_WORDS or _MAT_PARTS.search(w) or _MAT_EB.match(w):
            return True
    return False


_LAUGH = re.compile(r"^\W*((а?х[аы]){2,}\w*|(х[аеи]){2,}\w*|ах+а+\w*|пх[ах]+\w*|ору+|ржу+|ржака|лол|кек|"
                    r"[😂🤣😹😆😅]+)\W*$", re.I)


def is_laugh(text: str) -> bool:
    """Короткий ответ-смех: «ахаха», «ору», «😂». По ним считаем самого смешного."""
    t = (text or "").strip().lower()
    return len(t) <= 40 and bool(_LAUGH.match(t))


_PLUS = {"+", "+1", "++", "спасибо", "спс", "пасиб", "благодарю", "респект", "👍", "💯", "плюс", "сяб"}
_MINUS = {"-", "-1", "--", "минус", "👎"}


def rep_delta(text: str) -> int:
    """+1 / -1 к репутации, если сообщение целиком из «спасибо», «+», «-» и т.п."""
    t = (text or "").strip().lower().rstrip("!.)").strip()
    if t in _PLUS or t.startswith("спасибо"):
        return 1
    if t in _MINUS:
        return -1
    return 0


# ---------- дни рождения ----------

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря"]
_BDAY = re.compile(r"(?:мой|у меня)\s+(?:др|день\s+рождения|днюха)\s*[:\-]?\s*(\d{1,2})\s*[./\s]\s*(\d{1,2}|[а-яё]+)",
                   re.I)


def parse_birthday(text: str) -> str | None:
    """«мой др 12.05», «у меня день рождения 3 марта» → '05-12'. Иначе None."""
    m = _BDAY.search(text or "")
    if not m:
        return None
    day = int(m.group(1))
    raw = m.group(2).lower()
    if raw.isdigit():
        month = int(raw)
    else:
        month = next((i + 1 for i, name in enumerate(MONTHS) if name.startswith(raw[:3])), 0)
    days_in = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not 1 <= month <= 12 or not 1 <= day <= days_in[month - 1]:
        return None
    return f"{month:02d}-{day:02d}"


def human_date(mmdd: str) -> str:
    month, day = mmdd.split("-")
    return f"{int(day)} {MONTHS[int(month) - 1]}"


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """plural(5, ('сообщение', 'сообщения', 'сообщений')) → 'сообщений'."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return forms[1]
    return forms[2]


MSGS = ("сообщение", "сообщения", "сообщений")
REACTS = ("реакция", "реакции", "реакций")
