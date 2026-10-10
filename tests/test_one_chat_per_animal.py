"""An animal's diary lives in exactly one chat, so no other chat can take it over."""

import asyncio
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from skrypka_bot import api, db, main

BERLIN = ZoneInfo("Europe/Berlin")
TOKEN = "t" * 40
OTHER = -9


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **_):
        self.sent.append(text)
        return SimpleNamespace(message_id=len(self.sent), date=datetime.now(BERLIN))


def profile_command(chat_id, *args):
    bot = Bot()
    asyncio.run(main.profile_command(SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id)),
                                     SimpleNamespace(bot=bot, args=list(args))))
    return bot.sent


@pytest.fixture
def admin(chat, monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    return TestClient(api.app, headers={"Authorization": f"Bearer {TOKEN}"})


def test_a_second_chat_cannot_claim_a_taken_animal(chat):
    assert profile_command(OTHER, "чипуня") == [
        "Дневник Чипуня уже ведётся в другом чате, второй чат я не завожу."
    ]
    assert db.profile_for(OTHER) is None
    assert db.profile_for(chat).key == "chipunya"


def test_a_free_animal_can_still_be_claimed(chat):
    assert profile_command(OTHER, "скрипа")[0].startswith("Готово")
    assert db.profile_for(OTHER).key == "skripa"


def test_a_title_naming_a_taken_animal_does_not_assign_it(chat):
    assert db.upsert_chat(OTHER, "Чипуня и врачи") is None
    assert db.profile_for(OTHER) is None


def test_the_database_itself_refuses_a_second_chat_for_one_animal(chat):
    with pytest.raises(sqlite3.IntegrityError), sqlite3.connect(db.DB_PATH) as conn:
        conn.execute("INSERT INTO chats (chat_id, profile) VALUES (?, 'chipunya')", (OTHER,))


def test_chats_without_an_animal_do_not_collide(chat):
    db.upsert_chat(-10, "Ветклиника")
    db.upsert_chat(-11, "Соседи")
    db.init()
    assert db.profile_for(-10) is None and db.profile_for(-11) is None


def test_chats_from_before_profiles_existed_start_unassigned(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "old.db")
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.executescript(
            "CREATE TABLE chats (chat_id INTEGER PRIMARY KEY, title TEXT);"
            "INSERT INTO chats VALUES (-1, 'Чат один'), (-2, 'Чат два');"
        )
    db.init()
    assert db.profile_for(-1) is None and db.profile_for(-2) is None


def test_the_admin_api_moves_a_diary_by_freeing_the_old_chat_first(chat, admin):
    db.upsert_chat(OTHER, "Новый чат")
    assert admin.patch(f"/chats/{OTHER}", json={"profile": "chipunya"}).status_code == 409
    assert admin.patch(f"/chats/{chat}", json={"profile": None}).json()["profile"] is None
    assert admin.patch(f"/chats/{OTHER}", json={"profile": "chipunya"}).json() == {
        "chat_id": OTHER, "title": "Новый чат", "profile": "chipunya",
    }
    assert [(row["chat_id"], row["profile"]) for row in admin.get("/chats").json()] == [
        (OTHER, "chipunya"), (chat, None),
    ]


def test_the_admin_api_rejects_an_unknown_animal_or_chat(chat, admin):
    assert admin.patch(f"/chats/{chat}", json={"profile": "kasya"}).status_code == 422
    assert admin.patch("/chats/-404", json={"profile": None}).status_code == 404
    assert TestClient(api.app).get("/chats").status_code == 401
