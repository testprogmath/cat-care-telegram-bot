"""A chat the bot cannot place belongs to no animal, so it stays silent and records nothing."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import db, main

BERLIN = ZoneInfo("Europe/Berlin")
CLINIC = -7


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **_):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent), date=datetime.now(BERLIN))


def update(chat_id, message_id=1, text="съела 5 г сухариков", title="Ветклиника"):
    message = SimpleNamespace(
        message_id=message_id, text=text, caption=None, date=datetime.now(BERLIN),
        from_user=SimpleNamespace(full_name="owner"), reply_to_message=None,
    )
    return SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=chat_id, title=title, full_name=title),
    )


@pytest.fixture
def parser(monkeypatch):
    calls = []

    async def parse(text, *_args):
        calls.append(text)
        return [SimpleNamespace(type="food", name=None, dose=None, water_ml=None, kcal=18.5,
                                feeding="self", amount_ml=None, temp_c=None, liquid=None,
                                water_fraction=None, time=None, description=text)]

    monkeypatch.setattr(main, "parse_message", parse)
    return calls


def test_a_message_in_an_unknown_chat_is_neither_parsed_nor_stored(chat, parser):
    bot = Bot()
    asyncio.run(main.handle_message(update(CLINIC), SimpleNamespace(bot=bot)))
    assert not parser
    assert not bot.sent
    assert not db.message_seen(CLINIC, 1)
    assert db.profile_for(CLINIC) is None


def test_an_unknown_chat_is_offered_to_nobody(chat, parser):
    asyncio.run(main.handle_message(update(CLINIC), SimpleNamespace(bot=Bot())))
    assert [chat_id for chat_id, _ in db.all_chats()] == [chat]
    assert [chat_id for chat_id, _ in db.active_chats()] == [chat]


@pytest.mark.parametrize("command", [main.stats_command, main.left_command, main.risk_command,
                                     main.meds_command, main.reminders_command, main.help_command])
def test_commands_in_an_unknown_chat_answer_nothing(chat, command):
    bot = Bot()
    message = update(CLINIC).effective_message
    message.reply_text = lambda text: bot.send_message(CLINIC, text)
    asyncio.run(main.for_known_chat(command)(
        SimpleNamespace(effective_chat=SimpleNamespace(id=CLINIC), effective_message=message),
        SimpleNamespace(bot=bot, args=[]),
    ))
    assert not bot.sent


def test_a_bare_profile_command_in_an_unknown_chat_answers_nothing(chat):
    bot = Bot()
    asyncio.run(main.profile_command(SimpleNamespace(effective_chat=SimpleNamespace(id=CLINIC)),
                                     SimpleNamespace(bot=bot, args=[])))
    assert not bot.sent


def test_naming_the_animal_starts_the_diary(chat, parser):
    bot = Bot()
    asyncio.run(main.profile_command(SimpleNamespace(effective_chat=SimpleNamespace(id=CLINIC)),
                                     SimpleNamespace(bot=bot, args=["скрипа"])))
    asyncio.run(main.handle_message(update(CLINIC, 2), SimpleNamespace(bot=bot)))
    assert parser == ["съела 5 г сухариков"]
    assert [row["subject"] for row in db.events_for_day(CLINIC, db.care_day(datetime.now(BERLIN)))] == ["skripa"]
