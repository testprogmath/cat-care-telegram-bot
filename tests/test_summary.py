"""What the progress line says about feedings that carry no calories."""

from datetime import datetime

from skrypka_bot import profiles, summary

NOW = datetime(2026, 9, 29, 21, 24)


def _progress(rows):
    return summary.render_progress(rows, NOW, profiles.CHIPUNYA)


def test_gravy_with_a_volume_is_not_an_episode_without_quantity(row):
    text = _progress(
        [
            row(type="food", feeding="self", kcal=14.3, liquid=1, amount_ml=15.0, water_fraction=0.782),
            row(type="food", feeding="self", liquid=1, amount_ml=20.0, water_fraction=0.79),
            row(type="food", feeding="self", liquid=1, amount_ml=5.0, water_fraction=0.782),
        ]
    )
    assert "  сам ~14.3, плюс 2 подливки без калорий, вода зачтена" in text
    assert "без количества" not in text


def test_a_feeding_with_neither_kcal_nor_volume_is_without_quantity(row):
    text = _progress(
        [
            row(type="food", feeding="self", kcal=10.0, liquid=1, amount_ml=40.0, water_fraction=0.938),
            row(type="food", feeding="self", liquid=1, water_fraction=0.782),
        ]
    )
    assert "  сам ~10, плюс 1 эпизод без количества" in text
    assert "подливк" not in text


def test_both_kinds_are_listed_apart(row):
    text = _progress(
        [
            row(type="food", feeding="self", kcal=10.0, liquid=1, amount_ml=40.0, water_fraction=0.938),
            row(type="food", feeding="self", liquid=1, water_fraction=0.782),
            row(type="food", feeding="self", liquid=1, amount_ml=20.0, water_fraction=0.79),
        ]
    )
    assert "  сам ~10, плюс 1 эпизод без количества, плюс 1 подливка без калорий, вода зачтена" in text


def test_dry_food_without_a_number_stays_without_quantity(row):
    text = _progress([row(type="food", feeding="self", description="поел сухариков")])
    assert "плюс 1 эпизод без количества" in text
