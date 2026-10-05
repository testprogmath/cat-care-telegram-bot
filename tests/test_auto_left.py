"""A message that adds calories gets the /left progress as a reply."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import main

BERLIN = ZoneInfo("Europe/Berlin")
_ids = iter(range(1000, 2000))


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_parameters=None, **_):
        self.sent.append((text, reply_parameters and reply_parameters.message_id))
        return SimpleNamespace(message_id=next(_ids), date=datetime.now(BERLIN))


def food(**fields):
    base = dict(type="food", name=None, dose=None, water_ml=None, kcal=None, feeding="self",
                amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                description="поел")
    return SimpleNamespace(**{**base, **fields})


def receive(chat_id, message_id, text, events, monkeypatch):
    async def parsed(*_args):
        return events

    monkeypatch.setattr(main, "parse_message", parsed)
    bot = Bot()
    message = SimpleNamespace(
        message_id=message_id, text=text, caption=None, date=datetime.now(BERLIN),
        from_user=SimpleNamespace(full_name="owner"), reply_to_message=None,
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=chat_id, title="Чипуня", full_name="Чипуня"),
    )
    asyncio.run(main.handle_message(update, SimpleNamespace(bot=bot)))
    return bot.sent


def test_a_feeding_with_calories_is_answered_with_the_progress(chat, monkeypatch):
    sent = receive(chat, 1, "съел 3 г сухариков", [food(kcal=11.1)], monkeypatch)
    assert len(sent) == 1
    text, reply_to = sent[0]
    assert reply_to == 1
    now = datetime.now(main.TIMEZONE)
    expected = main.render_progress(
        main.db.events_for_day(chat, main.db.care_day(now)), now, main.db.profile_for(chat)
    )
    assert text.splitlines()[1:] == expected.splitlines()[1:]
    assert text.startswith("📈 Чипуня — итог на ")


@pytest.mark.parametrize(
    ("text", "events"),
    [
        ("пописал", [food(type="toilet", feeding=None, description="пописал")]),
        ("полизал подливку", [food(description="полизал подливку")]),
        ("за сутки съел 120 ккал", [food(kcal=120.0)]),
    ],
)
def test_a_message_without_new_calories_gets_no_reply(chat, monkeypatch, text, events):
    assert receive(chat, 2, text, events, monkeypatch) == []
