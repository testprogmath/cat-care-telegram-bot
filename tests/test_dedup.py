"""A repeated report replaces or yields to what is stored, and every replacement leaves a trace."""

import json
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import db

BERLIN = ZoneInfo("Europe/Berlin")
NOON = datetime(2026, 10, 6, 12, 0, tzinfo=BERLIN)


def event(type, description, **fields):
    base = dict(type=type, name=None, dose=None, water_ml=None, kcal=None, feeding=None,
                amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                description=description)
    return SimpleNamespace(**{**base, **fields})


def message(chat_id, message_id, text, *events, minute=0):
    db.save_message(chat_id, message_id, "owner", NOON.replace(minute=minute), text, list(events))


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
