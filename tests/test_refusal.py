"""A refused food is recorded by name and never counted as eaten."""

import asyncio
import itertools
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import db, profiles, summary

BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 10, 5)
_message_ids = itertools.count(1)


def recorded(chat_id, hour, type, name=None, description="", kcal=None):
    event = SimpleNamespace(
        type=type, name=name, dose=None, water_ml=None, kcal=kcal, feeding="self",
        amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
        description=description,
    )
    sent_at = datetime(2026, 10, 5, hour, 0, tzinfo=BERLIN)
    db.save_message(chat_id, next(_message_ids), "owner", sent_at, "запись", [event])


def test_the_day_lists_what_he_would_not_eat(chat):
    recorded(chat, 9, "refusal", "royal canin urinary care", "отказался от Urinary Care")
    recorded(chat, 12, "refusal", None, "отказался от корма")
    recorded(chat, 13, "food", "felix sauce", "выпил весь пакетик соуса Felix", kcal=10.0)
    events = db.events_for_day(chat, DAY)

    text = asyncio.run(summary.render_summary(DAY, events, profiles.CHIPUNYA, complete=False))

    lines = text.splitlines()
    start = lines.index("🚫 Не стал есть:")
    assert lines[start + 1 : start + 3] == [
        "  09:00 — royal canin urinary care",
        "  12:00 — отказался от корма",
    ]
    assert summary.kcal_total(events) == 10.0
