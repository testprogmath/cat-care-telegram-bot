"""A care record that names the other cat and records nothing is pointed out at once."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import messages, profiles

BERLIN = ZoneInfo("Europe/Berlin")


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_parameters=None, **_):
        self.sent.append((text, reply_parameters and reply_parameters.message_id))
        return SimpleNamespace(message_id=9000, date=datetime.now(BERLIN))


def water(ml):
    return SimpleNamespace(type="water", name=None, dose=None, water_ml=ml, kcal=None, feeding="tube",
                           amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                           description=f"дали {ml} мл")


def receive(chat_id, message_id, text, events, monkeypatch):
    async def parsed(*_args):
        return events

    monkeypatch.setattr(messages, "parse_message", parsed)
    bot = Bot()
    message = SimpleNamespace(
        message_id=message_id, text=text, caption=None, date=datetime.now(BERLIN),
        from_user=SimpleNamespace(full_name="owner"), reply_to_message=None,
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=chat_id, title="Чипуня", full_name="Чипуня"),
    )
    asyncio.run(messages.handle_message(update, SimpleNamespace(bot=bot)))
    return bot.sent


def test_a_record_for_the_other_cat_is_pointed_out(chat, monkeypatch):
    sent = receive(chat, 1, "Скрипе дали 35мл лактата рингера в 22.50", [], monkeypatch)
    assert sent == [("Здесь названа Скрипа, в дневник Чипуни ничего не записал.", 1)]


@pytest.mark.parametrize(
    ("text", "events"),
    [
        ("Скрипе дали 35мл лактата рингера", [water(35)]),
        ("Скрипа спит", []),
        ("Чипуне и Скрипе дали по 30 мл", []),
        ("дали 30 мл", []),
    ],
)
def test_no_notice_when_something_was_recorded_or_this_cat_is_named(chat, monkeypatch, text, events):
    assert receive(chat, 2, text, events, monkeypatch) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Чипуне дали 2 таблетки", profiles.CHIPUNYA),
        ("Скрипа поела 10 г", None),
        ("скрипит дверь, 2 раза", None),
    ],
)
def test_only_another_animal_named_by_its_name_counts(text, expected):
    assert profiles.named_instead(profiles.SKRIPA, text) is expected
