"""Gravy of a product with an estimate gets its calories even when the model left them out."""

import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import db, ingest

BERLIN = ZoneInfo("Europe/Berlin")


def food(name, grams, kcal=None, water_fraction=0.786):
    return SimpleNamespace(type="food", name=name, dose=None, water_ml=None, kcal=kcal, feeding="self",
                           amount_ml=grams, temp_c=None, liquid=True, water_fraction=water_fraction,
                           time=None, description=f"слизал {grams:g} г подливки")


def stored(chat, *events):
    ingest.save_message(chat, 1, "owner", datetime(2026, 10, 13, 12, 0, tzinfo=BERLIN), "подливка", list(events))
    with sqlite3.connect(db.DB_PATH) as conn:
        return [tuple(r) for r in conn.execute("SELECT kcal, water_fraction FROM events ORDER BY id")]


@pytest.mark.parametrize("name", ["felix heerlijke reepjes утка", "Heerlijke Streepjes"])
def test_reepjes_gravy_without_calories_is_counted_at_the_gravy_estimate(chat, name):
    assert stored(chat, food(name, 10.0)) == [(3.0, 0.9)]


def test_calories_the_model_gave_are_kept(chat):
    assert stored(chat, food("felix heerlijke reepjes", 40.0, kcal=35.7)) == [(35.7, 0.786)]


def test_gravy_of_a_product_without_an_estimate_stays_without_calories(chat):
    assert stored(chat, food("monge", 10.0, water_fraction=0.79)) == [(None, 0.79)]
