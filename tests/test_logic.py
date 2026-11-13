"""Тесты чистой логики (без Telegram и сети): python -m pytest -q"""

import random

from bot import brain, games, prompts
from bot.textutil import buttons_to_text, parse_buttons


# ---------- когда бот отвечает ----------

def test_aliases_parse():
    assert brain.parse_aliases("Марат", "маратик, мара ,  ,бро") == ["марат", "маратик", "мара", "бро"]


def test_name_in_text_any_case_and_form():
    al = brain.parse_aliases("Марат", "")
    assert brain.mentions_name("Марат, ты где?", al)
    assert brain.mentions_name("скажи марату что он красавчик", al)
    assert brain.mentions_name("маратик привет", al)
    assert not brain.mentions_name("марафон был вчера", al)
    assert not brain.mentions_name("привет всем", al)


def test_short_alias_only_whole_word():
    al = brain.parse_aliases("Бро", "")
    assert brain.mentions_name("бро, ты тут?", al)
    assert not brain.mentions_name("бронь на завтра", al)


def test_multiword_alias():
    al = brain.parse_aliases("Марат", "дядя мар")
    assert brain.mentions_name("эй Дядя Мар, привет", al)


def test_addressed_by_reply_and_username():
    al = ["марат"]
    assert brain.is_addressed("ага", "marat_bot", al, reply_to_bot=True)
    assert brain.is_addressed("@Marat_Bot глянь", "marat_bot", al, reply_to_bot=False)
    assert not brain.is_addressed("просто текст", "marat_bot", al, reply_to_bot=False)


def test_decide_addressed_always_ai():
    assert brain.decide(True, 100, 99, 90, 0.0, 0.0) is brain.Act.AI_REPLY


def test_decide_respects_cooldown():
    assert brain.decide(False, 100, 50, 90, 1.0, 1.0) is brain.Act.NONE


def test_decide_shares():
    rnd = random.Random(1)
    acts = [brain.decide(False, 10_000, 0, 90, 1.0, 0.3, rnd) for _ in range(2000)]
    ai_share = acts.count(brain.Act.AI_JUMP) / len(acts)
    assert brain.Act.NONE not in acts
    assert 0.25 < ai_share < 0.35


def test_decide_zero_chance_never_jumps():
    rnd = random.Random(2)
    assert all(brain.decide(False, 10_000, 0, 90, 0.0, 1.0, rnd) is brain.Act.NONE for _ in range(500))


# ---------- игры ----------

def test_ship_stable_and_symmetric():
    p1 = games.ship_percent(1, 2, "2026-11-13")
    assert p1 == games.ship_percent(2, 1, "2026-11-13")
    assert 0 <= p1 <= 100
    assert len(games.ship_bar(p1)) >= 10


def test_game_triggers():
    assert games.match("Пара дня")[0] == "couple"
    assert games.match("шип")[0] == "ship"
    assert games.match("кто сегодня красавчик?") == ("who", "сегодня красавчик")
    assert games.match("/games@my_bot")[0] == "help"
    assert games.match("предсказание!")[0] == "predict"
    assert games.match("пара") is None
    assert games.match("шипучка") is None


def test_pick_couple():
    assert games.pick_couple([1]) is None
    a, b = games.pick_couple([1, 2, 2, 3], random.Random(0))
    assert a != b


# ---------- кнопки рекламы ----------

def test_parse_buttons_rows():
    rows, errors = parse_buttons("Общение 💬 - https://t.me/chat | Найти - t.me/bot\nХочу 💋 — https://x.com/a")
    assert errors == []
    assert rows == [[["Общение 💬", "https://t.me/chat"], ["Найти", "https://t.me/bot"]],
                    [["Хочу 💋", "https://x.com/a"]]]
    assert parse_buttons(buttons_to_text(rows))[0] == rows


def test_parse_buttons_errors():
    rows, errors = parse_buttons("без ссылки\nКнопка - не_ссылка")
    assert rows == [] and len(errors) == 2


# ---------- промпты ----------

def test_clean_reply_strips_own_name_and_quotes():
    assert prompts.clean_reply("Марат: «ну ты дал»", "Марат") == "ну ты дал"
    assert prompts.clean_reply("Марат (это ты): ага", "Марат") == "ага"
    assert prompts.clean_reply("маратик красавчик", "Марат") == "маратик красавчик"
    assert "@all" not in prompts.clean_reply("@all всем привет", "Марат")


def test_history_format():
    rows = [{"name": "Аня", "text": "привет", "reply_name": "", "is_bot": 0},
            {"name": "Марат", "text": "здарова", "reply_name": "Аня", "is_bot": 1}]
    text = prompts.format_history(rows, "Марат")
    assert text == "Аня: привет\nМарат (это ты) → Аня: здарова"


def test_system_prompt_has_settings():
    s = prompts.system_prompt("Марат", "дерзкий", "чат Сатпаева", "Тусовка", ["Аня: любит кошек"])
    assert "Марат" in s and "чат Сатпаева" in s and "дерзкий" in s and "любит кошек" in s


def test_rate_limit():
    rl = brain.RateLimit(limit=2, window=60)
    assert rl.allow(1, 1, 0) and rl.allow(1, 1, 1)
    assert not rl.allow(1, 1, 2)
    assert rl.allow(1, 2, 2)          # другой человек не страдает
    assert rl.allow(1, 1, 100)        # через минуту снова можно
