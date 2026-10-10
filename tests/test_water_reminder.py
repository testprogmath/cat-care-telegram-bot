"""The water reminder says how far behind the even daily schedule the animal is."""

from datetime import datetime

from conftest import animal

from skrypka_bot import main
from skrypka_bot.profiles import Tube

WITHOUT_TUBE = animal(water_goal_ml=280.0)
WITH_TUBE = animal(tube=Tube(water_portion_ml=25.0, max_feed_ml=100.0))


def test_behind_schedule_the_reminder_states_the_expected_amount_and_the_gap():
    assert main.render_water_reminder(WITHOUT_TUBE, 100.0, datetime(2026, 10, 10, 16, 0)) == (
        "💧 Напоминание: Мурка получила 100 мл воды из 280 (осталось 180).\n"
        "К 16:00 по графику должно быть ~140 мл, не хватает ~40 мл "
        "(график: 280 мл равномерно с 09:00 до 23:00)."
    )


def test_within_the_buffer_of_the_schedule_there_is_no_reminder():
    assert main.render_water_reminder(WITHOUT_TUBE, 116.0, datetime(2026, 10, 10, 16, 0)) is None


def test_at_the_start_of_the_window_nothing_is_expected_yet():
    assert main.render_water_reminder(WITHOUT_TUBE, 0.0, datetime(2026, 10, 10, 9, 0)) is None


def test_once_the_goal_is_met_there_is_no_reminder():
    assert main.render_water_reminder(WITHOUT_TUBE, 280.0, datetime(2026, 10, 10, 23, 0)) is None


def test_with_a_tube_the_rest_is_split_into_portions_no_larger_than_it_takes():
    assert main.render_water_reminder(WITH_TUBE, 120.0, datetime(2026, 10, 10, 15, 0)) == (
        "💧 Напоминание: Мурка получила 120 мл воды из 340 (осталось 220).\n"
        "К 15:00 по графику должно быть ~146 мл, не хватает ~26 мл "
        "(график: 340 мл равномерно с 09:00 до 23:00).\n"
        "Чтобы добрать 220 мл до 23:00: примерно 9 раз по ~24 мл (не больше 25 мл за раз)."
    )


def test_the_last_reminder_of_the_day_does_not_name_a_deadline_that_has_come():
    assert main.render_water_reminder(WITH_TUBE, 300.0, datetime(2026, 10, 10, 23, 0)).splitlines()[-1] == (
        "Чтобы добрать 40 мл: примерно 2 раза по ~20 мл (не больше 25 мл за раз)."
    )
