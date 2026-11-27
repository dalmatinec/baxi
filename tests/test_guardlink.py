"""Связь с модератором: API Бакси (127.0.0.1, X-Key), события, ники. python -m pytest -q"""

import asyncio
import time
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot import config, db
from bot.services import api, guardlink

KEY = "test-key"
CHAT = -1001234567890


class FakeBot:
    async def get_chat_administrators(self, chat_id):
        return [SimpleNamespace(user=SimpleNamespace(id=111)), SimpleNamespace(user=SimpleNamespace(id=777))]

    async def send_message(self, *a, **k):
        return SimpleNamespace(message_id=1, chat=SimpleNamespace(id=CHAT))


def run(tmp_path, monkeypatch, fn):
    monkeypatch.setattr(config, "BAXI_API_KEY", KEY)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "bot.db")

    async def go():
        await db.connect()
        from bot.economy import store
        await store.init()
        await guardlink.init()
        c = TestClient(TestServer(api.make_app(FakeBot())))
        await c.start_server()
        try:
            return await fn(c)
        finally:
            await c.close()
            await db.close()
            db._db = None
    return asyncio.run(go())


H = {"X-Key": KEY}


def event(kind, **kw):
    return {"type": kind, "chat_id": CHAT, "user_id": 5, "by_id": 111, "until": 0, "reason": "", "warns": 0,
            "warn_limit": 3, "ts": int(time.time()), **kw}


def test_auth(tmp_path, monkeypatch):
    async def fn(c):
        assert (await c.get(f"/v1/chat/{CHAT}")).status == 401
        assert (await c.get(f"/v1/chat/{CHAT}", headers={"X-Key": "nope"})).status == 401
        assert (await c.post("/v1/events", json=event("warn"))).status == 401
        assert (await c.get("/v1/ping", headers=H)).status == 200
    run(tmp_path, monkeypatch, fn)


def test_chat_info_tariffs(tmp_path, monkeypatch):
    async def fn(c):
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert data["known"] is False and data["paid"] is False
        await db.ensure_chat(CHAT, "Тест")
        await db.update_chat(CHAT, approved=1, active=1, rent_until=time.time() + 86400, trial=0, free=0)
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert data["known"] and data["active"] and data["paid"] and not data["trial"] and data["until"] > 0
        await db.update_chat(CHAT, trial=1)
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert data["trial"] and not data["paid"]
        await db.update_chat(CHAT, trial=0, free=1)
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert data["free"] and not data["paid"] and not data["trial"]
        await db.update_chat(CHAT, free=0, rent_until=0)      # без срока: твои чаты считаются оплаченными
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert data["paid"]
        await db.update_chat(CHAT, rent_until=time.time() - 10)   # аренда кончилась
        data = await (await c.get(f"/v1/chat/{CHAT}", headers=H)).json()
        assert not data["paid"]
    run(tmp_path, monkeypatch, fn)


def test_trusted(tmp_path, monkeypatch):
    async def fn(c):
        await db.ensure_chat(CHAT, "Тест")
        await db.touch_user(CHAT, 42, "Вип", "vip")
        await db.set_perks(42, vip_until=time.time() + 3600)
        data = await (await c.get(f"/v1/chat/{CHAT}/trusted", headers=H)).json()
        assert data == {"admins": [111, 777], "vip": [42]}
    run(tmp_path, monkeypatch, fn)


def test_events_state_and_summary(tmp_path, monkeypatch):
    async def fn(c):
        await db.ensure_chat(CHAT, "Тест")
        r = await c.post("/v1/events", headers=H, json=event("warn", warns=2))
        assert (await r.json()) == {"ok": True}
        assert await guardlink.warns_line(CHAT, 5) == "⚠️ предупреждения 2/3"
        assert not await guardlink.is_blocked(CHAT, 5)
        await c.post("/v1/events", headers=H, json=event("mute", until=int(time.time()) + 3600, warns=0))
        assert await guardlink.is_blocked(CHAT, 5)
        assert await guardlink.warns_line(CHAT, 5) == ""   # на лимите модератор обнуляет
        await c.post("/v1/events", headers=H, json=event("unmute"))
        assert not await guardlink.is_blocked(CHAT, 5)
        await c.post("/v1/events", headers=H, json=event("ban", user_id=6))
        assert await guardlink.blocked_ids(CHAT) == {6}
        await c.post("/v1/events", headers=H, json=event("spam", user_id=7))
        counts = await guardlink.day_counts(CHAT, time.time() - 3600)
        assert counts == {"warn": 1, "mute": 1, "unmute": 1, "ban": 1, "spam": 1}
        assert guardlink.summary_line(counts) == ("🛡 <b>За день:</b> 1 мут, 1 предупреждение, 1 бан, "
                                                  "1 спам удалён")
        assert (await c.post("/v1/events", headers=H, json=event("hug"))).status == 400
        assert (await c.post("/v1/events", headers=H, data="не json")).status == 400
    run(tmp_path, monkeypatch, fn)


def test_ban_removes_from_games_and_lists(tmp_path, monkeypatch):
    async def fn(c):
        from bot.economy import service, store
        await db.ensure_chat(CHAT, "Тест")
        await db.call_add(CHAT, 5, "Вася")
        await store.wallet(5, "Вася")
        await store.wallet(9, "Петя")
        await store.add_coins(5, 500)
        await store.add_coins(9, 500)
        before = (await store.wallet(5))["coins"], (await store.wallet(9))["coins"]
        duel = await service.start_duel(CHAT, 5, "Вася", 9, "Петя", 100)
        assert not isinstance(duel, str), duel
        assert (await service.accept_duel(CHAT, 9, duel.id))[0] == ""
        await c.post("/v1/events", headers=H, json=event("ban"))
        assert service.active_duel(CHAT) is None
        assert ((await store.wallet(5))["coins"], (await store.wallet(9))["coins"]) == before   # ставки вернулись
        assert [r["user_id"] for r in await db.call_list(CHAT)] == []
    run(tmp_path, monkeypatch, fn)


def test_nicks(tmp_path, monkeypatch):
    async def fn(c):
        await db.ensure_chat(CHAT, "Тест")
        await db.touch_user(CHAT, 5, "Вася", "vasya")
        data = await (await c.get("/v1/user/5", headers=H)).json()
        assert data["name"] == "Вася" and data["nick"] == "" and data["nick_plain"] == "Вася"
        await db.set_perks(5, look_forever=1, nick="𝐁𝐚𝐤𝐬𝐢 ✨", emoji_alt="🔥", emoji_id="123")
        data = await (await c.get("/v1/user/5", headers=H)).json()
        assert data["nick"] == "𝐁𝐚𝐤𝐬𝐢 ✨" and data["nick_plain"] == "Baksi" and data["emoji_id"] == "123"
        data = await (await c.get("/v1/users?ids=5,6", headers=H)).json()
        assert set(data["users"]) == {"5", "6"} and data["users"]["6"]["name"] == ""
    run(tmp_path, monkeypatch, fn)


def test_tease_when_enabled(tmp_path, monkeypatch):
    said = []

    async def fake_in_character(bot, chat_id, situation, fallbacks, *a, **k):
        said.append((chat_id, situation, fallbacks))

    async def fn(c):
        from bot.services import talk
        monkeypatch.setattr(talk, "in_character", fake_in_character)
        monkeypatch.setattr(guardlink.random, "random", lambda: 0.0)
        guardlink._last_tease.clear()
        await db.ensure_chat(CHAT, "Тест")
        await db.update_chat(CHAT, approved=1, active=1)
        await db.touch_user(CHAT, 5, "Вася", "vasya")
        await c.post("/v1/events", headers=H, json=event("mute", until=int(time.time()) + 60))
        assert said == []                                  # подколки по умолчанию выключены
        await db.update_chat(CHAT, guard_tease=1)
        await c.post("/v1/events", headers=H, json=event("warn", warns=1, reason="флуд"))
        assert len(said) == 1 and "Вася" in said[0][1] and "флуд" in said[0][1]
        await c.post("/v1/events", headers=H, json=event("ban"))
        assert len(said) == 1                              # не чаще раза в 10 минут
    run(tmp_path, monkeypatch, fn)


@pytest.mark.parametrize("raw,ok", [
    ({"type": "warn", "chat_id": -1, "user_id": 2}, True),
    ({"type": "warn", "chat_id": -1}, False),
    ({"type": "nope", "chat_id": -1, "user_id": 2}, False),
    ({"type": "mute", "chat_id": "x", "user_id": 2}, False),
])
def test_parse_event(raw, ok):
    if ok:
        assert guardlink.parse_event(raw)["type"] == raw["type"]
    else:
        with pytest.raises(ValueError):
            guardlink.parse_event(raw)


def test_plain_nick():
    assert guardlink.plain_nick("𝓑𝓪𝓴𝓼𝓲 👑") == "Baksi"
    assert guardlink.plain_nick("Ｖａｓｙａ_99") == "Vasya_99"
    assert guardlink.plain_nick("  Петя   Пупкин ") == "Петя Пупкин"


def test_card_lines(tmp_path, monkeypatch):
    async def fn(c):
        await db.ensure_chat(CHAT, "Тест")
        assert await guardlink.card_lines(CHAT, 5) == ("🛡 нарушений нет", [])
        await c.post("/v1/events", headers=H, json=event("warn", warns=1, reason="флуд"))
        await c.post("/v1/events", headers=H, json=event("ban", until=0, warns=1, reason="реклама"))
        status, lines = await guardlink.card_lines(CHAT, 5)
        assert status == "🛡 предупреждения 1/3 · бан навсегда"
        assert "бан: реклама" in lines[0] and "предупреждение: флуд" in lines[1]
        await c.post("/v1/events", headers=H, json=event("unban"))
        await c.post("/v1/events", headers=H, json=event("unwarn", warns=0))
        status, lines = await guardlink.card_lines(CHAT, 5)
        assert status == "🛡 сейчас чисто" and len(lines) == 2
    run(tmp_path, monkeypatch, fn)


def test_chat_user_stats(tmp_path, monkeypatch):
    async def fn(c):
        await db.ensure_chat(CHAT, "Тест")
        await db.touch_user(CHAT, 5, "Вася", "vasya")
        await db.rep_change(CHAT, 6, 5, 3)
        data = await (await c.get(f"/v1/chat/{CHAT}/user/5", headers=H)).json()
        assert data["reputation"] == 3 and data["rep_place"] == 1 and data["rank_level"] >= 1 and "coins" in data
        assert (await c.get(f"/v1/chat/{CHAT}/user/5")).status == 401
    run(tmp_path, monkeypatch, fn)


def test_coins_spend_and_wallet(tmp_path, monkeypatch):
    async def fn(c):
        from bot.economy import store
        await store.add_coins(42, 6000, "Вася")
        w = await (await c.get("/v1/wallet/42", headers=H)).json()
        assert w["coins"] == 6000
        body = {"user_id": 42, "amount": 5000, "ref": "nick:42:1", "reason": "ник"}
        r = await (await c.post("/v1/coins/spend", headers=H, json=body)).json()
        assert r == {"ok": True, "coins": 1000}
        r = await (await c.post("/v1/coins/spend", headers=H, json=body)).json()   # повтор не списывает
        assert r["ok"] and r["repeat"] and r["coins"] == 1000
        r = await (await c.post("/v1/coins/spend", headers=H, json={**body, "ref": "nick:42:2"})).json()
        assert r == {"ok": False, "error": "not_enough", "coins": 1000}
        r = await (await c.post("/v1/coins/spend", headers=H, json={**body, "ref": "nick:42:2", "amount": 1000})).json()
        assert r == {"ok": True, "coins": 0}            # неудачный ref можно повторить, когда монеты появились
        assert (await c.post("/v1/coins/spend", headers=H, json={"user_id": 42, "amount": -5, "ref": "x"})).status == 400
        assert (await c.post("/v1/coins/spend", json=body)).status == 401
    run(tmp_path, monkeypatch, fn)


def test_signals_greet_mode_nick_join(tmp_path, monkeypatch):
    async def fn(c):
        from bot import textutil
        from bot.services import talk
        await db.ensure_chat(CHAT, "Тест")
        await db.update_chat(CHAT, approved=1, active=1, greet=1)
        r = await c.post("/v1/events", headers=H, json={"type": "greet_mode", "chat_id": CHAT, "on": True})
        assert r.status == 200 and guardlink.guard_greets(CHAT)
        await c.post("/v1/events", headers=H, json={"type": "greet_mode", "chat_id": CHAT, "on": False})
        assert not guardlink.guard_greets(CHAT)
        # ник из модератора
        nick = {"type": "nick", "user_id": 42, "head": '<tg-emoji emoji-id="1">🔥</tg-emoji> ',
                "body": "<b>Вася</b>", "tail": "", "plain": "Вася"}
        assert (await c.post("/v1/events", headers=H, json=nick)).status == 200
        assert textutil.mention(42, "Василий") == '<tg-emoji emoji-id="1">🔥</tg-emoji> ' \
                                                 '<a href="tg://user?id=42"><b>Вася</b></a>'
        await c.post("/v1/events", headers=H, json={**nick, "body": ""})
        assert textutil.mention(42, "Василий") == '<a href="tg://user?id=42">Василий</a>'
        # приветствие после модератора
        greeted = []

        async def fake_greet(bot, chat, user_id, name, thread=None):
            greeted.append((user_id, name))
        monkeypatch.setattr(talk, "greet", fake_greet)
        guardlink._last_greet.clear()
        join = {"type": "join", "chat_id": CHAT, "user_id": 50, "name": "Новичок"}
        await c.post("/v1/events", headers=H, json=join)
        await c.post("/v1/events", headers=H, json={**join, "user_id": 51})       # наплыв: вторая фраза позже
        assert greeted == [(50, "Новичок")]
        await db.update_chat(CHAT, greet=0)
        guardlink._last_greet.clear()
        await c.post("/v1/events", headers=H, json=join)
        assert greeted == [(50, "Новичок")]                                          # «здороваться» выключено
        assert (await c.post("/v1/events", headers=H, json={"type": "join", "chat_id": CHAT})).status == 400
        assert (await guardlink.day_counts(CHAT, 0)) == {}                           # в историю не попали
    run(tmp_path, monkeypatch, fn)


def test_chat_move_from_guard(tmp_path, monkeypatch):
    async def fn(c):
        new = CHAT - 1
        body = {"src": CHAT, "dst": new, "by_id": 111}
        r = await c.post("/v1/chat/move", headers=H, json=body)
        assert r.status == 404 and (await r.json())["error"] == "no_src"
        await db.ensure_chat(CHAT, "Старый")
        rent = int(time.time()) + 10 * 86400
        await db.update_chat(CHAT, approved=1, active=1, rent_until=rent)
        r = await c.post("/v1/chat/move", headers=H, json=body)
        assert (await r.json())["error"] == "no_dst"                 # Бакси ещё нет в новом чате
        await db.ensure_chat(new, "Новый")
        r = await (await c.post("/v1/chat/move", headers=H, json=body)).json()
        assert r["ok"] and "counts" in r
        assert (await db.get_chat(new))["rent_until"] == rent       # аренда ушла в новый чат
        assert (await db.get_chat(CHAT))["rent_until"] == 0
        r = await (await c.post("/v1/chat/move", headers=H, json=body)).json()
        assert r["ok"] and r["already"]                               # повтор ничего не делает
        assert (await c.post("/v1/chat/move", json=body)).status == 401
    run(tmp_path, monkeypatch, fn)
