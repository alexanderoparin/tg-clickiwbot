from aiogram.fsm.state import State, StatesGroup


class NewAnalysis(StatesGroup):
    file = State()
    label = State()
    price = State()
    drr = State()
    drr_custom = State()


class SettingsForm(StatesGroup):
    price = State()
    drr = State()
