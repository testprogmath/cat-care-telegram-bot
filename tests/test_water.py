import pytest

from skrypka_bot import db, summary


def test_dry_food_carries_no_water(row):
    assert db.food_water_ml(row(type="food", feeding="self", amount_ml=8.0)) == 0


def test_wet_food_uses_its_own_fraction(row):
    kitten = row(type="food", feeding="self", liquid=1, amount_ml=50.0, water_fraction=0.782)
    assert db.food_water_ml(kitten) == pytest.approx(39.1)


def test_missing_fraction_falls_back(row):
    """Rows predate the water_fraction column; they must still compute."""
    old = row(type="food", feeding="tube", amount_ml=40.0)
    assert db.food_water_ml(old) == pytest.approx(40 * db.LIQUID_FOOD_WATER_FRACTION)


def test_tube_feed_is_liquid_without_the_flag(row):
    assert db.is_liquid_food(row(type="food", feeding="tube", amount_ml=30.0))


def test_effective_water_adds_drinking_to_food(row):
    events = [
        row(type="water", water_ml=27.0),
        row(type="food", feeding="self", liquid=1, amount_ml=50.0, water_fraction=0.8),
        row(type="food", feeding="self", amount_ml=6.0),
    ]
    assert summary.effective_water(events) == pytest.approx(67.0)
