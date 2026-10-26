"""What the day page shows: each entry as a line of the timeline, and the day's water in one line."""

import sqlite3
from dataclasses import dataclass, field

from . import classify, figures, fmt, foods, meds, questions

KINDS = {
    "food_self": ("еда · {self}", "self"),
    "food_tube": ("еда · зонд", "tube"),
    "water": ("вода", "water"),
    "medication": ("лекарство", "meds"),
    "refusal": ("отказ", "refusal"),
    "toilet": ("туалет", "toilet"),
    "temperature": ("температура", "state"),
    "weight": ("вес", "state"),
    "breathing": ("дыхание", "state"),
    "state": ("состояние", "state"),
    "other": ("прочее", "state"),
}
FILTERS = {
    "food": ("Еда", {"food_self", "food_tube", "refusal"}),
    "meds": ("Лекарства", {"medication"}),
    "toilet": ("Туалет", {"toilet"}),
    "state": ("Состояние", {"state", "other", "temperature", "weight", "breathing"}),
}


@dataclass
class DayEvent:
    time: str
    kind: str
    tone: str
    title: str
    detail: str
    amount: str
    message: str | None
    tags: list[str] = field(default_factory=list)


@dataclass
class WaterLine:
    count: int
    ml: float
    drank_count: int = 0
    drank_ml: float = 0.0
    infused_count: int = 0
    infused_ml: float = 0.0


def _kind(row: sqlite3.Row) -> str:
    if row["type"] == "food":
        return "food_tube" if figures.is_given(row) else "food_self"
    return row["type"] if row["type"] in KINDS else "other"


def extra_message(message: str | None, *shown: str) -> str | None:
    """The chat message, only when it says more than the entry already shows."""
    if not message:
        return None
    longest = max((len(text) for text in shown if text), default=0)
    if "\n" in message.strip() or len(message) > longest + 40:
        return message
    return None


def day_events(rows: list[sqlite3.Row], show: str | None,
               self_label: str = "сама") -> tuple[list[DayEvent], WaterLine | None]:
    wanted = FILTERS[show][1] if show in FILTERS else None
    events, water = [], WaterLine(0, 0.0)
    for row in rows:
        kind = _kind(row)
        if kind == "water":
            water.count += 1
            water.ml += row["water_ml"] or 0
            source = figures.water_source(row)
            if source == "drank":
                water.drank_count += 1
                water.drank_ml += row["water_ml"] or 0
            elif source == "infusion":
                water.infused_count += 1
                water.infused_ml += row["water_ml"] or 0
            continue
        if wanted is not None and kind not in wanted:
            continue
        label, tone = KINDS[kind]
        label = label.format(self=self_label)
        tags: list[str] = []
        if kind == "toilet":
            label = {"stool": "туалет · стул", "failed": "туалет · без результата"}.get(
                classify.toilet_kind(row["description"]), label)
        title = row["description"] or ""
        detail = ""
        if kind in ("food_self", "food_tube"):
            title = foods.product(row["name"] or title, bool(row["liquid"]), bool(row["name"]))
            if row["amount_ml"]:
                title = f"{title}, {fmt.comma(round(row['amount_ml'], 1))} мл"
            detail = row["description"] or ""
        elif kind == "medication":
            title = " ".join(part for part in (row["name"], meds.normalise_dose(row["dose"])) if part) or title
            detail = row["description"] if row["name"] else ""
        elif kind == "refusal":
            title = ", ".join(foods.refused_products(row))
            detail = row["description"] or ""
            tags = foods.refused_products(row)
        amount = ""
        if row["kcal"]:
            amount = f"{fmt.comma(round(row['kcal'], 1))} ккал"
        elif row["type"] == "temperature" and row["temp_c"] is not None:
            amount = f"{fmt.comma(row['temp_c'])} °C"
        elif row["type"] == "weight" and row["weight_kg"]:
            amount = f"{fmt.comma(row['weight_kg'])} кг"
        elif row["type"] == "toilet" and row["stool_score"]:
            amount = questions.stool_label(row["stool_score"])
        elif row["type"] == "breathing" and row["breaths"]:
            amount = f"{fmt.comma(row['breaths'])}/мин" + (" во сне" if row["asleep"] == 1 else "")
        events.append(DayEvent(
            time=row["occurred_at"][11:16], kind=label, tone=tone, title=title,
            detail=detail if detail != title else "", amount=amount,
            message=extra_message(row["message_text"], title, detail), tags=tags,
        ))
    shown = water if water.count and (wanted is None) else None
    return events, shown
