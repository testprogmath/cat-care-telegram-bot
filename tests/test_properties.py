"""Properties that must hold for every input, checked on inputs Hypothesis chooses."""

import contextlib
import pathlib
import sqlite3
import tempfile
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from conftest import animal
from hypothesis import given
from hypothesis import strategies as st

from skrypka_bot import care_export, db, ingest, parser

BERLIN = ZoneInfo("Europe/Berlin")
DAYS = st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31))
# 02:00-03:00 is skipped or repeated on the nights the clocks change, so a boundary
# inside that hour has no single meaning there; the bot uses 00:00.
BOUNDARIES = st.tuples(st.integers(0, 23).filter(lambda h: h != 2), st.integers(0, 59))


@contextlib.contextmanager
def boundary(hour: int, minute: int):
    saved = db._DAY_START_HOUR, db._DAY_START_MINUTE
    db._DAY_START_HOUR, db._DAY_START_MINUTE = hour, minute
    try:
        yield
    finally:
        db._DAY_START_HOUR, db._DAY_START_MINUTE = saved


@given(DAYS, BOUNDARIES, st.floats(0, 1, exclude_max=True))
def test_every_instant_in_a_care_days_window_belongs_to_that_day(day, start_at, fraction):
    with boundary(*start_at):
        start, end = care_export.window_of(day, BERLIN)
        span = end.astimezone(UTC) - start.astimezone(UTC)
        instant = (start.astimezone(UTC) + span * fraction).astimezone(BERLIN)
        assert db.care_day(instant) == day


@given(st.datetimes(min_value=datetime(2024, 1, 1), max_value=datetime(2030, 12, 31)),
       st.timedeltas(min_value=timedelta(0), max_value=timedelta(days=3)), BOUNDARIES)
def test_a_later_instant_never_falls_on_an_earlier_care_day(moment, gap, start_at):
    earlier = moment.replace(tzinfo=UTC)
    with boundary(*start_at):
        assert db.care_day(earlier) <= db.care_day(earlier + gap)


@given(st.floats(0, 3600), st.floats(0.05, 1))
def test_seconds_of_drinking_round_to_the_nearest_half_millilitre(seconds, rate):
    ml = parser.drunk_ml(animal(drinking_ml_per_second=rate), seconds)
    assert (ml * 2).is_integer()
    assert abs(ml - seconds * rate) <= 0.25 + 1e-9


@contextlib.contextmanager
def diary():
    saved = db.DB_PATH
    with tempfile.TemporaryDirectory() as folder:
        db.DB_PATH = pathlib.Path(folder) / "test.db"
        db.init()
        db.upsert_chat(-1, "Чипуня")
        try:
            yield
        finally:
            db.DB_PATH = saved


def toilet(description):
    return SimpleNamespace(type="toilet", name=None, dose=None, water_ml=None, kcal=None, feeding=None,
                           amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                           description=description)


def visits():
    with sqlite3.connect(db.DB_PATH) as conn:
        return conn.execute("SELECT count(*) FROM events WHERE type = 'toilet'").fetchone()[0]


NOON = datetime(2026, 10, 6, 12, 0, tzinfo=BERLIN)


@given(st.integers(1, 6), st.integers(0, 4))
def test_visits_counted_in_one_message_are_all_kept_and_a_resend_adds_none(count, resends):
    with diary():
        events = [toilet(f"пописал ({k} из {count})") for k in range(1, count + 1)]
        for _ in range(resends + 1):
            ingest.save_message(-1, 1, "owner", NOON, "пописал", events)
        assert visits() == count


@given(st.integers(0, 299))
def test_the_same_visit_from_two_messages_within_five_minutes_counts_once(seconds_apart):
    with diary():
        ingest.save_message(-1, 1, "owner", NOON, "пописал", [toilet("пописал")])
        ingest.save_message(-1, 2, "owner", NOON + timedelta(seconds=seconds_apart), "пописал", [toilet("пописал")])
        assert visits() == 1


CLOCK_CHANGES = [datetime(2026, 3, 29, 1), datetime(2026, 10, 25, 1), datetime(2027, 3, 28, 1), datetime(2027, 10, 31, 1)]


@given(st.sampled_from(CLOCK_CHANGES), st.timedeltas(min_value=-timedelta(hours=3), max_value=timedelta(hours=3)),
       st.timedeltas(min_value=timedelta(0), max_value=timedelta(hours=3)), BOUNDARIES)
def test_the_nights_the_clocks_change_keep_the_care_days_in_order(change, offset, gap, start_at):
    earlier = (change + offset).replace(tzinfo=UTC)
    with boundary(*start_at):
        assert db.care_day(earlier) <= db.care_day(earlier + gap)
