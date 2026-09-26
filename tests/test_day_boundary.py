from datetime import datetime

import pytest

from skrypka_bot import db, main


def test_before_the_boundary_belongs_to_the_previous_day():
    """DAY_START defaults to 11:00, so 01:37 is still yesterday's care day."""
    assert db.DAY_START == "11:00"
    assert db.care_day(datetime(2026, 9, 25, 1, 37)) == datetime(2026, 9, 24).date()


def test_after_the_boundary_starts_a_new_day():
    assert db.care_day(datetime(2026, 9, 25, 11, 0)) == datetime(2026, 9, 25).date()


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 25, 7, 0), 0.0),
        (datetime(2026, 9, 25, 9, 0), 0.0),
        (datetime(2026, 9, 25, 16, 0), 0.5),
        (datetime(2026, 9, 25, 23, 0), 1.0),
        (datetime(2026, 9, 25, 23, 45), 1.0),
    ],
)
def test_pace_tracks_the_active_window(now, expected):
    """/risk divides intake by this, so it must stay inside 0..1."""
    assert main.day_pace(now) == pytest.approx(expected)
