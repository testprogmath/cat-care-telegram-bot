"""When an event happened, from the time and day the message names."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import ingest

BERLIN = ZoneInfo("Europe/Berlin")
SENT = datetime(2026, 10, 6, 22, 45, tzinfo=BERLIN)


@pytest.mark.parametrize(
    ("fields", "sent", "expected"),
    [
        ({"date": "04.10", "time": "23:30"}, SENT, datetime(2026, 10, 4, 23, 30, tzinfo=BERLIN)),
        ({"days_ago": 1, "time": "10:00"}, SENT, datetime(2026, 10, 5, 10, 0, tzinfo=BERLIN)),
        ({"days_ago": 2}, SENT, datetime(2026, 10, 4, 22, 45, tzinfo=BERLIN)),
        ({"time": "23:30"}, SENT, datetime(2026, 10, 5, 23, 30, tzinfo=BERLIN)),
        ({"time": "21:00"}, SENT, datetime(2026, 10, 6, 21, 0, tzinfo=BERLIN)),
        ({}, SENT, SENT),
        ({"date": "31.12", "time": "23:00"}, datetime(2027, 1, 2, 9, 0, tzinfo=BERLIN),
         datetime(2026, 12, 31, 23, 0, tzinfo=BERLIN)),
        ({"date": "10.10", "time": "09:00"}, SENT, datetime(2026, 10, 6, 9, 0, tzinfo=BERLIN)),
        ({"date": "31.02"}, SENT, SENT),
    ],
    ids=["named date", "yesterday", "day before without time", "late hour means yesterday",
         "earlier today", "nothing named", "across new year", "future date is ignored", "impossible date"],
)
def test_the_event_lands_on_the_day_the_message_names(fields, sent, expected):
    event = SimpleNamespace(**{"time": None, "date": None, "days_ago": None, **fields})
    assert ingest._event_time(sent, event) == expected


@pytest.mark.parametrize(
    ("text", "fields", "retold"),
    [
        ("вчера дала серению", {"days_ago": 1}, True),
        ("04.10 дала миратаз", {"date": "04.10"}, True),
        ("вчера в 23:30 дала серению 6 мг", {"days_ago": 1, "time": "23:30"}, False),
        ("забыла написать: вчера дала серению 6 мг", {"days_ago": 1}, False),
        ("вчера не записали серению", {"days_ago": 1}, False),
        ("дала серению", {}, False),
    ],
    ids=["told", "told with a date", "with its time", "said to be missed", "said not written", "today"],
)
def test_a_past_dose_is_an_entry_only_with_its_time_or_a_missed_entry(text, fields, retold):
    event = SimpleNamespace(**{"type": "medication", "time": None, "date": None, "days_ago": None, **fields})
    assert ingest.is_retold_past_dose(event, text) is retold
