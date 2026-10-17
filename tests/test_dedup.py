"""A repeated report replaces or yields to what is stored, and every replacement leaves a trace."""

import json
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import db, ingest

BERLIN = ZoneInfo("Europe/Berlin")
NOON = datetime(2026, 10, 6, 12, 0, tzinfo=BERLIN)


def event(type, description, **fields):
    base = dict(type=type, name=None, dose=None, water_ml=None, kcal=None, feeding=None,
                amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                description=description)
    return SimpleNamespace(**{**base, **fields})


def message(chat_id, message_id, text, *events, minute=0):
    ingest.save_message(chat_id, message_id, "owner", NOON.replace(minute=minute), text, list(events))


def manual(chat_id, type, description, **fields):
    return db.create_event(chat_id, "chipunya", {
        "type": type, "description": description, "occurred_at": NOON.isoformat(),
        "day": NOON.date().isoformat(), **fields,
    }, NOON)["id"]


def stored(type):
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [(r["id"], r["description"]) for r in conn.execute(
            "SELECT id, description FROM events WHERE type = ? ORDER BY id", (type,))]


def dedup_edits():
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [(r["event_id"], json.loads(r["before"])["description"], json.loads(r["after"]))
                for r in conn.execute("SELECT * FROM event_edits WHERE action = 'dedup' ORDER BY id")]


def test_a_more_detailed_feeding_replaces_the_first_and_the_replacement_is_logged(chat):
    message(chat, 1, "поел", event("food", "поел", feeding="self"))
    [(first, _)] = stored("food")
    message(chat, 2, "съел 5 г, 18 ккал", event("food", "съел 5 г", kcal=18.0, feeding="self"), minute=2)
    assert [description for _, description in stored("food")] == ["съел 5 г"]
    assert dedup_edits() == [(first, "поел", {"replaced_by": "съел 5 г"})]


def test_a_manually_added_feeding_is_never_replaced(chat):
    kept = manual(chat, "food", "дала 30 мл в зонд", kcal=20.7, feeding="tube", amount_ml=30.0, liquid=1)
    message(chat, 1, "30 мл в зонд, 20.7 ккал",
            event("food", "дала 30 мл trovet в зонд", kcal=20.7, feeding="tube", amount_ml=30.0, liquid=True),
            minute=1)
    assert stored("food") == [(kept, "дала 30 мл в зонд")]
    assert not dedup_edits()


def test_a_manually_added_toilet_visit_is_never_replaced(chat):
    kept = manual(chat, "toilet", "пописал")
    message(chat, 1, "пописал в лоток", event("toilet", "пописал в лоток, много"), minute=1)
    assert stored("toilet") == [(kept, "пописал")]
    assert not dedup_edits()


def test_a_replaced_medication_is_logged(chat):
    message(chat, 1, "дала серению", event("medication", "серения", name="серения"))
    [(first, _)] = stored("medication")
    message(chat, 2, "серения 6 мг", event("medication", "серения 6 мг", name="серения", dose="6 мг"), minute=3)
    assert [description for _, description in stored("medication")] == ["серения 6 мг"]
    assert dedup_edits() == [(first, "серения", {"replaced_by": "серения 6 мг"})]


def test_an_exact_amount_replaces_an_estimate_but_not_a_manual_record(chat):
    message(chat, 1, "немного попил", event("water", "немного попил", water_ml=2.0, feeding="self"))
    [(estimate, _)] = stored("water")
    kept = manual(chat, "water", "дала 5 мл", water_ml=5.0, feeding="tube")
    message(chat, 2, "попил 10 мл", event("water", "попил 10 мл", water_ml=10.0, feeding="self"), minute=1)
    assert [description for _, description in stored("water")] == ["дала 5 мл", "попил 10 мл"]
    assert kept in [event_id for event_id, _ in stored("water")]
    assert dedup_edits() == [(estimate, "немного попил", {"replaced_by": "попил 10 мл"})]


def test_two_flavours_of_the_same_size_eaten_one_after_the_other_are_two_feedings(chat):
    message(chat, 1, "курица", event("food", "снек с курицей", name="vitakraft с курицей", kcal=7.5,
                                     amount_ml=15.0, liquid=True))
    message(chat, 2, "говядина", event("food", "снек с говядиной", name="vitakraft с говядиной", kcal=7.5,
                                       amount_ml=15.0, liquid=True), minute=1)
    assert [description for _, description in stored("food")] == ["снек с курицей", "снек с говядиной"]


def test_the_same_product_named_more_or_less_fully_is_still_one_feeding(chat):
    message(chat, 1, "снек", event("food", "съел снек", name="vitakraft с говядиной", kcal=7.5,
                                   amount_ml=15.0, liquid=True))
    message(chat, 2, "тоже съел", event("food", "тоже съел снек", name="Vitakraft", kcal=7.5,
                                        amount_ml=15.0, liquid=True), minute=1)
    assert [description for _, description in stored("food")] == ["съел снек"]


def test_a_second_dry_portion_with_other_calories_is_a_second_feeding(chat):
    message(chat, 1, "29 сухариков", event("food", "съела 29 сухариков Purina One", name="purina one",
                                           kcal=13.4, liquid=False))
    message(chat, 2, "и ещё 18 Zalm", event("food", "съела 18 сухариков Purina One zalm",
                                            name="purina one zalm", kcal=11.6, liquid=False), minute=1)
    assert [description for _, description in stored("food")] == [
        "съела 29 сухариков Purina One", "съела 18 сухариков Purina One zalm",
    ]


def test_the_same_dry_portion_resent_is_still_one_feeding(chat):
    message(chat, 1, "29 сухариков", event("food", "съела 29 сухариков", name="purina one", kcal=13.4))
    message(chat, 2, "29 сухариков", event("food", "съела 29 сухариков", name="purina one", kcal=13.4), minute=1)
    assert len(stored("food")) == 1
