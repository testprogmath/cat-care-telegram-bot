"""Which animal an event belongs to must survive a later profile change."""

import sqlite3
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest

from skrypka_bot import db, profiles


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init()
    return db.DB_PATH


def food(description="съел 5 г сухариков", **overrides):
    event = dict(type="food", name=None, dose=None, water_ml=None, kcal=18.5, feeding="self",
                 amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                 description=description)
    return SimpleNamespace(**{**event, **overrides})


def subjects(chat_id=None):
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT subject FROM events" + (" WHERE chat_id = ?" if chat_id else "")
        return [r["subject"] for r in conn.execute(sql, (chat_id,) if chat_id else ())]


def test_new_event_records_its_subject(fresh_db):
    db.upsert_chat(-1, "Чипуня")
    db.save_message(-1, 1, "owner", datetime(2026, 9, 25, 12, 0), "съел 5 г сухариков", [food()])
    assert subjects() == ["chipunya"]


def test_two_chats_keep_separate_subjects(fresh_db):
    db.upsert_chat(-1, "Чипуня")
    db.upsert_chat(-2, "Скрипа")
    db.save_message(-1, 1, "owner", datetime(2026, 9, 25, 12, 0), "съел 5 г", [food()])
    db.save_message(-2, 2, "owner", datetime(2026, 9, 25, 12, 0), "съела 5 г", [food("съела 5 г")])
    assert subjects(-1) == ["chipunya"] and subjects(-2) == ["skripa"]


def test_a_later_profile_change_does_not_rewrite_past_events(fresh_db):
    """The point of storing the subject: history keeps the animal it was recorded for."""
    db.upsert_chat(-1, "Чипуня")
    db.save_message(-1, 1, "owner", datetime(2026, 9, 25, 12, 0), "съел 5 г", [food()])
    db.set_profile(-1, "skripa")
    db.save_message(-1, 2, "owner", datetime(2026, 9, 25, 13, 0), "съела 6 г", [food("съела 6 г")])
    assert subjects(-1) == ["chipunya", "skripa"]


def test_migration_backfills_existing_rows(tmp_path, monkeypatch):
    """A database written before the column exists still gets a subject for every row."""
    path = tmp_path / "old.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE chats (chat_id INTEGER PRIMARY KEY, title TEXT, profile TEXT);
            CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                                 message_id INTEGER, occurred_at TEXT NOT NULL, day TEXT NOT NULL,
                                 type TEXT NOT NULL, name TEXT, dose TEXT, water_ml REAL, description TEXT);
            INSERT INTO chats VALUES (-1, 'Чипуня', 'chipunya'), (-2, 'Скрипа', 'skripa');
            INSERT INTO events (chat_id, occurred_at, day, type) VALUES
                (-1, '2026-09-25T12:00', '2026-09-25', 'food'),
                (-2, '2026-09-25T12:00', '2026-09-25', 'water');
            """
        )
    db.init()
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = {r["chat_id"]: r["subject"] for r in conn.execute("SELECT chat_id, subject FROM events")}
    assert rows == {-1: "chipunya", -2: "skripa"}


def test_migration_runs_once_and_leaves_later_rows_alone(fresh_db):
    """init() runs on every start; a second run must not restamp anything."""
    db.upsert_chat(-1, "Чипуня")
    db.save_message(-1, 1, "owner", datetime(2026, 9, 25, 12, 0), "съел 5 г", [food()])
    db.set_profile(-1, "skripa")
    db.init()
    assert subjects(-1) == ["chipunya"]


CONTRACTED_SUBJECT_IDS = {"skripa", "chipunya"}


def test_subject_ids_are_frozen():
    """These strings live in stored events and in downstream systems' own records.

    Changing one is a migration on both sides. If this test fails because a profile was
    renamed, the rename belongs on Profile.key, which nothing outside cat-care reads.
    """
    assert {p.subject_id for p in profiles.PROFILES.values()} == CONTRACTED_SUBJECT_IDS


def test_renaming_a_profile_key_does_not_change_stored_identity(fresh_db, monkeypatch):
    renamed = replace(profiles.CHIPUNYA, key="cat_two")
    monkeypatch.setattr(profiles, "PROFILES", {**profiles.PROFILES, "cat_two": renamed})
    monkeypatch.setattr(profiles, "CHIPUNYA", renamed)
    db.upsert_chat(-1, "Чипуня")
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.execute("UPDATE chats SET profile = 'cat_two' WHERE chat_id = -1")
    db.save_message(-1, 99, "owner", datetime(2026, 9, 25, 12, 0), "съел 5 г", [food()])
    assert subjects(-1) == ["chipunya"]


def test_subject_id_is_what_gets_stored_not_the_key(fresh_db, monkeypatch):
    """The two hold the same string today. The column must follow subject_id anyway."""
    diverged = replace(profiles.CHIPUNYA, subject_id="chipunya-2019")
    monkeypatch.setattr(profiles, "PROFILES", {**profiles.PROFILES, "chipunya": diverged})
    db.upsert_chat(-1, "Чипуня")
    db.save_message(-1, 98, "owner", datetime(2026, 9, 25, 12, 0), "съел 5 г", [food()])
    assert subjects(-1) == ["chipunya-2019"]
