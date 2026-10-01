"""Admin API: every request needs the token, every change leaves a record."""

import itertools
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from skrypka_bot import api, db

BERLIN = ZoneInfo("Europe/Berlin")
TOKEN = "t" * 40
DAY_SENT = datetime(2026, 9, 25, 12, 0, tzinfo=BERLIN)
_message_ids = itertools.count(1)


@pytest.fixture
def client(chat, monkeypatch):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    return TestClient(api.app, headers={"Authorization": f"Bearer {TOKEN}"})


def saved(chat_id, type, sent_at=DAY_SENT, text="запись", **fields):
    base = dict(type=type, name=None, dose=None, water_ml=None, kcal=None, feeding=None,
                amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                description="")
    event = SimpleNamespace(**{**base, **fields})
    db.save_message(chat_id, next(_message_ids), "owner", sent_at, text, [event])
    with sqlite3.connect(db.DB_PATH) as conn:
        return conn.execute("SELECT max(id) FROM events").fetchone()[0]


def test_the_list_defaults_to_todays_care_day(chat, client):
    now = datetime.now(BERLIN)
    today_id = saved(chat, "water", sent_at=now, water_ml=10.0, description="попил")
    saved(chat, "water", sent_at=now - timedelta(days=2), water_ml=20.0, description="раньше")
    assert [row["id"] for row in client.get("/events").json()] == [today_id]


def test_the_list_filters_by_subject_and_day(chat, client):
    event_id = saved(chat, "food", kcal=10.0, amount_ml=12.0, description="съел 12 г")
    assert client.get("/events", params={"subject": "skripa", "day": "2026-09-25"}).json() == []
    response = client.get("/events", params={"subject": "chipunya", "day": "2026-09-25"})
    assert response.json() == [
        {
            "id": event_id,
            "occurred_at": "2026-09-25T12:00:00+02:00",
            "type": "food",
            "description": "съел 12 г",
            "kcal": 10.0,
            "water_ml": None,
            "amount_ml": 12.0,
        }
    ]


def test_a_missing_event_is_not_found(chat, client):
    response = client.get("/events/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "event 999 not found"}


def test_one_event_carries_the_message_it_came_from(chat, client):
    event_id = saved(chat, "food", text="съел 12 г Sensory Smell", kcal=10.2)
    body = client.get(f"/events/{event_id}").json()
    assert body["message_text"] == "съел 12 г Sensory Smell"
    assert body["subject"] == "chipunya"
    assert body["day"] == "2026-09-25"


def test_patch_sets_and_clears_one_field(chat, client):
    event_id = saved(chat, "food", kcal=10.0, description="съел")
    assert client.patch(f"/events/{event_id}", json={"kcal": 12.5}).json()["kcal"] == 12.5
    body = client.patch(f"/events/{event_id}", json={"kcal": None}).json()
    assert body["kcal"] is None
    assert body["description"] == "съел"


def test_moving_an_event_recomputes_its_care_day(chat, client, monkeypatch):
    monkeypatch.setattr(db, "_DAY_START_HOUR", 11)
    event_id = saved(chat, "toilet", description="пописал")
    body = client.patch(
        f"/events/{event_id}", json={"occurred_at": "2026-09-26T09:00:00+02:00"}
    ).json()
    assert (body["occurred_at"], body["day"]) == ("2026-09-26T09:00:00+02:00", "2026-09-25")
    body = client.patch(f"/events/{event_id}", json={"occurred_at": "2026-09-26T12:00:00"}).json()
    assert (body["occurred_at"], body["day"]) == ("2026-09-26T12:00:00+02:00", "2026-09-26")


def test_liquid_is_stored_the_way_the_bot_stores_it(chat, client):
    event_id = saved(chat, "food", description="сухарики")
    assert client.patch(f"/events/{event_id}", json={"liquid": True}).json()["liquid"] is True
    client.patch(f"/events/{event_id}", json={"liquid": False})
    with sqlite3.connect(db.DB_PATH) as conn:
        assert conn.execute("SELECT liquid FROM events WHERE id = ?", (event_id,)).fetchone() == (None,)


@pytest.mark.parametrize("body", [{"kcall": 5}, {"kcal": "ten"}, {}, {"occurred_at": None}])
def test_a_bad_patch_is_refused(chat, client, body):
    event_id = saved(chat, "food", kcal=10.0)
    assert client.patch(f"/events/{event_id}", json=body).status_code == 422
    assert client.get(f"/events/{event_id}").json()["kcal"] == 10.0


def test_patching_a_missing_event_is_not_found(chat, client):
    response = client.patch("/events/999", json={"kcal": 1})
    assert response.status_code == 404
    assert response.json() == {"detail": "event 999 not found"}


def test_delete_needs_confirmation(chat, client):
    event_id = saved(chat, "food", kcal=10.0)
    response = client.delete(f"/events/{event_id}")
    assert response.status_code == 400
    assert response.json() == {"detail": f"add ?confirm=true to delete event {event_id}"}
    assert client.get(f"/events/{event_id}").status_code == 200


def test_a_confirmed_delete_removes_the_event(chat, client):
    event_id = saved(chat, "food", kcal=10.0, description="дубль")
    response = client.delete(f"/events/{event_id}", params={"confirm": "true"})
    assert response.json()["description"] == "дубль"
    assert client.get(f"/events/{event_id}").status_code == 404


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {TOKEN}"}])
def test_every_route_refuses_a_request_without_the_token(chat, monkeypatch, headers):
    monkeypatch.setenv("API_TOKEN", TOKEN)
    event_id = saved(chat, "food", kcal=10.0)
    anonymous = TestClient(api.app, headers=headers)
    calls = [
        lambda: anonymous.get("/events"),
        lambda: anonymous.get(f"/events/{event_id}"),
        lambda: anonymous.patch(f"/events/{event_id}", json={"kcal": 1}),
        lambda: anonymous.delete(f"/events/{event_id}", params={"confirm": "true"}),
        lambda: anonymous.get(f"/events/{event_id}/edits"),
    ]
    for call in calls:
        response = call()
        assert (response.status_code, response.json()) == (401, {"detail": "invalid or missing token"})
    assert db.event_by_id(event_id)["kcal"] == 10.0


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_the_schema_pages_are_not_served(chat, client, path):
    assert client.get(path).status_code == 404


def test_an_unset_server_token_refuses_everyone(chat, monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    response = TestClient(api.app, headers={"Authorization": "Bearer "}).get("/events")
    assert response.status_code == 401


@pytest.mark.parametrize("token", [None, "", "short"])
def test_the_server_will_not_start_without_a_strong_token(monkeypatch, token):
    if token is None:
        monkeypatch.delenv("API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("API_TOKEN", token)
    started = []
    monkeypatch.setattr(api.uvicorn, "run", lambda *args, **kwargs: started.append(True))
    with pytest.raises(SystemExit, match="API_TOKEN must be set to at least 32 characters"):
        api.main()
    assert not started


def test_a_patch_records_old_and_new_values(chat, client):
    event_id = saved(chat, "food", kcal=10.0, description="съел")
    client.patch(f"/events/{event_id}", json={"kcal": 12.5, "description": "съел"})
    edits = client.get(f"/events/{event_id}/edits").json()
    assert [(e["action"], e["before"], e["after"]) for e in edits] == [
        ("update", {"kcal": 10.0}, {"kcal": 12.5})
    ]


def test_a_patch_that_changes_nothing_records_nothing(chat, client):
    event_id = saved(chat, "food", kcal=10.0)
    client.patch(f"/events/{event_id}", json={"kcal": 10.0})
    assert client.get(f"/events/{event_id}/edits").json() == []


def test_a_delete_keeps_the_whole_row_in_the_history(chat, client):
    event_id = saved(chat, "food", kcal=10.0, description="дубль")
    deleted = client.delete(f"/events/{event_id}", params={"confirm": "true"}).json()
    [edit] = client.get(f"/events/{event_id}/edits").json()
    expected = {key: value for key, value in deleted.items() if key != "message_text"}
    assert (edit["action"], edit["before"], edit["after"]) == ("delete", expected, None)
