"""What the diary rows add up to: who gave what, water from food, the day's totals."""

import os
import sqlite3

LIQUID_FOOD_WATER_FRACTION = float(os.environ.get("LIQUID_FOOD_WATER_FRACTION", "0.85"))


def is_given(row: sqlite3.Row) -> bool:
    """People gave it, through the tube or by syringe; anything else the animal took itself."""
    return row["feeding"] == "tube"


def is_liquid_food(row: sqlite3.Row) -> bool:
    return row["type"] == "food" and bool(is_given(row) or row["liquid"])


def food_water_ml(row: sqlite3.Row) -> float:
    if not is_liquid_food(row):
        return 0.0
    return (row["amount_ml"] or 0) * (row["water_fraction"] or LIQUID_FOOD_WATER_FRACTION)


def uncounted_wet(events: list[sqlite3.Row]) -> int:
    return sum(
        1
        for e in events
        if e["type"] == "food" and (e["liquid"] or is_given(e)) and not e["amount_ml"]
    )


def water_from_food(events: list[sqlite3.Row]) -> float:
    return sum(food_water_ml(e) for e in events)


def effective_water(events: list[sqlite3.Row]) -> float:
    drink = sum(e["water_ml"] or 0 for e in events if e["type"] == "water")
    return drink + water_from_food(events)


def kcal_total(events: list[sqlite3.Row]) -> float:
    return sum(e["kcal"] or 0 for e in events if e["type"] == "food")

