"""Логика экономики без Telegram: начисления за сообщения, бонус дня, покупки, питомцы, кости.
Обработчики команд лежат в bot/handlers/economy.py, картинки в bot/economy/cards.py."""

import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from bot import config
from bot.economy import catalog, store


def today() -> str:
    return datetime.now(config.TZ).strftime("%Y-%m-%d")


# ---------- опыт и монеты за сообщения ----------

async def on_message(chat_id: int, user_id: int, name: str, text: str) -> tuple[int, int] | None:
    """Начисляет опыт и монеты не чаще раза в 30 секунд. Если уровень вырос, возвращает (старый, новый)."""
    if len((text or "").strip()) < catalog.MIN_TEXT or text.startswith("/"):
        return None
    w = await store.wallet(chat_id, user_id, name)
    now = time.time()
    if now - w["last_award"] < catalog.AWARD_COOLDOWN:
        return None
    xp = w["xp"] + random.randint(*catalog.XP_PER_MSG)
    coins = w["coins"] + random.randint(*catalog.COINS_PER_MSG)
    level = catalog.level_for(xp)
    await store.update_wallet(chat_id, user_id, xp=xp, coins=coins, level=level, last_award=now)
    pet = await store.pet(chat_id, user_id)
    if pet and satiety(pet) >= catalog.PET_XP_HUNGRY:
        await store.update_pet(chat_id, user_id, xp=pet["xp"] + 1)  # сытый питомец растёт вместе с хозяином
    return (w["level"], level) if level > w["level"] else None


# ---------- бонус дня ----------

async def claim_bonus(chat_id: int, user_id: int, name: str) -> tuple[int, int] | None:
    """Бонус раз в день. Возвращает (сколько дали, серия дней) или None, если уже забирал."""
    w = await store.wallet(chat_id, user_id, name)
    day = today()
    if w["bonus_day"] == day:
        return None
    yesterday = (datetime.now(config.TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    streak = w["streak"] + 1 if w["bonus_day"] == yesterday else 1
    amount = min(catalog.BONUS_BASE + catalog.BONUS_STEP * (streak - 1), catalog.BONUS_MAX)
    await store.update_wallet(chat_id, user_id, coins=w["coins"] + amount, bonus_day=day, streak=streak)
    return amount, streak


# ---------- питомцы ----------

def satiety(pet) -> float:
    """Текущая сытость с учётом времени с последнего пересчёта."""
    hours = (time.time() - pet["fed_at"]) / 3600
    return max(0.0, pet["satiety"] - hours * catalog.PET_HUNGER_PER_HOUR)


def pet_level(pet) -> int:
    return catalog.pet_level_for(pet["xp"])


def pet_power(pet) -> int:
    return catalog.PETS[pet["species"]]["power"] + pet_level(pet)


async def buy_pet(chat_id: int, user_id: int, owner: str, species: str) -> str:
    """Покупка за монеты. Возвращает '' при успехе или причину отказа."""
    info = catalog.PETS.get(species)
    if not info:
        return "такого питомца нет"
    current = await store.pet(chat_id, user_id)
    if current and catalog.PET_ORDER.index(current["species"]) >= catalog.PET_ORDER.index(species):
        return "у тебя уже такой или круче"
    if not await store.spend(chat_id, user_id, info["price"]):
        return f"не хватает монет, нужно {info['price']} 🪙"
    await store.set_pet(chat_id, user_id, owner, species, info["name"])
    return ""


async def feed(chat_id: int, owner_id: int, feeder_id: int, feeder: str, kind: str = "food") -> dict:
    """Кормит питомца хозяина owner_id. Платит тот, кто нажал (можно кормить и чужого).
    Возвращает {'error': ...} или {'food': ..., 'satiety': ..., 'pet': ...}."""
    pet = await store.pet(chat_id, owner_id)
    if not pet:
        return {"error": "у тебя ещё нет питомца, загляни в магазин" if owner_id == feeder_id else "питомца уже нет"}
    food = next((f for f in catalog.foods(pet["species"]) if f["key"] == kind), None)
    if not food:
        return {"error": "такого корма нет"}
    now_sat = satiety(pet)
    if now_sat >= catalog.PET_FULL:
        return {"error": f"{pet['name']} сыт и отказывается есть 😼"}
    await store.wallet(chat_id, feeder_id, feeder)
    if not await store.spend(chat_id, feeder_id, food["price"]):
        return {"error": f"не хватает монет: {food['name']} стоит {food['price']} 🪙"}
    new_sat = min(100.0, now_sat + food["plus"])
    await store.update_pet(chat_id, owner_id, satiety=new_sat, fed_at=time.time(), xp=pet["xp"] + food["xp"],
                           fed_by=f"{feeder} · {food['name']} {food['emoji']}", warned=0)
    return {"food": food, "satiety": int(new_sat), "pet": await store.pet(chat_id, owner_id)}


def clean_pet_name(name: str) -> str:
    return " ".join((name or "").split())[:20]


async def rename_pet(chat_id: int, user_id: int, name: str) -> str:
    name = clean_pet_name(name)
    if not name or "http" in name.lower() or "@" in name:
        return "кличка до 20 символов, без ссылок и @"
    if not await store.pet(chat_id, user_id):
        return "у тебя ещё нет питомца"
    await store.update_pet(chat_id, user_id, name=name)
    return ""


async def hungry_pets(chat_id: int) -> list:
    """Питомцы, которые проголодались и о которых ещё не писали в чат."""
    return [p for p in await store.pets_in_chat(chat_id)
            if not p["warned"] and satiety(p) < catalog.PET_XP_HUNGRY]


async def gift(chat_id: int, from_id: int, from_name: str, to_id: int, to_name: str, amount: int) -> str:
    if from_id == to_id:
        return "себе переводить нельзя 🙃"
    if amount < catalog.GIFT_MIN:
        return f"минимум {catalog.GIFT_MIN} 🪙"
    await store.wallet(chat_id, from_id, from_name)
    if not await store.spend(chat_id, from_id, amount):
        return "не хватает монет"
    await store.add_coins(chat_id, to_id, amount, to_name)
    return ""


async def buy_look(chat_id: int, user_id: int) -> str:
    """Свой ник и премиум-эмодзи навсегда за монеты. Сам вид настраивается в личке бота."""
    from bot import db
    perks = await db.get_perks(user_id)
    if perks and perks["look_forever"]:
        return "у тебя уже есть свой ник навсегда, настроить его можно в личке бота"
    if not await store.spend(chat_id, user_id, catalog.NICK_PRICE):
        return f"нужно {catalog.NICK_PRICE} 🪙"
    await db.set_perks(user_id, look_forever=1)
    return ""


async def pet_top(chat_id: int, limit: int = 10) -> list:
    pets = await store.pets_in_chat(chat_id)
    return sorted(pets, key=pet_power, reverse=True)[:limit]


# ---------- кости: ставка ответом на сообщение ----------

@dataclass
class Duel:
    chat_id: int
    a: int
    a_name: str
    b: int
    b_name: str
    bet: int
    accepted: bool = False
    rolls: dict = field(default_factory=dict)     # кто сколько выбросил
    created: float = field(default_factory=time.time)


DUELS: dict[int, Duel] = {}       # одна игра в кости на чат
DUEL_TIMEOUT = 180


def active_duel(chat_id: int) -> Duel | None:
    """Игра в чате, если она ещё не протухла (протухшие разбирает refund_expired)."""
    d = DUELS.get(chat_id)
    return d if d and time.time() - d.created <= DUEL_TIMEOUT else None


async def start_duel(chat_id: int, a: int, a_name: str, b: int, b_name: str, bet: int) -> str:
    await refund_expired()
    if not catalog.DICE_MIN <= bet <= catalog.DICE_MAX:
        return f"ставка от {catalog.DICE_MIN} до {catalog.DICE_MAX} 🪙"
    if active_duel(chat_id):
        return "в чате уже идёт игра в кости, подождите"
    if a == b:
        return "с собой играть нельзя 🙃"
    w = await store.wallet(chat_id, a, a_name)
    if w["coins"] < bet:
        return f"у тебя только {w['coins']} 🪙"
    DUELS[chat_id] = Duel(chat_id, a, a_name, b, b_name, bet)
    return ""


async def accept_duel(chat_id: int, user_id: int) -> str:
    d = active_duel(chat_id)
    if not d or d.accepted:
        return "игра уже закончилась"
    if user_id != d.b:
        return "это не тебе вызов"
    await store.wallet(chat_id, d.b, d.b_name)
    if not await store.spend(chat_id, d.a, d.bet):
        DUELS.pop(chat_id, None)
        return "у вызвавшего уже не хватает монет"
    if not await store.spend(chat_id, d.b, d.bet):
        await store.add_coins(chat_id, d.a, d.bet)
        DUELS.pop(chat_id, None)
        return f"у тебя не хватает монет, нужно {d.bet} 🪙"
    d.accepted, d.created = True, time.time()
    return ""


async def roll(chat_id: int, user_id: int, value: int) -> tuple[str, Duel | None]:
    """Кубик от участника. Возвращает ('wait'|'tie'|'done'|'', дуэль). Чужие кубики игнорируются."""
    d = active_duel(chat_id)
    if not d or not d.accepted or user_id not in (d.a, d.b) or user_id in d.rolls:
        return "", None
    if user_id == d.b and d.a not in d.rolls:
        return "", None   # первым кидает тот, кто вызвал
    d.rolls[user_id] = value
    d.created = time.time()   # пока кидают, игра не протухает
    if len(d.rolls) < 2:
        return "wait", d
    if d.rolls[d.a] == d.rolls[d.b]:
        d.rolls.clear()
        return "tie", d
    winner = d.a if d.rolls[d.a] > d.rolls[d.b] else d.b
    await store.add_coins(chat_id, winner, d.bet * 2)
    DUELS.pop(chat_id, None)
    return "done", d


async def give_up(chat_id: int, user_id: int) -> tuple[str, Duel | None]:
    """Сдаться. До принятия: вызов просто отменяется. После: банк забирает соперник."""
    d = active_duel(chat_id)
    if not d or user_id not in (d.a, d.b):
        return "", None
    DUELS.pop(chat_id, None)
    if not d.accepted:
        return "cancel", d
    await store.add_coins(chat_id, d.b if user_id == d.a else d.a, d.bet * 2)
    return "lost", d


async def refund_expired() -> list[Duel]:
    """Возвращает ставки, если игру в кости бросили посередине."""
    gone = []
    for chat_id, d in list(DUELS.items()):
        if time.time() - d.created > DUEL_TIMEOUT:
            DUELS.pop(chat_id, None)
            if d.accepted:
                await store.add_coins(chat_id, d.a, d.bet)
                await store.add_coins(chat_id, d.b, d.bet)
            gone.append(d)
    return gone
