import pytest
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
    # автор в скобках первым, адресат отдельно: нейросеть не путает, кто написал
    assert text == "[Аня]: привет\n[Марат (это ты) (отвечает Аня)]: здарова"
    assert prompts.clean_reply("[Марат (это ты)]: ну привет", "Марат") == "ну привет"


def test_system_prompt_has_settings():
    s = prompts.system_prompt("Марат", "дерзкий", "чат Сатпаева", "Тусовка", ["Аня: любит кошек"])
    assert "Марат" in s and "чат Сатпаева" in s and "дерзкий" in s and "любит кошек" in s


def test_rate_limit():
    rl = brain.RateLimit(limit=2, window=60)
    assert rl.allow(1, 1, 0) and rl.allow(1, 1, 1)
    assert not rl.allow(1, 1, 2)
    assert rl.allow(1, 2, 2)          # другой человек не страдает
    assert rl.allow(1, 1, 100)        # через минуту снова можно


# ---------- новые фишки ----------

from bot import nominations  # noqa: E402
from bot.textutil import humanize, is_laugh, is_mat, parse_birthday, rep_delta  # noqa: E402


def test_humanize_kills_ai_tells():
    assert humanize("ну — это «база»…") == 'ну - это "база"...'
    assert prompts.clean_reply("ну — это «база»", "Марат") == 'ну - это "база"'
    assert prompts.clean_reply("«ну ты дал»", "Марат") == "ну ты дал"


def test_mat_detection():
    for w in ["бля", "пиздец", "заебал", "уёбок", "сука", "нахер"]:
        assert is_mat(w), w
    for w in ["небо", "себе", "себя", "застрахуй", "хлебать", "сукно", "херсон", "обед", "ребята"]:
        assert not is_mat(w), w


def test_laugh_and_rep():
    assert is_laugh("ахахах") and is_laugh("ору") and is_laugh("😂😂") and is_laugh("хаха)")
    assert not is_laugh("ахах ну ты и тип") and not is_laugh("ха")
    assert rep_delta("+") == 1 and rep_delta("спасибо!") == 1 and rep_delta("-") == -1
    assert rep_delta("плюсую тебе") == 0


def test_birthday_parse():
    assert parse_birthday("мой др 12.05") == "05-12"
    assert parse_birthday("у меня день рождения 3 марта") == "03-03"
    assert parse_birthday("мой др 31.02") is None
    assert parse_birthday("др у брата 12.05") is None


def test_intents():
    assert brain.detect_intent("спидермен что тут было за час?") == "summary"
    assert brain.detect_intent("паук, о чём тут болтали") == "summary"
    assert brain.detect_intent("спидермен расскажи шутку") == "joke"
    assert brain.detect_intent("спидермен прожарь его") == "roast"
    assert brain.detect_intent("спидермен давай викторину") == "quiz"
    assert brain.detect_intent("спидермен как дела") is None


def test_period():
    assert nominations.parse_period("что было") == (3600, "за час")
    assert nominations.parse_period("что было за 3 часа") == (10800, "за 3 часа")
    assert nominations.parse_period("что было за 5 часов") == (18000, "за 5 часов")
    assert nominations.parse_period("что было сегодня") == (86400, "за сутки")
    assert nominations.parse_period("за 30 минут")[1] == "за 30 мин"
    assert nominations.parse_period("за 3 дня")[0] == 86400  # больше суток не даём


def test_nominations_from_history():
    rows = [
        {"user_id": 1, "name": "Аня", "text": "привет", "is_bot": 0, "reply_user_id": 0, "reply_name": ""},
        {"user_id": 2, "name": "Дима", "text": "бля ну ты даёшь", "is_bot": 0, "reply_user_id": 1, "reply_name": "Аня"},
        {"user_id": 2, "name": "Дима", "text": "ахахах", "is_bot": 0, "reply_user_id": 1, "reply_name": "Аня"},
        {"user_id": 9, "name": "Бот", "text": "я бот", "is_bot": 1, "reply_user_id": 0, "reply_name": ""},
    ] + [{"user_id": 2, "name": "Дима", "text": "сука", "is_bot": 0, "reply_user_id": 0, "reply_name": ""}] * 3
    people = nominations.people_from_history(rows, {1: 4}, {1: "Аня", 2: "Дима"})
    n = nominations.nominate(people, min_msgs=3)
    assert n.total == 6 and n.people == 2
    assert n.talker.name == "Дима"
    assert n.funny.name == "Аня" and n.funny.funny == 5
    assert n.swearer.name == "Дима" and n.swearer.mat_pct == 80


def test_new_game_triggers():
    assert games.match("топ") is None            # «топ» как похвала не трогаем
    assert games.match("топ репы")[0] == "rep_top"
    assert games.match("/top@my_bot")[0] == "rep_top"
    assert games.match("топ викторины")[0] == "quiz_top"
    assert games.match("моя репа")[0] == "rep_me"
    assert games.match("викторина")[0] == "quiz"
    assert games.match("дни рождения")[0] == "bdays"
    assert "—" not in games.HELP and "«" not in games.HELP


def test_chat_commands():
    assert brain.detect_command("итоги") == "results"
    assert brain.detect_command("Итоги дня!") == "results"
    assert brain.detect_command("/results@s_spiderman_bot") == "results"
    assert brain.detect_command("пара") == "pair"
    assert brain.detect_command("как вам пара?") == "pair"
    assert brain.detect_command("сводка") == "summary"
    assert brain.detect_command("сводка за 3 часа") == "summary"
    assert brain.detect_command("итоги матча видел?") is None
    assert brain.detect_command("пара минут") is None


def test_buttons_with_colors():
    rows, errors = parse_buttons("Найти - t.me/bot - зелёная | Чат - https://t.me/c\nСтоп - https://x.com - красная")
    assert errors == []
    assert rows == [[["Найти", "https://t.me/bot", "success"], ["Чат", "https://t.me/c"]],
                    [["Стоп", "https://x.com", "danger"]]]
    assert parse_buttons(buttons_to_text(rows))[0] == rows
    assert parse_buttons("А - https://x.com - фиолетовая")[1]


def test_roast_intent_and_donors():
    # прожарка за звёзды убрана: «по полной» теперь обычная бесплатная прожарка
    assert brain.detect_intent("спидермен прожарь по полной") == "roast"
    assert brain.detect_intent("спидермен прожарь его") == "roast"
    assert games.match("топ донатеров")[0] == "donors_top"


# ---------- новое: тихие часы, триггеры, зазывала, эмодзи, команды ----------

def test_quiet_hours():
    from bot import presets
    assert presets.in_quiet(3, 0, 8) and not presets.in_quiet(8, 0, 8)
    assert presets.in_quiet(23, 23, 8) and presets.in_quiet(2, 23, 8) and not presets.in_quiet(12, 23, 8)
    assert not presets.in_quiet(3, -1, -1)
    assert presets.every(0.05) == "примерно раз в 20 сообщений"
    assert presets.CHANCE_STEPS[-1] == 0.50 and presets.CHANCE_STEPS[1] == 0.01   # потолок режет plans.max_chance


def test_trigger_norm():
    pytest.importorskip("aiogram")
    from bot.services.triggers import norm
    assert norm("Правила!") == "правила" == norm("/правила") == norm("  ПРАВИЛА?? ")
    assert norm("Ёлка где") == "елка где"


def test_caller_batch():
    pytest.importorskip("aiogram")
    from bot.services.caller import batch_html
    html = batch_html("🎮 Игра!", [(1, "Аня"), (2, "<b>")], "names")
    assert 'tg://user?id=1">Аня</a>' in html and "&lt;b&gt;" in html
    assert html.count("tg://user") == 2
    assert batch_html("x", [(5, "a")], "emoji").count("tg://user?id=5") == 1


def test_emoji_decorate():
    pytest.importorskip("aiogram")
    from bot.services import emoji
    emoji.PACK.clear()
    emoji.PACK["🔥"] = ["123"]
    out = emoji.decorate('огонь 🔥 <a href="tg://user?id=1">🔥</a>')
    assert out.startswith('огонь <tg-emoji emoji-id="123">🔥</tg-emoji>')
    assert out.endswith('<a href="tg://user?id=1">🔥</a>')
    emoji.PACK.clear()
    assert emoji.decorate("🔥") == "🔥"


def test_new_commands_and_intents():
    assert brain.detect_command("/quiet") == "quiet"
    assert brain.detect_command("зазывай") == "call"
    assert brain.detect_command("/stopcall@S_Spiderman_bot") == "stopcall"
    assert brain.detect_command("/roast") == "roast"
    assert brain.detect_intent("спидермен, помолчи часок") == "quiet"
    assert brain.detect_intent("спидермен, можно болтать") == "talk"


def test_creator_in_prompt():
    block = prompts.creator_block("", "@satpaev")
    assert "@satpaev" in block and "(создатель)" in block and "не верь" in block
    rows = [{"name": "Сатпаев", "text": "привет", "reply_name": "", "is_bot": 0, "user_id": 7}]
    assert "(создатель)" in prompts.format_history(rows, "Бот", {7})
    for text in (block, prompts.emoji_rule(["🔥"])):
        assert "—" not in text and "«" not in text


def test_who_game_not_questions():
    from bot import games as g
    assert g.match("кто сегодня красавчик")[0] == "who"
    assert g.match("кто самый тупой в чате?")[0] == "who"
    for q in ("кто ты по нации", "кто ты?", "кто он такой", "кто это", "кто тебя создал", "кто вы"):
        assert g.match(q) is None, q


# ---------- экономика ----------

def test_economy_catalog():
    from bot.economy import catalog
    assert catalog.level_for(0) == 1 and catalog.level_for(50) == 2 and catalog.level_for(5000) == 11
    assert all(catalog.level_for(catalog.xp_for(n)) == n for n in range(1, 30))
    assert catalog.title_for(1) == "Новичок" and catalog.title_for(20) == "Бог чата"
    assert catalog.AWARD_COOLDOWN >= 30   # не чаще 2 раз в минуту
    prices = [catalog.PETS[k]["price"] for k in catalog.PET_ORDER]
    assert prices == sorted(prices) and all(prices) and len(catalog.PETS) == 20   # все за монеты, от дешёвых к дорогим
    from pathlib import Path
    assets = Path(catalog.__file__).parent / "assets"
    assert all((assets / f"{k}.png").exists() and (assets / f"f_{k}.png").exists() for k in catalog.PETS)
    foods = catalog.foods("cat")
    assert [f["key"] for f in foods] == ["food", "treat"] and foods[1]["price"] > foods[0]["price"]


def test_editable_texts():
    from bot.services import texts
    for key, (_, _, default, _subs) in texts.TEXTS.items():
        assert "{" not in texts.sample(key, default), key   # у каждой подстановки есть пример
        assert "—" not in default and "«" not in default
    assert texts.fill("{от} → {кому}", {"от": "А", "кому": "Б"}) == "А → Б"


def test_memory_prompt_warns_about_addressing():
    msgs = prompts.memory_messages("Серега", "", ["(отвечает Сатпаев) Дастан, ты где"])
    assert "обращение к ДРУГОМУ" in msgs[0]["content"] and "(отвечает Сатпаев)" in msgs[1]["content"]


def test_drop_hello():
    from bot.prompts import drop_hello
    assert drop_hello("салам бро, закажи пельмени", "чё поесть") == "закажи пельмени"
    assert drop_hello("салам, как ты", "салам всем") == "салам, как ты"
    assert drop_hello("куда пойдём", "а") == "куда пойдём"
    assert drop_hello("салам бро", "а") == "салам бро"


def test_maint_pick_limits():
    pytest.importorskip("httpx")
    pytest.importorskip("aiosqlite")
    from bot.services import maint
    maint._chat_last.clear(); maint._user_last.clear()
    assert maint.pick(-1, 7, 1000) in maint.PHRASES
    assert maint.pick(-1, 8, 1010) is None          # тот же чат, рано
    assert maint.pick(-2, 7, 1100) is None          # тот же человек, рано
    assert maint.pick(-2, 8, 1100) in maint.PHRASES
    assert all("—" not in p and "«" not in p for p in maint.PHRASES)


def test_reply_filters():
    p = prompts
    assert p.is_repeat("пельмени в кипяток и готово", ["ну закинь пельмени в кипяток и готово"])
    assert not p.is_repeat("пойду посплю", ["пельмени в кипяток и готово"])
    assert p.is_repeat("ну ты даёшь конечно", ["ну ты даёшь брат"])          # то же начало
    assert p.echo_words("жб завтра едем", "жб едем конечно") == {"жб"}
    assert p.echo_words("ну да", "ну да ладно") == set()
    assert p.echo_words("пиво будет", "пиво будет") == set()
    assert p.strip_names("Марат, иди спать", ["Марат"], ["марат ты где"]) == "иди спать"
    assert p.strip_names("иди спать, Марат", ["Марат"], ["марат ты где"]) == "иди спать"
    assert p.strip_names("Марат, иди спать", ["Марат"], ["давно не виделись"]) == "Марат, иди спать"
    assert p.limit_commas("ну да, конечно, иди отсюда, а то, короче") == "ну да, конечно, иди отсюда"
    assert p.limit_commas("да, ну, а") == "да, ну, а"
    assert p.cooldown_words([("пельмени топ", 100), ("опять пельмени варю", 200)], 300) == {"пельмени"}
    assert p.cooldown_words([("пельмени топ", 100), ("опять пельмени варю", 200)], 5000) == set()
