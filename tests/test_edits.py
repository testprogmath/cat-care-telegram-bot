"""An edited message is parsed again and its events replace the ones from the first version."""

import asyncio
import json
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import db, messages

BERLIN = ZoneInfo("Europe/Berlin")
SENT = datetime(2026, 10, 12, 16, 54, tzinfo=BERLIN)


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **_):
        self.sent.append(text)
        return SimpleNamespace(message_id=100 + len(self.sent), date=datetime.now(BERLIN))


def soup(grams):
    return SimpleNamespace(type="food", name="felix soup", dose=None, water_ml=None, kcal=round(grams * 0.425, 1),
                           feeding="self", amount_ml=grams, temp_c=None, liquid=True, water_fraction=0.95,
                           time=None, description=f"съела {grams:g} г супчика")


@pytest.fixture
def parser(monkeypatch):
    answers = {}

    async def parse(text, *_args):
        answer = answers[text]
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(messages, "parse_message", parse)
    return answers


def send(chat_id, text, edited=False):
    bot = Bot()
    message = SimpleNamespace(message_id=7, text=text, caption=None, date=SENT,
                              from_user=SimpleNamespace(full_name="owner"), reply_to_message=None)
    update = SimpleNamespace(effective_message=message, edited_message=message if edited else None,
                             effective_chat=SimpleNamespace(id=chat_id, title="Чипуня", full_name="Чипуня"))
    asyncio.run(messages.handle_message(update, SimpleNamespace(bot=bot)))
    return bot.sent


def stored():
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        events = [(r["amount_ml"], r["kcal"]) for r in conn.execute("SELECT * FROM events WHERE message_id = 7")]
        message = conn.execute("SELECT text, parsed FROM messages WHERE message_id = 7").fetchone()
        edits = [(r["action"], json.loads(r["before"])["amount_ml"])
                 for r in conn.execute("SELECT * FROM event_edits WHERE action = 'reparse'")]
    return events, tuple(message), edits


def test_an_edit_replaces_the_first_versions_events_and_leaves_a_trace(chat, parser):
    parser["съела 31 г супчика"] = [soup(31.0)]
    parser["съела 41 г супчика"] = [soup(41.0)]
    send(chat, "съела 31 г супчика")
    sent = send(chat, "съела 41 г супчика", edited=True)
    assert stored() == ([(41.0, 17.4)], ("съела 41 г супчика", 1), [("reparse", 31.0)])
    assert len(sent) == 1 and sent[0].startswith("📈 Чипуня")


def test_an_edit_that_cannot_be_parsed_keeps_the_old_events(chat, parser):
    parser["съела 31 г супчика"] = [soup(31.0)]
    parser["съела 41 г"] = messages.ParseFailed("timeout")
    send(chat, "съела 31 г супчика")
    send(chat, "съела 41 г", edited=True)
    assert stored() == ([(31.0, 13.2)], ("съела 31 г супчика", 1), [])


def test_an_edit_of_a_message_waiting_for_retry_is_parsed_once(chat, parser):
    parser["съела 31 г супчика"] = messages.ParseFailed("timeout")
    parser["съела 41 г супчика"] = [soup(41.0)]
    send(chat, "съела 31 г супчика")
    send(chat, "съела 41 г супчика", edited=True)
    assert stored()[:2] == ([(41.0, 17.4)], ("съела 41 г супчика", 1))
    assert not db.unparsed_messages()


def test_an_edit_that_changes_no_figure_sends_no_second_progress(chat, parser):
    parser["съела 31 г супчика"] = [soup(31.0)]
    parser["съела 31 г супчика!"] = [soup(31.0)]
    send(chat, "съела 31 г супчика")
    assert send(chat, "съела 31 г супчика!", edited=True) == []
