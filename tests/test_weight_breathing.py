"""Weight, breathing and who gave the water: stored, summarised, and reminded about."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import db, profiles, summary

BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 10, 6)


def record(chat_id, n, hour, **fields):
    event = dict(type="state", name=None, dose=None, water_ml=None, kcal=None, feeding=None,
                 amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                 description="запись")
    event.update(fields)
    sent = datetime(2026, 10, 6, hour, 0, tzinfo=BERLIN)
    db.save_message(chat_id, n, "owner", sent, "сообщение", [SimpleNamespace(**event)])


def test_the_new_fields_are_stored_and_summarised(chat):
    record(chat, 1, 8, type="weight", weight_kg=6.8, description="вес 6,8 кг")
    record(chat, 2, 9, type="breathing", breaths_per_min=32.0, asleep=True, description="дыхание во сне 32")
    record(chat, 3, 10, type="water", water_ml=13.5, feeding="self", description="пил 30 секунд")
    record(chat, 4, 11, type="water", water_ml=10.0, feeding="tube", description="промывка")
    events = db.events_for_day(chat, DAY)
    assert [(e["type"], e["weight_kg"], e["breaths"], e["asleep"]) for e in events[:2]] == [
        ("weight", 6.8, None, None), ("breathing", None, 32.0, 1),
    ]
    text = asyncio.run(summary.render_summary(DAY, events, profiles.CHIPUNYA, complete=False))
    lines = text.splitlines()
    assert "  пила сама 1 раз (13.5 мл), дали 10 мл" in lines
    assert "  10:00 — 13.5 мл (сама)" in lines and "  11:00 — 10 мл (дали)" in lines
    assert "  08:00 — 6.8 кг" in lines
    assert "  09:00 — 32 в минуту во сне — выше 30 во сне" in lines
    assert db.last_weight(chat) == (DAY, 6.8)


def test_the_weighing_reminder_waits_a_week():
    assert summary.weighing_reminder((date(2026, 10, 1), 7.6), date(2026, 10, 7)) is None
    assert summary.weighing_reminder((date(2026, 8, 25), 7.73), date(2026, 10, 7)) == (
        "⚖️ Последнее взвешивание 25.08, 7.73 кг — 43 дня назад. Пора взвесить."
    )
    assert summary.weighing_reminder(None, date(2026, 10, 7)).startswith("⚖️ Взвешиваний в дневнике ещё нет")
