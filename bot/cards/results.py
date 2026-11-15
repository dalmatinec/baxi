"""Итоги дня двумя карточками в стиле круиза: «Бортовой журнал» (номинации) и «Команда корабля» (топ дня).

Только рисование: на вход готовые данные и аватарки (байты или None), на выход JPEG.
Данные собирает services/daily.py. Без Pillow функции возвращают None, и итоги уходят текстом."""

import io
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter
except ImportError:
    Image = None

from bot.economy.cards import _clean, _font

ASSETS = Path(__file__).parent / "assets"
W, H = 1080, 1350
PAD = 64
TOP, BOTTOM = (31, 111, 139), (8, 30, 62)          # бирюзовое море сверху, глубина снизу
TEAL, GOLD, MUTED = (103, 232, 249), (250, 204, 21), (203, 213, 225)
RED = (229, 72, 77)
INITIAL_COLORS = [(59, 130, 246), (234, 88, 12), (22, 163, 74), (219, 39, 119), (124, 58, 237), (13, 148, 136)]


@dataclass
class Nomination:
    icon: str          # имя файла в assets без .png
    label: str         # Капитан болтовни
    user_id: int
    name: str
    sub: str           # 214 сообщений


@dataclass
class Crew:
    user_id: int
    name: str
    msgs: int


@dataclass
class DayData:
    chat_title: str
    date: str
    total: int
    people: int
    peak: str
    noms: list[Nomination] = field(default_factory=list)
    top: list[Crew] = field(default_factory=list)
    star: str = ""                 # Человек дня: Аня · 168 сообщений
    bot_name: str = "Бакси"
    site: str = ""


@lru_cache(maxsize=16)
def _icon(name: str, size: int):
    path = ASSETS / f"{name}.png"
    if not path.exists():
        return None
    img = Image.open(path).convert("RGBA")
    k = size / max(img.size)
    return img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)


def _background() -> "Image.Image":
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-260, -320, 640, 420), fill=(125, 211, 252, 70))
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    img.paste(glow, (0, 0), glow)
    waves = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wd = ImageDraw.Draw(waves)
    import math
    for n, (base, amp, alpha) in enumerate(((H - 170, 22, 45), (H - 120, 26, 70))):
        pts = [(x, base + amp * math.sin(x / 95 + n * 2.1)) for x in range(0, W + 10, 10)]
        wd.polygon(pts + [(W, H), (0, H)], fill=(96, 165, 250, alpha))
    img.paste(waves, (0, 0), waves)
    return img.convert("RGBA")


def _spaced(d, xy, text: str, size: int, fill, spacing: int = 6) -> None:
    x, y = xy
    font = _font(size)
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill)
        x += d.textlength(ch, font=font) + spacing


def _fit(d, text: str, size: int, width: int, bold: bool = True) -> tuple[str, int]:
    text = _clean(text) or "кто-то"
    while size > 20 and d.textlength(text, font=_font(size, bold)) > width:
        size -= 2
    while d.textlength(text, font=_font(size, bold)) > width and len(text) > 3:
        text = text[:-2] + "…"
    return text, size


def _avatar(img, center: tuple[int, int], r: int, photo: bytes | None, name: str, uid: int) -> None:
    """Аватарка в спасательном круге: красно-белое кольцо, внутри фото или первая буква имени."""
    cx, cy = center
    ring = Image.new("RGBA", (r * 2, r * 2), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    for i in range(8):
        rd.pieslice((0, 0, r * 2 - 1, r * 2 - 1), i * 45 - 22.5, i * 45 + 22.5,
                    fill=RED + (255,) if i % 2 == 0 else (255, 255, 255, 255))
    inner = int(r * 0.7)
    face = None
    if photo:
        try:
            face = Image.open(io.BytesIO(photo)).convert("RGB")
            s = min(face.size)
            face = face.crop(((face.width - s) // 2, (face.height - s) // 2,
                              (face.width + s) // 2, (face.height + s) // 2)).resize((inner * 2, inner * 2), Image.LANCZOS)
        except Exception:
            face = None
    if face is None:
        face = Image.new("RGB", (inner * 2, inner * 2), INITIAL_COLORS[abs(uid) % len(INITIAL_COLORS)])
        fd = ImageDraw.Draw(face)
        letter = (_clean(name)[:1] or "?").upper()
        font = _font(int(inner * 1.1))
        tw = fd.textlength(letter, font=font)
        fd.text((inner - tw / 2, inner - inner * 0.75), letter, font=font, fill=(255, 255, 255))
    mask = Image.new("L", (inner * 2, inner * 2), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, inner * 2 - 1, inner * 2 - 1), fill=255)
    ring.paste(face, (r - inner, r - inner), mask)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((cx - r + 4, cy - r + 8, cx + r + 4, cy + r + 8), fill=(0, 0, 0, 70))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(8)))
    img.alpha_composite(ring, (cx - r, cy - r))


def _panel(img, box, radius: int = 28, alpha: int = 26, outline: tuple | None = None) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius, fill=(255, 255, 255, alpha),
                                            outline=outline or (255, 255, 255, 48), width=2)
    img.alpha_composite(layer)


def _header(img, d, kicker: str, title: str, sub: str, ship: bool) -> None:
    anchor = _icon("anchor", 34)
    if anchor:
        img.alpha_composite(anchor, (PAD, 74))
    _spaced(d, (PAD + 46, 76), kicker, 28, TEAL)
    d.text((PAD, 112), title, font=_font(86), fill=(255, 255, 255))
    sub, size = _fit(d, sub, 34, W - PAD * 2 - (170 if ship else 0), bold=False)
    d.text((PAD, 214), sub, font=_font(size, False), fill=(224, 242, 254))
    if ship:
        icon = _icon("ship", 140)
        if icon:
            img.alpha_composite(icon, (W - PAD - icon.width, 82))


def _footer(img, d, data: DayData, bot_photo: bytes | None) -> None:
    y = H - 82
    _avatar(img, (PAD + 26, y + 18), 26, bot_photo, data.bot_name, 0)
    name, size = _fit(d, data.bot_name, 30, 400)
    d.text((PAD + 66, y + 2), name, font=_font(size), fill=(255, 255, 255))
    if data.site:
        site = data.site.replace("https://", "").replace("http://", "").rstrip("/")
        tw = d.textlength(site, font=_font(30))
        d.text((W - PAD - tw, y + 2), site, font=_font(30), fill=GOLD)


def _jpeg(img) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()


def logbook(data: DayData, avatars: dict[int, bytes | None], bot_photo: bytes | None = None) -> bytes | None:
    """Карточка 1: Бортовой журнал, номинации дня."""
    if Image is None:
        return None
    img = _background()
    d = ImageDraw.Draw(img)
    _header(img, d, "БОРТОВОЙ ЖУРНАЛ", "Итоги дня", f"{data.chat_title} · {data.date}", ship=True)
    y, row_h, gap = 292, 150, 20
    for nom in data.noms[:5]:
        _panel(img, (PAD, y, W - PAD, y + row_h))
        _avatar(img, (PAD + 92, y + row_h // 2), 58, avatars.get(nom.user_id), nom.name, nom.user_id)
        x = PAD + 180
        icon = _icon(nom.icon, 34)
        if icon:
            img.alpha_composite(icon, (x, y + 20))
        d.text((x + 44, y + 20), nom.label, font=_font(30), fill=TEAL)
        name, size = _fit(d, nom.name, 50, W - PAD - x - 30)
        d.text((x, y + 56), name, font=_font(size), fill=(255, 255, 255))
        sub, ssize = _fit(d, nom.sub, 29, W - PAD - x - 30, bold=False)
        d.text((x, y + 108), sub, font=_font(ssize, False), fill=MUTED)
        y += row_h + gap
    _footer(img, d, data, bot_photo)
    return _jpeg(img)


def crew(data: DayData, avatars: dict[int, bytes | None], bot_photo: bytes | None = None) -> bytes | None:
    """Карточка 2: Команда корабля, сколько написали, пик, топ-5 и человек дня."""
    if Image is None:
        return None
    img = _background()
    d = ImageDraw.Draw(img)
    _header(img, d, "КОМАНДА КОРАБЛЯ", "Топ дня", f"{data.chat_title} · {data.date}", ship=False)
    tiles = [(f"{data.total:,}".replace(",", " "), "сообщений"), (str(data.people), "человек"), (data.peak, "пик")]
    tw = (W - PAD * 2 - 2 * 24) // 3
    for i, (big, small) in enumerate(tiles):
        x0 = PAD + i * (tw + 24)
        _panel(img, (x0, 292, x0 + tw, 442), radius=26)
        bw = d.textlength(big, font=_font(64))
        d.text((x0 + tw / 2 - bw / 2, 310), big, font=_font(64), fill=(255, 255, 255))
        sw = d.textlength(small, font=_font(28, False))
        d.text((x0 + tw / 2 - sw / 2, 392), small, font=_font(28, False), fill=MUTED)
    trophy = _icon("trophy", 34)
    if trophy:
        img.alpha_composite(trophy, (PAD, 484))
    _spaced(d, (PAD + 46, 486), "ТОП ЭКИПАЖА", 28, TEAL, spacing=4)
    top = data.top[:5]
    most = max((c.msgs for c in top), default=1) or 1
    y = 552
    bar_x0, bar_x1 = 450, W - PAD - 110
    for c in top:
        _avatar(img, (PAD + 46, y + 44), 44, avatars.get(c.user_id), c.name, c.user_id)
        name, size = _fit(d, c.name, 38, bar_x0 - PAD - 120)
        d.text((PAD + 112, y + 22), name, font=_font(size), fill=(255, 255, 255))
        track = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(track).rounded_rectangle((bar_x0, y + 32, bar_x1, y + 58), 13, fill=(255, 255, 255, 34))
        img.alpha_composite(track)
        fill_w = max(26, int((bar_x1 - bar_x0) * c.msgs / most))
        grad = Image.new("RGBA", (fill_w, 26))
        gd = ImageDraw.Draw(grad)
        for gx in range(fill_w):
            t = gx / max(1, (bar_x1 - bar_x0))
            gd.line([(gx, 0), (gx, 26)], fill=(round(94 + (250 - 94) * t), round(234 + (204 - 234) * t),
                                                round(212 + (21 - 212) * t), 255))
        mask = Image.new("L", (fill_w, 26), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, fill_w - 1, 25), 13, fill=255)
        img.paste(grad, (bar_x0, y + 32), mask)
        num = str(c.msgs)
        nw = d.textlength(num, font=_font(38))
        d.text((W - PAD - nw, y + 22), num, font=_font(38), fill=(255, 255, 255))
        y += 104
    if data.star:
        y0 = max(y + 16, 1100)
        _panel(img, (PAD, y0, W - PAD, y0 + 88), radius=44, alpha=22, outline=GOLD + (200,))
        crown = _icon("crown", 38)
        if crown:
            img.alpha_composite(crown, (PAD + 30, y0 + 24))
        label = "Человек дня: "
        d.text((PAD + 80, y0 + 24), label, font=_font(32), fill=GOLD)
        lw = d.textlength(label, font=_font(32))
        rest, size = _fit(d, data.star, 32, W - PAD * 2 - 110 - int(lw))
        d.text((PAD + 80 + lw, y0 + 24), rest, font=_font(size), fill=(255, 255, 255))
    _footer(img, d, data, bot_photo)
    return _jpeg(img)
