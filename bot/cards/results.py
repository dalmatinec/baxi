"""Итоги дня двумя карточками: «Итоги дня» (номинации) и «Топ дня» (цифры и топ-5).

Дизайн общий для всех чатов, без привязки к теме: сверху название чата, без кораблей и пиратов.
У каждого чата свой цвет (STYLES): выбирается сам по номеру чата, владелец может поменять в админке.
Только рисование: на вход данные и аватарки (байты или None), на выход JPEG. Без Pillow функции вернут None."""

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
WHITE, MUTED = (255, 255, 255), (214, 222, 235)
INITIAL_COLORS = [(59, 130, 246), (234, 88, 12), (22, 163, 74), (219, 39, 119), (124, 58, 237), (13, 148, 136)]

# стили карточек: название, верх фона, низ фона, акцент (подписи, кольца), второй цвет полосок
STYLES = [
    ("Море", (31, 111, 139), (8, 30, 62), (103, 232, 249), (250, 204, 21)),
    ("Ночь", (76, 29, 149), (17, 9, 48), (196, 181, 253), (244, 114, 182)),
    ("Закат", (194, 65, 12), (69, 10, 50), (253, 186, 116), (250, 204, 21)),
    ("Изумруд", (6, 120, 95), (5, 35, 40), (110, 231, 183), (190, 242, 100)),
    ("Графит", (55, 65, 81), (12, 15, 22), (226, 232, 240), (250, 204, 21)),
    ("Вишня", (159, 18, 57), (36, 8, 24), (253, 164, 175), (251, 191, 36)),
]


def style_for(chat_id: int, chosen: int = -1) -> int:
    """Номер стиля: выбранный владельцем или свой у каждого чата по его номеру."""
    return chosen if 0 <= chosen < len(STYLES) else abs(chat_id) % len(STYLES)


@dataclass
class Nomination:
    icon: str          # имя файла в assets без .png
    label: str         # Болтун дня
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
    style: int = 0


@lru_cache(maxsize=32)
def _icon(name: str, size: int):
    path = ASSETS / f"{name}.png"
    if not path.exists():
        return None
    img = Image.open(path).convert("RGBA")
    k = size / max(img.size)
    return img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)


@lru_cache(maxsize=8)
def _background(style: int) -> "Image.Image":
    """Градиент цвета чата и пара мягких световых пятен. Кэшируется: фон рисуется один раз на стиль."""
    _, top, bottom, accent, second = STYLES[style]
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((-300, -340, 620, 420), fill=accent + (60,))
    g.ellipse((W - 380, H - 520, W + 260, H + 160), fill=second + (38,))
    img.paste(glow.filter(ImageFilter.GaussianBlur(110)), (0, 0), glow.filter(ImageFilter.GaussianBlur(110)))
    dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    for i in range(28):   # мелкие точки для фактуры, всегда в одних местах
        x, y = (i * 389) % W, (i * 613 + 140) % (H - 200)
        r = 2 + i % 3
        dd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 26))
    img.paste(dots, (0, 0), dots)
    return img.convert("RGBA")


def _spaced(d, xy, text: str, size: int, fill, spacing: int = 5, width: int = W) -> None:
    x, y = xy
    font = _font(size)
    for ch in text:
        step = d.textlength(ch, font=font) + spacing
        if x + step > width:
            d.text((x, y), "…", font=font, fill=fill)
            return
        d.text((x, y), ch, font=font, fill=fill)
        x += step


def _fit(d, text: str, size: int, width: int, bold: bool = True) -> tuple[str, int]:
    text = _clean(text) or "кто-то"
    while size > 20 and d.textlength(text, font=_font(size, bold)) > width:
        size -= 2
    while d.textlength(text, font=_font(size, bold)) > width and len(text) > 3:
        text = text[:-2] + "…"
    return text, size


def _avatar(img, center: tuple[int, int], r: int, photo: bytes | None, name: str, uid: int, ring) -> None:
    """Круглая аватарка с цветным кольцом. Нет фото: цветной круг с первой буквой имени."""
    cx, cy = center
    inner = int(r * 0.86)
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
        font = _font(int(inner * 1.05))
        tw = fd.textlength(letter, font=font)
        fd.text((inner - tw / 2, inner - inner * 0.72), letter, font=font, fill=WHITE)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((cx - r + 3, cy - r + 7, cx + r + 3, cy + r + 7), fill=(0, 0, 0, 80))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(8)))
    ImageDraw.Draw(img).ellipse((cx - r, cy - r, cx + r, cy + r), fill=ring + (255,))
    mask = Image.new("L", (inner * 2, inner * 2), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, inner * 2 - 1, inner * 2 - 1), fill=255)
    img.paste(face, (cx - inner, cy - inner), mask)


def _panel(img, box, radius: int = 28, alpha: int = 24, outline: tuple | None = None) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius, fill=(255, 255, 255, alpha),
                                            outline=outline or (255, 255, 255, 44), width=2)
    img.alpha_composite(layer)


def _header(img, d, data: DayData, title: str, bot_photo: bytes | None) -> None:
    """Сверху название чата мелко, крупно заголовок, под ним дата. Справа аватарка бота."""
    accent = STYLES[data.style][3]
    _spaced(d, (PAD, 78), (_clean(data.chat_title) or "наш чат").upper(), 28, accent, width=W - PAD - 190)
    d.text((PAD, 114), title, font=_font(86), fill=WHITE)
    d.text((PAD, 216), data.date, font=_font(34, False), fill=MUTED)
    _avatar(img, (W - PAD - 70, 160), 70, bot_photo, data.bot_name, 0, accent)


def _footer(img, d, data: DayData) -> None:
    y = H - 84
    name, size = _fit(d, data.bot_name, 30, 520)
    d.text((PAD, y), name, font=_font(size), fill=WHITE)
    if data.site:
        site = data.site.replace("https://", "").replace("http://", "").rstrip("/")
        tw = d.textlength(site, font=_font(30))
        d.text((W - PAD - tw, y), site, font=_font(30), fill=STYLES[data.style][4])


def _jpeg(img) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()


def logbook(data: DayData, avatars: dict[int, bytes | None], bot_photo: bytes | None = None) -> bytes | None:
    """Карточка 1: Итоги дня, до 5 номинаций."""
    if Image is None:
        return None
    accent = STYLES[data.style][3]
    img = _background(data.style).copy()
    d = ImageDraw.Draw(img)
    _header(img, d, data, "Итоги дня", bot_photo)
    noms = data.noms[:5]
    row_h, gap = 150, 22
    y = 300
    for nom in noms:
        _panel(img, (PAD, y, W - PAD, y + row_h))
        _avatar(img, (PAD + 90, y + row_h // 2), 56, avatars.get(nom.user_id), nom.name, nom.user_id, accent)
        x = PAD + 176
        icon = _icon(nom.icon, 34)
        if icon:
            img.alpha_composite(icon, (x, y + 20))
        d.text((x + 46, y + 20), nom.label, font=_font(30), fill=accent)
        name, size = _fit(d, nom.name, 50, W - PAD - x - 30)
        d.text((x, y + 56), name, font=_font(size), fill=WHITE)
        sub, ssize = _fit(d, nom.sub, 29, W - PAD - x - 30, bold=False)
        d.text((x, y + 110), sub, font=_font(ssize, False), fill=MUTED)
        y += row_h + gap
    _footer(img, d, data)
    return _jpeg(img)


def crew(data: DayData, avatars: dict[int, bytes | None], bot_photo: bytes | None = None) -> bytes | None:
    """Карточка 2: Топ дня, сколько написали, сколько людей, час пик, топ-5 и человек дня."""
    if Image is None:
        return None
    _, _, _, accent, second = STYLES[data.style]
    img = _background(data.style).copy()
    d = ImageDraw.Draw(img)
    _header(img, d, data, "Топ дня", bot_photo)
    tiles = [(f"{data.total:,}".replace(",", " "), "сообщений"), (str(data.people), "человек"), (data.peak, "час пик")]
    tw = (W - PAD * 2 - 2 * 24) // 3
    for i, (big, small) in enumerate(tiles):
        x0 = PAD + i * (tw + 24)
        _panel(img, (x0, 300, x0 + tw, 450), radius=26)
        bw = d.textlength(big, font=_font(64))
        d.text((x0 + tw / 2 - bw / 2, 318), big, font=_font(64), fill=WHITE)
        sw = d.textlength(small, font=_font(28, False))
        d.text((x0 + tw / 2 - sw / 2, 400), small, font=_font(28, False), fill=MUTED)
    trophy = _icon("trophy", 34)
    if trophy:
        img.alpha_composite(trophy, (PAD, 494))
    _spaced(d, (PAD + 46, 496), "САМЫЕ АКТИВНЫЕ", 28, accent, spacing=4)
    top = data.top[:5]
    most = max((c.msgs for c in top), default=1) or 1
    y = 560
    bar_x0, bar_x1 = 450, W - PAD - 110
    for c in top:
        _avatar(img, (PAD + 44, y + 44), 42, avatars.get(c.user_id), c.name, c.user_id, accent)
        name, size = _fit(d, c.name, 38, bar_x0 - PAD - 120)
        d.text((PAD + 108, y + 22), name, font=_font(size), fill=WHITE)
        track = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(track).rounded_rectangle((bar_x0, y + 32, bar_x1, y + 58), 13, fill=(255, 255, 255, 34))
        img.alpha_composite(track)
        fill_w = max(26, int((bar_x1 - bar_x0) * c.msgs / most))
        grad = Image.new("RGBA", (fill_w, 26))
        gd = ImageDraw.Draw(grad)
        for gx in range(fill_w):
            t = gx / max(1, (bar_x1 - bar_x0))
            gd.line([(gx, 0), (gx, 26)], fill=tuple(round(accent[k] + (second[k] - accent[k]) * t) for k in range(3)))
        mask = Image.new("L", (fill_w, 26), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, fill_w - 1, 25), 13, fill=255)
        img.paste(grad, (bar_x0, y + 32), mask)
        num = str(c.msgs)
        nw = d.textlength(num, font=_font(38))
        d.text((W - PAD - nw, y + 22), num, font=_font(38), fill=WHITE)
        y += 104
    if data.star:
        y0 = max(y + 16, 1108)
        _panel(img, (PAD, y0, W - PAD, y0 + 88), radius=44, alpha=20, outline=second + (210,))
        crown = _icon("crown", 38)
        if crown:
            img.alpha_composite(crown, (PAD + 30, y0 + 24))
        label = "Человек дня: "
        d.text((PAD + 80, y0 + 24), label, font=_font(32), fill=second)
        lw = d.textlength(label, font=_font(32))
        rest, size = _fit(d, data.star, 32, W - PAD * 2 - 110 - int(lw))
        d.text((PAD + 80 + lw, y0 + 24), rest, font=_font(size), fill=WHITE)
    _footer(img, d, data)
    return _jpeg(img)

