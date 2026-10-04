"""What /meds reports, for a week and for a period."""

import itertools
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import db, main, meds

BERLIN = ZoneInfo("Europe/Berlin")
TODAY = date(2026, 10, 4)
_message_ids = itertools.count(1)


def given(chat_id, day, hour, name, dose=None):
    event = SimpleNamespace(
        type="medication", name=name, dose=dose, water_ml=None, kcal=None, feeding=None,
        amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
        description=f"дала {name}",
    )
    sent_at = datetime(day.year, day.month, day.day, hour, 0, tzinfo=BERLIN)
    db.save_message(chat_id, next(_message_ids), "owner", sent_at, "запись", [event])


@pytest.mark.parametrize(
    ("raw", "shown"),
    [("6мг", "6 мг"), ("2,5 мг", "2.5 мг"), ("0,75 мл", "0.75 мл"),
     ("0.06 мг (0.2 мл)", "0.06 мг (0.2 мл)"), ("полтаблетки", "полтаблетки"), (None, None)],
)
def test_doses_are_shown_in_one_spelling(raw, shown):
    assert meds.normalise_dose(raw) == shown


def test_the_week_is_a_grid_of_doses_per_day(chat):
    given(chat, date(2026, 10, 1), 8, "бупренорфин", "0.06 мг (0.2 мл)")
    given(chat, date(2026, 10, 1), 20, "бупренорфин", "0.06 мг (0.2 мл)")
    given(chat, date(2026, 10, 3), 20, "серения", "6мг")
    given(chat, date(2026, 9, 27), 20, "серения", "8 мг")

    assert main.render_meds(chat, [], TODAY) == (
        "💊 Чипуня: лекарства 28.09–04.10\n"
        "<pre>            28 29 30 01 02 03 04\n"
        "серения      ·  ·  ·  ·  ·  1  ·\n"
        "бупренорфин  ·  ·  ·  2  ·  ·  ·</pre>\n"
        "Число в клетке: сколько раз дали за сутки, · не записано.\n\n"
        "серения (маропитант, таблетки): 6 мг ×1\n"
        "бупренорфин: 0.06 мг (0.2 мл) ×2"
    )


def test_all_covers_the_whole_diary_most_recent_drug_first_then_by_name(chat):
    given(chat, date(2026, 8, 4), 20, "марбоцил", "15 мг")
    given(chat, date(2026, 8, 5), 20, "марбоцил", "15 мг")
    given(chat, date(2026, 8, 5), 21, "превомакс", "0,75 мл")
    given(chat, date(2026, 10, 3), 20, "ондансетрон", "6 мг")
    given(chat, date(2026, 10, 3), 23, "ондансетрон", "4 мг")
    given(chat, date(2026, 10, 2), 20, "ондансетрон", "6 мг")
    given(chat, date(2026, 10, 2), 23, "ондансетрон")
    given(chat, date(2026, 9, 1), 20, None)

    assert main.render_meds(chat, ["all"], TODAY) == (
        "💊 Чипуня: лекарства 04.08–04.10 (62 дня)\n"
        "\n"
        "ондансетрон\n"
        "  4 приёма за 2 дня, 02.10–03.10\n"
        "  дозы: 6 мг ×2, 4 мг ×1, без дозы ×1\n"
        "\n"
        "марбоцил\n"
        "  2 приёма за 2 дня, 04.08–05.08\n"
        "  дозы: 15 мг ×2\n"
        "\n"
        "превомакс (маропитант, инъекция)\n"
        "  1 приём за 1 день, 05.08\n"
        "  дозы: 0.75 мл ×1\n"
        "\n"
        "не названо\n"
        "  1 приём за 1 день, 01.09\n"
        "  дозы: без дозы ×1"
    )


def test_a_period_leaves_out_days_outside_it(chat):
    given(chat, date(2026, 8, 31), 20, "серения", "8 мг")
    given(chat, date(2026, 9, 1), 20, "серения", "8 мг")
    given(chat, date(2026, 10, 1), 20, "серения", "8 мг")

    assert main.render_meds(chat, ["2026-09-01", "2026-09-30"], TODAY) == (
        "💊 Чипуня: лекарства 01.09–30.09 (30 дней)\n"
        "\n"
        "серения (маропитант, таблетки)\n"
        "  1 приём за 1 день, 01.09\n"
        "  дозы: 8 мг ×1"
    )


def test_an_empty_week_says_so(chat):
    assert main.render_meds(chat, [], TODAY) == (
        "💊 Чипуня: лекарства 28.09–04.10\nЗа эти дни лекарств не записано."
    )


@pytest.mark.parametrize(
    "args", [["week"], ["2026-09-01"], ["2026-09-30", "2026-09-01"], ["2026-09-01", "вчера"]]
)
def test_other_arguments_are_refused(chat, args):
    assert main.render_meds(chat, args, TODAY) is None
