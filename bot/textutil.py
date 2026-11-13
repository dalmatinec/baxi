"""Мелкие помощники для текста без Telegram-зависимостей."""

import html
import re

_URL = re.compile(r"^(https?://|tg://|t\.me/)\S+$", re.I)


def esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{esc(name) or "аноним"}</a>'


def full_name(first: str | None, last: str | None) -> str:
    return " ".join(x for x in (first, last) if x).strip() or "аноним"


def parse_buttons(text: str) -> tuple[list[list[list[str]]], list[str]]:
    """Кнопки из текста. Каждая строка — ряд, кнопки в ряду через «|»:

        Общение - https://t.me/chat | Найти - https://t.me/bot
        Хочу 💋 - https://example.com

    Возвращает (ряды, ошибки). Ряд: [[текст, ссылка], ...]."""
    rows, errors = [], []
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        row = []
        for part in line.split("|"):
            part = part.strip()
            m = re.match(r"^(.+?)\s+[-—–]\s+(\S+)$", part)
            if not m:
                errors.append(f"строка {n}: «{part}» — нужно «Текст - ссылка»")
                continue
            label, url = m.group(1).strip(), m.group(2).strip()
            if url.lower().startswith("t.me/"):
                url = "https://" + url
            if not _URL.match(url):
                errors.append(f"строка {n}: «{url}» не похоже на ссылку")
                continue
            row.append([label[:64], url])
        if row:
            rows.append(row[:8])
    return rows, errors


def buttons_to_text(rows: list) -> str:
    return "\n".join(" | ".join(f"{label} - {url}" for label, url in row) for row in rows)


def short(text: str, n: int = 40) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"
