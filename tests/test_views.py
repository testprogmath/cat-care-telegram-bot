"""What the web pages compute from diary rows."""

import itertools
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import db, foods, views

BERLIN = ZoneInfo("Europe/Berlin")
_ids = itertools.count(1)


def record(chat_id, day, hour, **fields):
    event = dict(type="medication", name=None, dose=None, water_ml=None, kcal=None, feeding=None,
                 amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                 description="запись")
    event.update(fields)
    sent = datetime(day.year, day.month, day.day, hour, 0, tzinfo=BERLIN)
    db.save_message(chat_id, next(_ids), "owner", sent, "сообщение", [SimpleNamespace(**event)])


def test_a_course_given_lately_is_current_with_its_dose_since_and_gaps(chat):
    for day, dose in [(1, "6 мг"), (2, "6 мг"), (4, "4 мг"), (5, "4 мг")]:
        record(chat, date(2026, 10, day), 20, name="ондансетрон", dose=dose)
    record(chat, date(2026, 9, 2), 20, name="марбоцил", dose="15 мг")
    rows = db.medications_in_days(chat, date(2026, 9, 1), date(2026, 10, 5))
    current, finished = views.courses(rows, date(2026, 9, 1), date(2026, 10, 5))
    [course] = current
    assert (course.label, course.dose, course.since) == ("ондансетрон", "4 мг", date(2026, 10, 4))
    assert course.gaps == ["03.10"]
    assert [cell.shade for cell in course.cells] == ["#3FA796", "#3FA796", "#9ED6CC", "#9ED6CC"]
    assert [(f.label, f.doses) for f in finished] == [("марбоцил", "15 мг ×1")]


def test_foods_split_into_eating_stopped_and_never():
    lines = [
        foods.FoodLine("Felix Sauce", eaten=3, kcal=30, last_eaten=date(2026, 10, 5)),
        foods.FoodLine("RC Kitten", eaten=9, kcal=200, last_eaten=date(2026, 9, 20)),
        foods.FoodLine("RC Urinary", refused=1, last_refused=date(2026, 10, 5)),
    ]
    groups = views.food_groups(lines, date(2026, 10, 6))
    assert [(g.title, [line.product for line in g.lines]) for g in groups] == [
        ("Ест · за последние 7 дней", ["Felix Sauce"]),
        ("Давно не ест", ["RC Kitten"]),
        ("Не ест вовсе", ["RC Urinary"]),
    ]


def test_refusals_without_a_named_food_count_as_unknown(chat):
    record(chat, date(2026, 10, 5), 9, type="refusal", description="не стала есть")
    record(chat, date(2026, 10, 5), 10, type="refusal", name="сухарики, снек", description="от сухариков и снэка")
    rows = db.events_with_messages(chat, date(2026, 10, 5), date(2026, 10, 5))
    top, days = views.refusal_summary(rows)
    assert dict(top) == {foods.UNNAMED: 1, foods.UNNAMED_DRY: 1, foods.UNNAMED_SNACK: 1}
    assert [item.tags for item in days[0].items] == [[foods.UNNAMED_DRY, foods.UNNAMED_SNACK], [foods.UNNAMED]]


def test_the_day_groups_water_and_filters_by_kind(chat):
    record(chat, date(2026, 10, 5), 9, type="water", water_ml=10.0)
    record(chat, date(2026, 10, 5), 10, type="water", water_ml=13.0)
    record(chat, date(2026, 10, 5), 11, type="food", feeding="tube", name="royal canin recovery liquid",
           kcal=23.0, amount_ml=23.0)
    record(chat, date(2026, 10, 5), 20, name="серения", dose="6мг")
    rows = db.events_with_messages(chat, date(2026, 10, 5), date(2026, 10, 5))
    events, water = views.day_events(rows, None)
    assert [(e.kind, e.title, e.amount) for e in events] == [
        ("еда · зонд", "RC Recovery Liquid, 23 мл", "23 ккал"),
        ("лекарство", "серения 6 мг", ""),
    ]
    assert (water.count, water.ml) == (2, 23.0)
    events, water = views.day_events(rows, "meds")
    assert [e.title for e in events] == ["серения 6 мг"] and water is None


def test_the_mini_chart_is_left_out_past_a_month():
    row = SimpleNamespace(kcal=100.0, kcal_tube=60.0, kcal_self=40.0, day=date(2026, 10, 1),
                          urinations=3, stools=None)
    assert views.mini_chart([row] * 31, 250) is not None
    assert views.mini_chart([row] * 32, 250) is None


def test_the_day_clock_places_each_event_on_its_hour(chat):
    record(chat, date(2026, 10, 5), 6, type="food", feeding="tube", kcal=50.0, amount_ml=50.0, liquid=True,
           water_fraction=0.8, description="зонд")
    record(chat, date(2026, 10, 5), 12, type="food", feeding="self", kcal=75.0, description="поела")
    record(chat, date(2026, 10, 5), 12, type="toilet", description="покакала")
    record(chat, date(2026, 10, 5), 18, type="toilet", description="пыталась пописать, не получилось")
    record(chat, date(2026, 10, 5), 20, name="серения", dose="6 мг")
    rows = db.events_with_messages(chat, date(2026, 10, 5), date(2026, 10, 5))
    clock = views.day_clock(rows, date(2026, 10, 5), 250, 340, datetime(2026, 10, 7, 9, tzinfo=BERLIN))
    assert clock.kcal_pct == 50.0 and round(clock.water_pct, 1) == 11.8
    assert [(m.x, m.shape, m.tone) for m in clock.marks] == [
        (88.5, "circle", "tube"), (137.0, "circle", "self"), (137.0, "square", "stool"),
        (185.5, "ring", "toilet"), (201.7, "diamond", "meds"),
    ]
    assert clock.kcal_line.split()[-1] == f"234.0,{clock.y(50)}"
    assert [label for _, label in clock.ticks] == ["00:00", "06:00", "12:00", "18:00", "00:00"]


def test_today_stops_the_lines_at_now(chat):
    record(chat, date(2026, 10, 5), 6, type="food", feeding="self", kcal=25.0, description="поела")
    rows = db.events_with_messages(chat, date(2026, 10, 5), date(2026, 10, 5))
    clock = views.day_clock(rows, date(2026, 10, 5), 250, 340, datetime(2026, 10, 5, 12, tzinfo=BERLIN))
    assert clock.kcal_line.split()[-1] == f"137.0,{clock.y(10)}"


def test_a_day_with_only_notes_has_no_clock(chat):
    record(chat, date(2026, 10, 5), 9, type="state", description="спит")
    rows = db.events_with_messages(chat, date(2026, 10, 5), date(2026, 10, 5))
    assert views.day_clock(rows, date(2026, 10, 5), 250, 340, datetime(2026, 10, 7, tzinfo=BERLIN)) is None


def test_the_legend_lists_only_the_marks_the_day_has(chat):
    record(chat, date(2026, 10, 5), 6, type="food", feeding="tube", kcal=50.0, description="зонд")
    record(chat, date(2026, 10, 5), 7, type="water", feeding="tube", water_ml=15.0, description="промыли зонд")
    record(chat, date(2026, 10, 5), 12, type="toilet", description="пописала")
    rows = db.events_with_messages(chat, date(2026, 10, 5), date(2026, 10, 5))
    clock = views.day_clock(rows, date(2026, 10, 5), 250, 340, datetime(2026, 10, 7, tzinfo=BERLIN))
    legend = views.clock_legend(clock, "сама", "пила сама")
    assert [(name, [(i.shape, i.tone, i.label) for i in items]) for name, items in legend] == [
        ("Еда", [("circle", "tube", "зонд")]),
        ("Вода", [("ring", "drink", "дали в зонд")]),
        ("Туалет", [("circle", "toilet", "моча")]),
    ]
