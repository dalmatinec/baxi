"""Картинки экономики. Рисуются кодом через Pillow (бесплатно, без нейросети), морской стиль.

Если Pillow не установлен, функции возвращают None, и бот отвечает текстом."""

import io
import math
from functools import lru_cache
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:  # без Pillow просто нет картинок
    Image = None

from bot.economy import catalog

ASSETS = Path(__file__).parent / "assets"
W, H = 1000, 560
SKY, SEA, DEEP = (125, 211, 252), (14, 116, 178), (8, 47, 89)


@lru_cache(maxsize=8)
def _font(size: int, bold: bool = True):
    return ImageFont.truetype(str(ASSETS / ("font-bold.otf" if bold else "font.otf")), size)


@lru_cache(maxsize=32)
def _icon(name: str, size: int):
    path = ASSETS / f"{name}.png"
    if not path.exists():
        return None
    img = Image.open(path).convert("RGBA")
    scale = size / max(img.size)
    return img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _sea_background() -> "Image.Image":
    """Небо сверху, море снизу, солнце и несколько волн."""
    img = Image.new("RGB", (W, H))
    px = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        a, b = (SKY, SEA) if t < 0.6 else (SEA, DEEP)
        k = t / 0.6 if t < 0.6 else (t - 0.6) / 0.4
        px.line([(0, y), (W, y)], fill=tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3)))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((W - 230, -150, W + 30, 110), fill=(255, 250, 225, 170))
    glow = glow.filter(ImageFilter.GaussianBlur(40))
    img.paste(glow, (0, 0), glow)
    sun = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sun).ellipse((W - 150, -70, W - 10, 70), fill=(255, 251, 235, 255))
    sun = sun.filter(ImageFilter.GaussianBlur(3))
    img.paste(sun, (0, 0), sun)
    clouds = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(clouds)
    for cx0, cy0, k in ((560, 40, 1.0), (380, 110, 0.7)):
        for dx, dy, rr in ((0, 10, 26), (28, 0, 34), (62, 8, 28), (90, 16, 20)):
            rr = rr * k
            cd.ellipse((cx0 + dx * k - rr, cy0 + dy * k - rr, cx0 + dx * k + rr, cy0 + dy * k + rr),
                       fill=(255, 255, 255, 120))
    clouds = clouds.filter(ImageFilter.GaussianBlur(2))
    img.paste(clouds, (0, 0), clouds)
    waves = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wd = ImageDraw.Draw(waves)
    for n, (base, amp, alpha) in enumerate(((H - 150, 12, 40), (H - 100, 16, 55), (H - 50, 10, 70))):
        points = [(x, base + amp * math.sin(x / 70 + n * 1.7)) for x in range(0, W + 10, 10)]
        wd.polygon(points + [(W, H), (0, H)], fill=(255, 255, 255, alpha))
    img.paste(waves, (0, 0), waves)
    return img


def _text(d, xy, text, size, fill=(255, 255, 255), bold=True, shadow=True):
    font = _font(size, bold)
    if shadow:
        d.text((xy[0] + 2, xy[1] + 3), text, font=font, fill=(3, 37, 76, 120))
    d.text(xy, text, font=font, fill=fill)
    return d.textlength(text, font=font)


def _clean(text: str) -> str:
    """Шрифт карточки не умеет эмодзи и экзотические символы: убираем их, чтобы не было квадратиков."""
    return " ".join("".join(ch for ch in text or "" if ord(ch) < 0x2190 and ch.isprintable()).split())


def _fit(d, text: str, size: int, width: int, bold: bool = True) -> tuple[str, int]:
    """Уменьшает шрифт (и обрезает), чтобы длинная кличка влезла."""
    while size > 22 and d.textlength(text, font=_font(size, bold)) > width:
        size -= 2
    while d.textlength(text, font=_font(size, bold)) > width and len(text) > 3:
        text = text[:-2] + "…"
    return text, size


def pet_card(pet, satiety: float, level: int, power: int, owner: str, bot_name: str) -> bytes | None:
    """Карточка питомца: картинка, кличка, вид, уровень, сила, сытость, хозяин и кто кормил."""
    if Image is None:
        return None
    info = catalog.PETS[pet["species"]]
    accent = _hex(info["color"])
    img = _sea_background().convert("RGBA")
    d = ImageDraw.Draw(img)

    # круг с питомцем слева
    cx, cy, r = 250, 270, 170
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((cx - r + 8, cy - r + 16, cx + r + 8, cy + r + 16), fill=(3, 37, 76, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    img.alpha_composite(shadow)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 235), outline=accent + (255,), width=10)
    icon = _icon(pet["species"], 230)
    if icon:
        img.alpha_composite(icon, (cx - icon.width // 2, cy - icon.height // 2))
    if info["stars"]:  # редкий питомец за звёзды: золотая плашка
        d.rounded_rectangle((cx - 80, cy + r - 24, cx + 80, cy + r + 22), 22, fill=(250, 204, 21, 255))
        tw = d.textlength("РЕДКИЙ", font=_font(26))
        d.text((cx - tw / 2, cy + r - 17), "РЕДКИЙ", font=_font(26), fill=(113, 63, 18))

    # текст справа
    x, width = 470, W - 470 - 50
    name, size = _fit(d, _clean(pet["name"]) or info["name"], 64, width)
    _text(d, (x, 60), name, size)
    chip = f"{info['name']} · {level} ур."
    cw = d.textlength(chip, font=_font(28)) + 36
    d.rounded_rectangle((x, 150, x + cw, 196), 23, fill=accent + (255,))
    d.text((x + 18, 156), chip, font=_font(28), fill=(255, 255, 255))
    _text(d, (x + cw + 18, 156), f"Сила {power}", 30)

    # сытость
    _text(d, (x, 230), "Сытость", 26, bold=False)
    pct = max(0, min(100, int(satiety)))
    bar_color = (34, 197, 94) if pct >= 60 else (245, 158, 11) if pct >= catalog.PET_XP_HUNGRY else (239, 68, 68)
    d.rounded_rectangle((x, 268, x + width, 304), 18, fill=(255, 255, 255, 90))
    if pct:
        d.rounded_rectangle((x, 268, x + max(36, int(width * pct / 100)), 304), 18, fill=bar_color + (255,))
    pct_text = f"{pct}%"
    _text(d, (x + width - d.textlength(pct_text, font=_font(26)), 230), pct_text, 26)

    # еда
    food = info["food"]
    ficon = _icon(f"f_{pet['species']}", 44)
    if ficon:
        img.alpha_composite(ficon, (x, 330))
    food_text, fsize = _fit(d, f"Ест: {food[0]} · {food[2]} монет", 28, width - 56, bold=False)
    _text(d, (x + 56, 336), food_text, fsize, bold=False)

    owner_text, osize = _fit(d, f"Хозяин: {_clean(owner) or 'аноним'}", 28, width, bold=False)
    _text(d, (x, 392), owner_text, osize, bold=False)
    if pet["fed_by"]:
        fed_text, fsize = _fit(d, f"Кормил: {_clean(pet['fed_by'])}", 24, width, bold=False)
        _text(d, (x, 436), fed_text, fsize, fill=(224, 242, 254), bold=False)

    _text(d, (40, H - 52), _clean(bot_name), 26, fill=(224, 242, 254), shadow=False)
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()
