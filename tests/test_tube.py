"""Tube limits come from the animal's tube, not from which animal it is."""

import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from conftest import animal

from skrypka_bot import db, profiles
from skrypka_bot.profiles import Tube

BERLIN = ZoneInfo("Europe/Berlin")
WITH_TUBE, WITHOUT_TUBE = -2, -3


@pytest.fixture
def animals(chat, monkeypatch):
    tubed = animal("tubed", tube=Tube(water_portion_ml=25.0, max_feed_ml=100.0))
    untubed = animal("untubed")
    monkeypatch.setattr(profiles, "PROFILES", {**profiles.PROFILES, "tubed": tubed, "untubed": untubed})
    db.set_profile(WITH_TUBE, "tubed")
    db.set_profile(WITHOUT_TUBE, "untubed")


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


def test_a_feed_above_the_tubes_limit_is_rejected_as_implausible(animals):
    tube_feed(WITH_TUBE, 1, 60.0)
    tube_feed(WITH_TUBE, 20, 120.0)
    assert stored(WITH_TUBE) == [60.0]


def test_an_animal_without_a_tube_has_no_tube_limit_to_apply(animals):
    tube_feed(WITHOUT_TUBE, 1, 120.0)
    assert stored(WITHOUT_TUBE) == [120.0]
