"""Weight, appetite trend, treatment marks, before and after, stool and breathing."""

import itertools
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import db, views

BERLIN = ZoneInfo("Europe/Berlin")
_ids = itertools.count(1)


def record(chat_id, day, hour=12, **fields):
    event = dict(type="state", name=None, dose=None, water_ml=None, kcal=None, feeding=None,
                 amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                 description="запись")
    event.update(fields)
    sent = datetime(day.year, day.month, day.day, hour, 0, tzinfo=BERLIN)
    db.save_message(chat_id, next(_ids), "owner", sent, "сообщение", [SimpleNamespace(**event)])


def test_weight_reports_the_change_over_a_week_and_a_month_and_goes_stale(chat):
    record(chat, date(2026, 8, 25), type="weight", weight_kg=7.73)
    record(chat, date(2026, 9, 28), type="weight", weight_kg=7.60)
    record(chat, date(2026, 10, 6), type="weight", weight_kg=7.55)
    summary = views.weight_summary(chat, date(2026, 9, 7), date(2026, 10, 6), date(2026, 10, 14))
    assert (summary.last.kg, summary.previous.kg, summary.change_30) == (7.55, 7.60, -0.18)
    assert summary.stale and summary.days_ago == 8
    assert len(summary.points) == 2


def test_treatment_marks_are_starts_and_dose_changes_that_hold(chat):
    doses = ["6 мг", "6 мг", "4 мг", "6 мг", "4 мг", "4 мг", "4 мг", "4 мг"]
    for day, dose in enumerate(doses, start=1):
        record(chat, date(2026, 10, day), type="medication", name="ондансетрон", dose=dose)
    rows = db.medications_in_days(chat, date(2026, 1, 1), date(2026, 10, 9))
    assert [(m.day, m.label) for m in views.treatment_marks(rows)] == [
        (date(2026, 10, 1), "ондансетрон: начало, 6"),
        (date(2026, 10, 5), "ондансетрон: 6 → 4"),
    ]


def test_an_opening_dose_settled_in_the_first_days_is_the_start(chat):
    for day, dose in [(29, "2 мг"), (30, "2.5 мг")]:
        record(chat, date(2026, 9, day), type="medication", name="преднизолон", dose=dose)
    for day in range(1, 4):
        record(chat, date(2026, 10, day), type="medication", name="преднизолон", dose="2.5 мг")
    rows = db.medications_in_days(chat, date(2026, 1, 1), date(2026, 10, 6))
    assert [m.label for m in views.treatment_marks(rows)] == ["преднизолон: начало, 2.5"]


def test_changes_on_one_day_are_one_comparison():
    marks = [views.Mark(date(2026, 9, 25), "кротакс: начало"), views.Mark(date(2026, 9, 25), "серения: 8 → 6")]
    assert [(m.day, m.label) for m in views.same_day_marks(marks)] == [
        (date(2026, 9, 25), "кротакс: начало; серения: 8 → 6"),
    ]


def test_before_and_after_compares_seven_days_either_side(chat):
    for offset in range(1, 8):
        record(chat, date(2026, 9, 28) - timedelta(days=offset), type="food", feeding="self", kcal=70.0)
    for offset in range(0, 5):
        record(chat, date(2026, 9, 28) + timedelta(days=offset), type="food", feeding="self", kcal=90.0)
    mark = views.Mark(date(2026, 9, 28), "преднизолон: начало, 2")
    comparison = views.compare_around(chat, "chipunya", mark, date(2026, 10, 2))
    assert comparison.before == (date(2026, 9, 21), date(2026, 9, 27))
    assert comparison.after == (date(2026, 9, 28), date(2026, 10, 2))
    assert comparison.lines[0] == ("Ккал сама", "70", "90")


def test_before_and_after_waits_for_three_days_after(chat):
    record(chat, date(2026, 9, 27), type="food", feeding="self", kcal=70.0)
    record(chat, date(2026, 9, 28), type="food", feeding="self", kcal=90.0)
    mark = views.Mark(date(2026, 9, 28), "x")
    assert views.compare_around(chat, "chipunya", mark, date(2026, 9, 29)) is None


def test_the_appetite_trend_needs_four_recorded_days_in_the_window(chat):
    for offset in range(10):
        record(chat, date(2026, 9, 20) + timedelta(days=offset), type="food", feeding="self", kcal=100.0)
    rows = views.day_rows(chat, "chipunya", date(2026, 9, 20), date(2026, 9, 29))
    mark = views.Mark(date(2026, 9, 25), "серения: 8 → 6")
    trend = views.appetite_trend(rows, date(2026, 9, 20), date(2026, 9, 29), 250, [mark])
    assert len(trend.line.split()) == 7 and len(trend.bars) == 10
    assert (trend.latest_pct, trend.latest_kcal) == (40.0, 100.0)
    assert [(m.number, m.day) for m in trend.marks] == [(1, date(2026, 9, 25))]


def test_the_last_stool_ignores_urination(chat):
    record(chat, date(2026, 10, 3), type="toilet", description="покакал")
    record(chat, date(2026, 10, 5), type="toilet", description="пописал")
    assert views.last_stool(chat, date(2026, 10, 6)) == date(2026, 10, 3)


def test_breathing_above_thirty_is_flagged_only_in_sleep(chat):
    record(chat, date(2026, 10, 6), 9, type="breathing", breaths_per_min=32.0, asleep=True)
    record(chat, date(2026, 10, 6), 10, type="breathing", breaths_per_min=40.0, asleep=False)
    assert [(b.rate, b.high) for b in views.breathing(chat, date(2026, 10, 6), date(2026, 10, 6))] == [
        (40.0, False), (32.0, True),
    ]


def test_water_splits_into_drank_given_and_from_food():
    share = views.Share3.of((20.0, 100.0, 180.0), 340)
    assert share.widths == (5.9, 29.4, 52.9)
    assert share.starts == (0.0, 5.9, 35.3)
