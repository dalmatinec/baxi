"""Тексты бота в чатах. Их меняют двое:
  * владелец бота для всех чатов: /admin → Настройки → Тексты бота (хранится в kv под ключом текста);
  * админ чата для своего чата: ⚙️ Мои чаты → чат → ✉️ Тексты (таблица chat_texts).
Порядок: свой текст чата → текст владельца → стандартный.

Каждый текст: название, текст по умолчанию и подстановки в фигурных скобках. Свой вариант хранится HTML-ом
(с премиум-эмодзи и жирным, как прислали). У текста чата ещё может быть картинка и кнопки-ссылки.
Обычные эмодзи в тексте сами заменяются на премиум из эмодзи-пака (Настройки → Эмодзи)."""

import re
from dataclasses import dataclass, field

# ключ → (группа, название, текст по умолчанию, {подстановка: что это, пример})
TEXTS: dict[str, tuple[str, str, str, dict[str, tuple[str, str]]]] = {
    "tpl_rep_plus": ("Репутация", "⭐ Репутация повышена",
                     "⭐ Репутация пользователя {user} повышена.\n\nИзменение: +{amount}\n"
                     "Текущая репутация: {reputation}",
                     {"user": ("кто получил", "<b>Олег</b>"), "amount": ("на сколько", "1"),
                      "reputation": ("сколько стало", "48"), "от": ("кто дал", "Аня"), "место": ("место в чате", "3")}),
    "tpl_rep_minus": ("Репутация", "⭐ Репутация понижена",
                      "⭐ Репутация пользователя {user} понижена.\n\nИзменение: -{amount}\n"
                      "Текущая репутация: {reputation}",
                      {"user": ("кто получил", "<b>Олег</b>"), "amount": ("на сколько", "1"),
                       "reputation": ("сколько стало", "12"), "от": ("кто дал", "Аня"), "место": ("место в чате", "9")}),
    "eco_gift": ("Монеты", "💸 Перевод монет",
                 "💸 {от} передал {кому} <b>{сколько} 🪙</b>",
                 {"от": ("кто отдал", "Аня"), "кому": ("кто получил", "Олег"), "сколько": ("сколько", "100")}),
    "eco_bonus": ("Монеты", "🎁 Бонус дня",
                  "🎁 {кто} забрал бонус <b>+{сколько} 🪙</b>\n🔥 Серия: {серия} дн. Завтра будет {завтра} 🪙, "
                  "если не пропустишь.",
                  {"кто": ("кто забрал", "Аня"), "сколько": ("сколько дали", "70"), "серия": ("дней подряд", "3"),
                   "завтра": ("сколько дадут завтра", "80")}),
    "eco_topup": ("Монеты", "💰 Пополнение",
                  "💰 {кто} пополнил кошелёк на <b>{сколько} 🪙</b>",
                  {"кто": ("кто пополнил", "Аня"), "сколько": ("сколько монет", "3500")}),
    "eco_level": ("Ранги", "🆙 Новый ранг в чате",
                  "🎉 {кто} теперь <b>{уровень} ранг</b> в этом чате · {звание}! Держи {монеты} 🪙",
                  {"кто": ("кто вырос", "Аня"), "уровень": ("номер ранга", "5"), "звание": ("звание", "Болтун"),
                   "монеты": ("награда", "50")}),
    "eco_level_global": ("Ранги", "🌍 Новый общий уровень (в личку)",
                         "🌍 {кто}, твой общий уровень теперь <b>{уровень}</b> · {звание}! +{монеты} 🪙\n"
                         "🎖 Плюшки: {плюшки}",
                         {"кто": ("кто вырос", "Аня"), "уровень": ("номер уровня", "8"),
                          "звание": ("звание", "Душа компании"), "монеты": ("награда", "160"),
                          "плюшки": ("плюшки ранга", "+1 🪙 за сообщение, бонус дня +20%, корм -10%")}),
    "eco_weekly": ("Монеты", "🏅 Самые активные недели",
                   "🏅 <b>Самые активные за неделю</b>\n\n{список}\n\nПишите в чат: на следующей неделе приз может "
                   "быть вашим 😉",
                   {"список": ("места, имена и призы", "🥇 Аня · 340 сообщ. · +500 🪙\n🥈 Олег · 210 сообщ. · +300 🪙")}),
    "eco_dice_call": ("Кости", "🎲 Вызов в кости",
                      "🎲 {от} вызывает {кому} в кости на <b>{ставка} 🪙</b>!\n\n{кому}, принимаешь? "
                      "У кого больше, тот забирает банк.",
                      {"от": ("кто вызвал", "Аня"), "кому": ("кого вызвали", "Олег"), "ставка": ("ставка", "100")}),
    "eco_dice_go": ("Кости", "✅ Игра принята",
                    "🎲 Игра принята! Банк <b>{банк} 🪙</b>\n\n{первый} кидает первым: отправь в чат кубик 🎲, "
                    "потом {второй}. Чужие кубики не считаются.",
                    {"банк": ("сколько на кону", "200"), "первый": ("кто вызвал", "Аня"),
                     "второй": ("кого вызвали", "Олег")}),
    "eco_dice_win": ("Кости", "🏆 Победа в костях",
                     "🏆 {победитель} забирает <b>{банк} 🪙</b>!\n{первый} {очки1} : {очки2} {второй}",
                     {"победитель": ("кто выиграл", "Олег"), "банк": ("выигрыш", "200"),
                      "первый": ("кто вызвал", "Аня"), "очки1": ("его кубик", "3"),
                      "второй": ("кого вызвали", "Олег"), "очки2": ("его кубик", "5")}),
    "eco_new_pet": ("Питомцы", "🐣 Новый питомец",
                    "{эмодзи} {кто} завёл питомца: <b>{вид}</b>! Как назовёшь? Напиши кличку ✍️",
                    {"кто": ("хозяин", "Аня"), "вид": ("какой питомец", "Кошка"), "эмодзи": ("эмодзи питомца", "🐱")}),
    "eco_feed": ("Питомцы", "🍖 Покормили питомца",
                 "{еда} {кто} покормил {питомец} ({корм}, {цена} 🪙). Сытость {сытость}%",
                 {"кто": ("кто кормил", "Олег"), "питомец": ("кого (кличка, у чужого с хозяином)", "<b>Пушка</b>"),
                  "корм": ("чем", "Лосось"), "еда": ("эмодзи корма", "🍣"), "цена": ("цена", "30"),
                  "сытость": ("сытость после", "85")}),
    "eco_hungry": ("Питомцы", "😿 Питомец проголодался",
                   "🍽 {питомец} у {хозяин} проголодался! Покормите: {корм}",
                   {"питомец": ("эмодзи и кличка", "🐱 <b>Пушок</b>"), "хозяин": ("хозяин", "Аня"),
                    "корм": ("его еда", "Рыбка 🐟")}),

    # ---------- профиль ----------
    "profile": ("Профиль", "👤 Профиль участника",
                "👤 <b>ПРОФИЛЬ УЧАСТНИКА</b>\n\nИмя: {mention}\n{name}\nUsername:\n{username}\nID:{user_id}\n"
                "Статус: {status}\n━━━━━━━━━━━━━━\n📊 <b>АКТИВНОСТЬ</b>\n\nДата вступления:\n{join_date}\n"
                "Всего сообщений:\n{messages}\nСообщений за 24 часа:\n{messages_24h}\nПоследняя активность:\n"
                "{last_active}\n━━━━━━━━━━━━━━\n⭐ <b>ПОКАЗАТЕЛИ</b>\n\nРепутация:\n{reputation}\nРанг:\n{rank}\n"
                "Достижения:\n{achievements}\nПредупреждения:\n{warnings}\n━━━━━━━━━━━━━━\n💰 <b>ФИНАНСЫ</b>\n\n"
                "Баланс:\n{balance}\nЗадолженность:\n{debt}",
                {"mention": ("имя ссылкой", "<a href='tg://user?id=1'>Олег</a>"), "name": ("полное имя", "Олег Петров"),
                 "username": ("юзернейм", "@oleg"), "user_id": ("ID", "123456789"), "status": ("роль в чате", "Участник"),
                 "join_date": ("с какого числа в чате", "01.05.2026"), "messages": ("всего сообщений", "1 240"),
                 "messages_24h": ("сообщений за сутки", "37"), "last_active": ("последняя активность", "сегодня в 18:30"),
                 "reputation": ("репутация", "15"), "rank": ("ранг", "12 · Знаток"), "achievements": ("достижения", "пока нет"),
                 "warnings": ("предупреждения", "1/3"), "balance": ("монеты", "3 500 🪙"), "debt": ("задолженность", "нет")}),

    # ---------- модерация (эти тексты присылает бот-модератор) ----------
    "mod_ban": ("Модерация", "🚫 Блокировка",
                "🚫 Пользователь {user} заблокирован.\n\nПричина: {reason}\nСрок: {duration}\nМодератор: {admin}",
                {"user": ("кого", "<b>Олег</b>"), "reason": ("причина", "спам"), "duration": ("срок", "навсегда"),
                 "admin": ("кто наказал", "Аня")}),
    "mod_unban": ("Модерация", "🔓 Разблокировка",
                  "🔓 Пользователь {user} разблокирован.\n\nМодератор: {admin}",
                  {"user": ("кого", "<b>Олег</b>"), "admin": ("кто снял", "Аня")}),
    "mod_mute": ("Модерация", "🔇 Ограничение сообщений",
                 "🔇 Пользователю {user} выдано ограничение сообщений.\n\nСрок: {duration}\nПричина: {reason}\n"
                 "Модератор: {admin}",
                 {"user": ("кому", "<b>Олег</b>"), "duration": ("срок", "1 час"), "reason": ("причина", "флуд"),
                  "admin": ("кто наказал", "Аня")}),
    "mod_unmute": ("Модерация", "🔊 Снятие ограничения",
                   "🔊 Ограничение пользователя {user} снято.\n\nМодератор: {admin}",
                   {"user": ("с кого", "<b>Олег</b>"), "admin": ("кто снял", "Аня")}),
    "mod_warn": ("Модерация", "⚠️ Предупреждение",
                 "⚠️ Пользователь {user} получил предупреждение.\n\nПричина: {reason}\n"
                 "Всего предупреждений: {count}\nМодератор: {admin}",
                 {"user": ("кому", "<b>Олег</b>"), "reason": ("причина", "мат"), "count": ("сколько стало", "2/3"),
                  "admin": ("кто выдал", "Аня")}),
    "mod_unwarn": ("Модерация", "✅ Снятие предупреждения",
                   "✅ Предупреждение пользователя {user} снято.\n\nОсталось предупреждений: {count}",
                   {"user": ("с кого", "<b>Олег</b>"), "count": ("сколько осталось", "1/3")}),

    # ---------- задолженность ----------
    "debt": ("Задолженность", "💳 Задолженность",
             "За пользователем {user} числится задолженность.\n\nДата: {date}\nСпонсор: {sponsor}\nПриз: {prize}",
             {"user": ("кто должен получить", "<b>Олег</b>"), "date": ("дата и время", "21.11.2026 21:05"),
              "sponsor": ("спонсор", "Аня"), "prize": ("приз", "500 🪙")}),

    # ---------- рулетка ----------
    "game_list": ("Рулетка", "📋 Список игры",
                  "🎰 <b>{game}</b>{fk}\n━━━━━━━━━━━━━━\n{list}\n━━━━━━━━━━━━━━\nИгроков: {count}\n{how}",
                  {"game": ("название игры", "Рулетка"), "fk": ("строка ФК", " · ФК 30"),
                   "list": ("сам список", "1. Олег @oleg\n2. Аня @anya"), "count": ("сколько записалось", "2"),
                   "how": ("как записаться", "Записаться: кнопка ниже, @ или свой юзернейм")}),
    "game_closed": ("Рулетка", "🔒 Список закрыт",
                    "🔒 Список закрыт.\n\nКоличество игроков: {count}\nВсем удачи! 🍀",
                    {"count": ("сколько игроков", "36")}),
    "game_random": ("Рулетка", "🎲 Рандом",
                    "🎲 Рандом от {from} до {to}\n\nВыпало число: <b>{number}</b>",
                    {"from": ("от", "1"), "to": ("до", "36"), "number": ("выпавшее число", "17")}),
}


def groups() -> list[str]:
    seen = []
    for group, *_ in TEXTS.values():
        if group not in seen:
            seen.append(group)
    return seen


def fill(template: str, values: dict[str, object]) -> str:
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def sample(key: str, template: str) -> str:
    """Как текст будет выглядеть с примерами вместо подстановок."""
    return fill(template, {k: v[1] for k, v in TEXTS[key][3].items()})


SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_texts (
    chat_id  INTEGER NOT NULL,
    key      TEXT    NOT NULL,
    html     TEXT    NOT NULL DEFAULT '',   -- пусто: текст владельца или стандартный
    photo    TEXT    NOT NULL DEFAULT '',   -- file_id картинки
    buttons  TEXT    NOT NULL DEFAULT '',   -- строки «Текст - ссылка», в строке через |
    PRIMARY KEY (chat_id, key)
);
"""
MAX_HTML = 3000
MAX_CAPTION = 1024


async def init() -> None:
    from bot import db
    await db.conn().executescript(SCHEMA)
    await db.conn().commit()


@dataclass
class Msg:
    html: str
    photo: str = ""
    buttons: list[list[tuple[str, str]]] = field(default_factory=list)


_BUTTON = re.compile(r"^\s*(.+?)\s+[-–—]\s+((?:https?://|tg://)\S+)\s*$")


def parse_buttons(raw: str) -> tuple[list[list[tuple[str, str]]], list[str]]:
    """«Текст - ссылка», несколько в строке через |. Возвращает (кнопки, строки с ошибками)."""
    rows, bad = [], []
    for line in (raw or "").splitlines():
        if not line.strip():
            continue
        row = []
        for part in line.split("|"):
            m = _BUTTON.match(part)
            if m:
                row.append((m.group(1)[:64], m.group(2)[:512]))
            elif part.strip():
                bad.append(part.strip())
        if row:
            rows.append(row[:4])
    return rows[:8], bad


def buttons_text(rows: list[list[tuple[str, str]]]) -> str:
    return "\n".join(" | ".join(f"{t} - {u}" for t, u in row) for row in rows)


async def chat_override(chat_id: int, key: str) -> dict | None:
    from bot import db
    async with db.conn().execute("SELECT html, photo, buttons FROM chat_texts WHERE chat_id = ? AND key = ?",
                                 (chat_id, key)) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def set_chat_text(chat_id: int, key: str, **fields) -> None:
    from bot import db
    if key not in TEXTS or set(fields) - {"html", "photo", "buttons"}:
        raise ValueError(key)
    await db.conn().execute("INSERT OR IGNORE INTO chat_texts (chat_id, key) VALUES (?, ?)", (chat_id, key))
    sets = ", ".join(f"{k} = ?" for k in fields)
    await db.conn().execute(f"UPDATE chat_texts SET {sets} WHERE chat_id = ? AND key = ?",
                            (*fields.values(), chat_id, key))
    await db.conn().execute("DELETE FROM chat_texts WHERE html = '' AND photo = '' AND buttons = ''")
    await db.conn().commit()


async def reset_chat_text(chat_id: int, key: str) -> None:
    from bot import db
    await db.conn().execute("DELETE FROM chat_texts WHERE chat_id = ? AND key = ?", (chat_id, key))
    await db.conn().commit()


async def custom_keys(chat_id: int) -> set[str]:
    from bot import db
    async with db.conn().execute("SELECT key FROM chat_texts WHERE chat_id = ?", (chat_id,)) as cur:
        return {r[0] for r in await cur.fetchall()}


async def template(key: str, chat_id: int | None = None) -> Msg:
    """Шаблон без подстановок: свой текст чата → текст владельца → стандартный, плюс картинка и кнопки чата."""
    from bot import db
    own = await chat_override(chat_id, key) if chat_id else None
    html = (own or {}).get("html") or await db.kv_get(key) or TEXTS[key][2]
    buttons, _ = parse_buttons((own or {}).get("buttons", ""))
    return Msg(html=html, photo=(own or {}).get("photo", ""), buttons=buttons)


async def render(key: str, chat_id: int | None = None, **values) -> str:
    """Текст с подставленными значениями (без картинки и кнопок)."""
    return fill((await template(key, chat_id)).html, values)


async def message(key: str, chat_id: int | None = None, **values) -> Msg:
    t = await template(key, chat_id)
    return Msg(html=fill(t.html, values), photo=t.photo,
               buttons=[[(fill(text, values), url) for text, url in row] for row in t.buttons])


def markup(msg: Msg, extra=None):
    """Кнопки текста (ссылки) и, если есть, служебные кнопки бота снизу."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    rows = [[InlineKeyboardButton(text=t, url=u) for t, u in row] for row in msg.buttons]
    if extra is not None:
        rows += list(extra.inline_keyboard)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send(bot, chat_id: int, key: str, *, reply_to=None, thread=None, extra=None, **values):
    """Отправить текст чата целиком: картинка (если задана), текст, кнопки. Возвращает сообщение."""
    from bot.services.out import say, say_photo
    msg = await message(key, chat_id, **values)
    kb = markup(msg, extra)
    if msg.photo:
        sent = await say_photo(bot, chat_id, msg.photo, msg.html if len(msg.html) <= MAX_CAPTION else "",
                               reply_to=reply_to, thread=thread, markup=kb if len(msg.html) <= MAX_CAPTION else None)
        if len(msg.html) <= MAX_CAPTION:
            return sent
    return await say(bot, chat_id, msg.html, reply_to=reply_to, thread=thread, markup=kb)
