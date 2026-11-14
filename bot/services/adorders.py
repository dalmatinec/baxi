"""Заказы рекламы: оплата USDT в сети TON (toncenter) или TRON/TRC20 (TronGrid) с автопроверкой,
публикация по формату, закрепы с откреплением через сутки, рассылка в личку бота.

Как опознаётся платёж: у каждого заказа своя точная сумма (например 10.0037 USDT), годится любая из сетей.
Если в переводе TON есть комментарий AD<номер заказа>, заказ находится и по нему."""

import asyncio
import logging
import random
import re
import time

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from bot import config, db, notify
from bot.services.ads import send_ad
from bot.textutil import esc

log = logging.getLogger(__name__)

DEFAULT_PRODUCTS = [
    ("groups", "📢 Пост во все группы", 10, 1, 0),
    ("groups", "📢 Пост в группы 3 дня подряд", 25, 3, 1),
    ("pin_groups", "📌 Закреп в группах на сутки", 20, 1, 2),
    ("pin_channel", "📌 Закреп в канале на сутки", 15, 1, 3),
    ("dm", "✉️ Рассылка в личку бота", 15, 1, 4),
]
# не реклама, а оплата аренды и своего бота: продаются через те же заказы и ту же оплату USDT
SERVICE_PRODUCTS = [("rent", "📅 Аренда бота на 30 дней", 50, 30, 20), ("wl", "💼 Свой бот", 100, 1, 21)]
SERVICE_KINDS = {"rent", "wl"}
KIND_TEXT = {
    "rent": "бот в твоём чате на 30 дней, со своим характером и всеми фишками",
    "wl": "свой бот: исходный код, любые настройки, установка на твой сервер",
    "groups": "пост выходит во всех чатах сети, где включена реклама",
    "pin_groups": "пост выходит во всех чатах сети и висит в закрепе сутки",
    "pin_channel": "пост в канале с закрепом на сутки",
    "dm": "сообщение в личку всем, кто запускал бота",
    "both": "пост во все чаты и в личку бота",
}
PAY_HOURS = 24          # сколько ждать оплату после одобрения
DAY = 86400

_http: httpx.AsyncClient | None = None
_last_check = 0.0
_tasks: set[asyncio.Task] = set()


def spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def usdt(units: int) -> str:
    """Микро-USDT → строка без лишних нулей: 10003700 → '10.0037'."""
    return f"{units / 1_000_000:.6f}".rstrip("0").rstrip(".")


async def unique_amount(price: float) -> int:
    """Цена плюс копейки 0.0001-0.0099, которых нет у других неоплаченных заказов."""
    base = round(price * 1_000_000)
    for _ in range(200):
        amount = base + random.randint(1, 99) * 100
        if not await db.amount_taken(amount):
            return amount
    return base + random.randint(100, 9999)


def can_pay() -> bool:
    return bool(config.PAY_TON_ADDRESS or config.PAY_TRON_ADDRESS)


def pay_text(order) -> str:
    lines = [f"✅ <b>Заказ #{order['id']} одобрен!</b>\n",
             f"Оплати <b>ровно {usdt(order['amount'])} USDT</b> в одной из сетей:\n"]
    if config.PAY_TON_ADDRESS:
        lines.append(f"💎 <b>Сеть TON</b> (комиссия копейки):\n<code>{config.PAY_TON_ADDRESS}</code>\n"
                     f"комментарий, если кошелёк позволяет: <code>AD{order['id']}</code>\n")
    if config.PAY_TRON_ADDRESS:
        lines.append(f"🔺 <b>Сеть TRON (TRC20)</b>:\n<code>{config.PAY_TRON_ADDRESS}</code>\n")
    lines.append("⚠️ Отправляй USDT только в той сети, чей адрес выбрал, иначе деньги потеряются. "
                 "Сумма должна совпасть до последней цифры: по ней я узнаю твой платёж "
                 f"(с биржи учитывай её комиссию). Проверяю сам каждые полминуты, на оплату {PAY_HOURS} ч.")
    return "\n".join(lines)


def pay_kb(order) -> InlineKeyboardMarkup:
    copy = []
    if config.PAY_TON_ADDRESS:
        copy.append(InlineKeyboardButton(text="📋 Адрес TON", copy_text=CopyTextButton(text=config.PAY_TON_ADDRESS)))
    if config.PAY_TRON_ADDRESS:
        copy.append(InlineKeyboardButton(text="📋 Адрес TRC20",
                                         copy_text=CopyTextButton(text=config.PAY_TRON_ADDRESS)))
    return InlineKeyboardMarkup(inline_keyboard=[
        copy,
        [InlineKeyboardButton(text="📋 Сумма", copy_text=CopyTextButton(text=usdt(order["amount"])))],
        [InlineKeyboardButton(text="🔄 Я оплатил, проверить", callback_data=f"ord:chk:{order['id']}",
                              style="success")],
        [InlineKeyboardButton(text="🆘 Поддержка", callback_data="act:support:оплата рекламы")],
    ])


async def approve(bot: Bot, order_id: int) -> None:
    order = await db.get_order(order_id)
    if not order or order["status"] != "moderation":
        return
    await start_payment(bot, order_id)


async def start_payment(bot: Bot, order_id: int) -> None:
    """Выставить счёт: точная сумма и адреса. Без адресов: оплата через поддержку."""
    order = await db.get_order(order_id)
    if not can_pay():
        await db.update_order(order_id, status="awaiting", next_run=time.time() + PAY_HOURS * 3600)
        await _tell(bot, order["user_id"], f"✅ Заказ #{order_id} одобрен! Как оплатить, напишет поддержка.",
                    InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                        text="🆘 Написать в поддержку", callback_data="act:support:оплата рекламы",
                        style="primary")]]))
        return
    amount = await unique_amount(order["price"])
    await db.update_order(order_id, status="awaiting", amount=amount, next_run=time.time() + PAY_HOURS * 3600)
    order = await db.get_order(order_id)
    await _tell(bot, order["user_id"], pay_text(order), pay_kb(order))


async def _tell(bot: Bot, user_id: int, html: str, kb=None) -> None:
    try:
        await bot.send_message(user_id, html, parse_mode="HTML", reply_markup=kb)
    except Exception as exc:
        log.info("Не написал заказчику %s: %s", user_id, exc)


# ---------- проверка оплаты через toncenter ----------

def extract_comment(payload) -> str:
    """Комментарий из decoded_forward_payload: ищем любую строку по ключам comment/text."""
    if isinstance(payload, dict):
        for key in ("comment", "text"):
            if isinstance(payload.get(key), str):
                return payload[key]
        for value in payload.values():
            found = extract_comment(value)
            if found:
                return found
    if isinstance(payload, list):
        for value in payload:
            found = extract_comment(value)
            if found:
                return found
    return ""


def match_order(transfer: dict, awaiting: list) -> object | None:
    """Чей это платёж: по комментарию AD<номер> (сумма не меньше цены) или по точной сумме.
    transfer: {"tx", "amount" (микро-USDT), "time", "comment", "net"}."""
    amount, when = transfer["amount"], transfer["time"]
    m = re.search(r"AD\s*(\d+)", transfer.get("comment") or "", re.I)
    if m:
        for order in awaiting:
            if order["id"] == int(m.group(1)) and amount >= round(order["price"] * 1_000_000):
                return order
    for order in awaiting:
        if order["amount"] == amount and when >= order["created"] - 60:
            return order
    return None


async def fetch_ton(since: float) -> list[dict]:
    """Входящие USDT в сети TON через toncenter."""
    global _http
    if _http is None:
        headers = {"X-API-Key": config.TONCENTER_API_KEY} if config.TONCENTER_API_KEY else {}
        _http = httpx.AsyncClient(base_url=config.TONCENTER_URL, headers=headers, timeout=20)
    params = {"owner_address": config.PAY_TON_ADDRESS, "direction": "in", "jetton_master": config.USDT_MASTER,
              "start_utime": int(since), "limit": 100, "sort": "desc"}
    resp = await _http.get("/jetton/transfers", params=params)
    if resp.status_code != 200:
        log.warning("toncenter ответил %s: %s", resp.status_code, resp.text[:200])
        return []
    out = []
    for t in resp.json().get("jetton_transfers", []) or []:
        if t.get("transaction_aborted") or not t.get("transaction_hash"):
            continue
        try:
            amount = int(t.get("amount", 0))
        except (TypeError, ValueError):
            continue
        out.append({"tx": "ton:" + t["transaction_hash"], "amount": amount, "net": "TON",
                    "time": int(t.get("transaction_now") or 0),
                    "comment": extract_comment(t.get("decoded_forward_payload"))})
    return out


_tron: httpx.AsyncClient | None = None


async def fetch_tron(since: float) -> list[dict]:
    """Входящие USDT TRC20 через TronGrid (только подтверждённые)."""
    global _tron
    if _tron is None:
        headers = {"TRON-PRO-API-KEY": config.TRONGRID_API_KEY} if config.TRONGRID_API_KEY else {}
        _tron = httpx.AsyncClient(base_url=config.TRONGRID_URL, headers=headers, timeout=20)
    params = {"only_to": "true", "only_confirmed": "true", "contract_address": config.TRON_USDT_CONTRACT,
              "min_timestamp": int(since * 1000), "limit": 100, "order_by": "block_timestamp,desc"}
    resp = await _tron.get(f"/v1/accounts/{config.PAY_TRON_ADDRESS}/transactions/trc20", params=params)
    if resp.status_code != 200:
        log.warning("TronGrid ответил %s: %s", resp.status_code, resp.text[:200])
        return []
    out = []
    for t in resp.json().get("data", []) or []:
        if t.get("to") != config.PAY_TRON_ADDRESS or not t.get("transaction_id"):
            continue
        try:
            amount = int(t.get("value", 0))
        except (TypeError, ValueError):
            continue
        out.append({"tx": "tron:" + t["transaction_id"], "amount": amount, "net": "TRC20",
                    "time": int(t.get("block_timestamp", 0)) // 1000, "comment": ""})
    return out


async def check_payments(bot: Bot, force: bool = False) -> int:
    global _last_check
    if not can_pay() or (not force and time.time() - _last_check < 25):
        return 0
    _last_check = time.time()
    awaiting = [o for o in await db.orders_by_status("awaiting") if o["amount"]]
    if not awaiting:
        return 0
    since = min(o["created"] for o in awaiting) - 300
    transfers = []
    for enabled, fetch, name in ((config.PAY_TON_ADDRESS, fetch_ton, "toncenter"),
                                 (config.PAY_TRON_ADDRESS, fetch_tron, "TronGrid")):
        if not enabled:
            continue
        try:
            transfers += await fetch(since)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("%s недоступен: %s", name, exc)
    paid = 0
    for t in transfers:
        if await db.tx_seen(t["tx"]):
            continue
        await db.mark_tx(t["tx"])
        order = match_order(t, awaiting)
        if order is None:
            await notify.owners(bot, f"💸 Пришёл платёж {usdt(t['amount'])} USDT ({t['net']}), но я не понял, "
                                     "за какой он заказ. Проверь заказы и отметь оплату вручную.")
            continue
        awaiting = [o for o in awaiting if o["id"] != order["id"]]
        await mark_paid(bot, order["id"], t["tx"])
        paid += 1
    return paid


async def mark_paid(bot: Bot, order_id: int, tx: str = "manual") -> None:
    order = await db.get_order(order_id)
    if not order or order["status"] not in ("awaiting", "moderation"):
        return
    await db.update_order(order_id, status="paid", tx=tx, paid_at=time.time())
    await _tell(bot, order["user_id"], f"💸 Оплата заказа #{order_id} получена, спасибо! Публикую.")
    await notify.owners(bot, f"💸 Заказ #{order_id} оплачен ({esc(order['title'])}), запускаю")
    order = await db.get_order(order_id)
    spawn(run_order(bot, order))


# ---------- публикация ----------

async def post_groups(bot: Bot, order, pin: bool = False) -> int:
    sent = 0
    for chat in [c for c in await db.list_chats() if c["ads"]]:
        try:
            message_id = await send_ad(bot, order, chat["chat_id"])
            sent += 1
            if pin:
                try:
                    await bot.pin_chat_message(chat["chat_id"], message_id, disable_notification=True)
                    await db.add_pin(chat["chat_id"], message_id, time.time() + DAY)
                except Exception as exc:
                    log.info("Не закрепил в %s (нет права?): %s", chat["chat_id"], exc)
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
        except Exception as exc:
            log.info("Заказ %s не ушёл в чат %s: %s", order["id"], chat["chat_id"], exc)
        await asyncio.sleep(0.5)
    return sent


async def broadcast_dm(bot: Bot, order) -> tuple[int, int]:
    ok = fail = 0
    for user_id in await db.dm_user_ids():
        try:
            await send_ad(bot, order, user_id)
            ok += 1
        except TelegramForbiddenError:
            await db.mark_dm_blocked(user_id)
            fail += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)  # не больше ~20 сообщений в секунду
    return ok, fail


async def run_service(bot: Bot, order) -> None:
    """Оплачена аренда или свой бот."""
    oid = order["id"]
    if order["kind"] == "rent":
        from bot.services import approval
        chat = await db.get_chat(order["target"])
        if not chat:
            await db.update_order(oid, status="done", result="чат не найден, разобраться вручную")
            await notify.owners(bot, f"⚠️ Аренда #{oid} оплачена, но чат не найден. Свяжись с заказчиком.")
            return
        await approval.approve(bot, chat["chat_id"], rent_days=order["days"] or 30,
                               announce=not chat["approved"] or not chat["active"])
        chat = await db.get_chat(chat["chat_id"])
        until = approval.until_text(chat["rent_until"])
        await db.update_order(oid, status="done", result=f"аренда до {until}")
        await _tell(bot, order["user_id"], f"✅ Аренда оплачена! Бот работает в {esc(chat['title'])} до {until}. "
                                           "За 3 дня до конца напомню продлить.")
        await notify.owners(bot, f"📅 Аренда в {esc(chat['title'])} оплачена до {until} ({esc(order['user_name'])})")
        return
    await db.update_order(oid, status="done", result="оплачено, ждёт установки")
    await _tell(bot, order["user_id"], "✅ Оплата получена! Скоро с тобой свяжутся, чтобы настроить твоего бота. "
                                       "Можешь сразу написать пожелания: имя, характер, для каких чатов.",
                InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                    text="📝 Написать пожелания", callback_data="act:support:свой бот", style="primary")]]))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="✍️ Написать заказчику", callback_data=f"sup:{order['user_id']}", style="primary")]])
    for owner in config.OWNER_IDS:
        try:
            await bot.send_message(owner, f"💼 <b>Оплачен свой бот</b> (заказ #{oid})\nЗаказчик: "
                                          f"{esc(order['user_name'])} (<code>{order['user_id']}</code>)",
                                   parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass


async def run_order(bot: Bot, order) -> None:
    kind, oid = order["kind"], order["id"]
    if kind in SERVICE_KINDS:
        return await run_service(bot, order)
    await db.update_order(oid, status="running")
    parts = []
    try:
        if kind in ("groups", "both"):
            parts.append(f"в {await post_groups(bot, order)} чатах")
        if kind == "pin_groups":
            parts.append(f"с закрепом в {await post_groups(bot, order, pin=True)} чатах")
        if kind == "pin_channel":
            if config.AD_CHANNEL_ID:
                message_id = await send_ad(bot, order, config.AD_CHANNEL_ID)
                await bot.pin_chat_message(config.AD_CHANNEL_ID, message_id, disable_notification=True)
                await db.add_pin(config.AD_CHANNEL_ID, message_id, time.time() + DAY)
                parts.append("в канале с закрепом")
            else:
                parts.append("канал не настроен, свяжись с поддержкой")
        if kind in ("dm", "both"):
            ok, fail = await broadcast_dm(bot, order)
            parts.append(f"в личку {ok} людям" + (f" (не доставлено {fail})" if fail else ""))
    except Exception:
        log.exception("Заказ %s сломался при публикации", oid)
        parts.append("часть не вышла из-за ошибки, поддержка разберётся")
    result = ", ".join(parts)
    if kind == "groups" and order["days"] > 1:
        await db.update_order(oid, status="running", runs_left=order["days"] - 1, next_run=time.time() + DAY,
                              result=result)
        tail = f"\nДальше по посту в день ещё {order['days'] - 1} дн."
    else:
        await db.update_order(oid, status="done", result=result)
        tail = ""
    if order["price"]:
        await _tell(bot, order["user_id"], f"📣 Реклама по заказу #{oid} вышла: {esc(result)}.{tail}")
    else:
        await notify.owners(bot, f"📢 Рассылка #{oid} готова: {esc(result)}")


async def tick(bot: Bot) -> None:
    now = time.time()
    for order in await db.orders_by_status("running"):
        if order["runs_left"] > 0 and order["next_run"] <= now:
            sent = await post_groups(bot, order)
            left = order["runs_left"] - 1
            await db.update_order(order["id"], runs_left=left, next_run=now + DAY,
                                  status="running" if left else "done")
            log.info("Заказ %s: повтор в %s чатах, осталось %s", order["id"], sent, left)
    for pin in await db.due_pins(now):
        try:
            await bot.unpin_chat_message(pin["chat_id"], message_id=pin["message_id"])
        except Exception:
            pass
        await db.delete_pin(pin["id"])
    for order in await db.orders_by_status("awaiting"):
        if order["next_run"] and order["next_run"] < now:
            await db.update_order(order["id"], status="expired")
            await _tell(bot, order["user_id"], f"⌛ Время на оплату заказа #{order['id']} вышло. "
                                               "Если оплатил, напиши в поддержку.")
    await check_payments(bot)


async def run_scheduler(bot: Bot) -> None:
    await db.seed_products(DEFAULT_PRODUCTS)
    for product in SERVICE_PRODUCTS:
        await db.ensure_product(*product)
    while True:
        try:
            await tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Ошибка в планировщике заказов")
        await asyncio.sleep(30)
