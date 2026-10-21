"""What the foods page shows: what the animal eats now, has stopped eating or never ate, and refusals."""

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import foods
from .day_view import DayEvent, extra_message

RECENT_DAYS = 7


@dataclass
class FoodGroup:
    title: str
    lines: list[foods.FoodLine] = field(default_factory=list)


def food_groups(lines: list[foods.FoodLine], end: date) -> list[FoodGroup]:
    eating = FoodGroup(f"Ест · за последние {RECENT_DAYS} дней")
    stopped = FoodGroup("Давно не ест")
    never = FoodGroup("Не ест вовсе")
    recent = end - timedelta(days=RECENT_DAYS - 1)
    for line in lines:
        if not line.eaten:
            never.lines.append(line)
        elif line.last_eaten >= recent:
            eating.lines.append(line)
        else:
            stopped.lines.append(line)
    return [group for group in (eating, stopped, never) if group.lines]


@dataclass
class RefusalDay:
    day: date
    items: list[DayEvent]


def refusal_summary(rows: list[sqlite3.Row]) -> tuple[list[tuple[str, int]], list[RefusalDay]]:
    refusals = [r for r in rows if r["type"] == "refusal"]
    counts = Counter(product for r in refusals for product in foods.refused_products(r))
    by_day: dict[str, list[DayEvent]] = {}
    for row in reversed(refusals):
        by_day.setdefault(row["day"], []).append(DayEvent(
            time=row["occurred_at"][11:16], kind="отказ", tone="refusal",
            title=", ".join(foods.refused_products(row)), detail=row["description"] or "",
            amount="", message=extra_message(row["message_text"], row["description"] or ""),
            tags=foods.refused_products(row),
        ))
    days = [RefusalDay(date.fromisoformat(day), items) for day, items in by_day.items()]
    return counts.most_common(8), days
