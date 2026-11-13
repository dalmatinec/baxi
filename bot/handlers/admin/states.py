from aiogram.fsm.state import State, StatesGroup


class ChatEdit(StatesGroup):
    value = State()      # ждём новое значение поля чата


class PhraseAdd(StatesGroup):
    collecting = State()  # принимаем фразы, стикеры, гифки


class AdNew(StatesGroup):
    post = State()
    buttons = State()
    interval = State()


class AdEdit(StatesGroup):
    post = State()
    buttons = State()
