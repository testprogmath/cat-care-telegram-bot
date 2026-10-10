"""Tube limits come from the animal's tube, not from which animal it is."""

import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import db

BERLIN = ZoneInfo("Europe/Berlin")
TUBE_CHAT = -2


def tube_feed(chat_id, message_id, ml):
    event = SimpleNamespace(type="food", name=None, dose=None, water_ml=None, kcal=ml, feeding="tube",
                            amount_ml=ml, temp_c=None, liquid=True, water_fraction=None, time=None,
                            description=f"дала {ml:g} мл через зонд")
    db.save_message(chat_id, message_id, "owner", datetime(2026, 10, 6, 12, message_id, tzinfo=BERLIN),
                    event.description, [event])


def stored(chat_id):
    with sqlite3.connect(db.DB_PATH) as conn:
        return [row[0] for row in conn.execute(
            "SELECT amount_ml FROM events WHERE chat_id = ? ORDER BY id", (chat_id,))]


def test_a_feed_above_the_tubes_limit_is_rejected_as_implausible(chat):
    db.set_profile(TUBE_CHAT, "skripa")
    tube_feed(TUBE_CHAT, 1, 60.0)
    tube_feed(TUBE_CHAT, 20, 120.0)
    assert stored(TUBE_CHAT) == [60.0]


def test_an_animal_without_a_tube_has_no_tube_limit_to_apply(chat):
    tube_feed(chat, 1, 120.0)
    assert stored(chat) == [120.0]
