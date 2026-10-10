"""The water reminder says how far behind the even daily schedule the animal is."""

from dataclasses import replace
from datetime import datetime

from skrypka_bot import main, profiles

CAT = replace(profiles.CHIPUNYA, water_goal_ml=280.0)


def test_behind_schedule_the_reminder_states_the_expected_amount_and_the_gap():
    assert main.render_water_reminder(CAT, 100.0, datetime(2026, 10, 10, 16, 0)) == (
        "💧 Напоминание: Чипуня получил 100 мл воды из 280 (осталось 180).\n"
        "К 16:00 по графику должно быть ~140 мл, не хватает ~40 мл "
        "(график: 280 мл равномерно с 09:00 до 23:00). Пора дать ~15-20 мл."
    )


def test_within_the_buffer_of_the_schedule_there_is_no_reminder():
    assert main.render_water_reminder(CAT, 116.0, datetime(2026, 10, 10, 16, 0)) is None


def test_at_the_start_of_the_window_nothing_is_expected_yet():
    assert main.render_water_reminder(CAT, 0.0, datetime(2026, 10, 10, 9, 0)) is None


def test_once_the_goal_is_met_there_is_no_reminder():
    assert main.render_water_reminder(CAT, 280.0, datetime(2026, 10, 10, 23, 0)) is None
