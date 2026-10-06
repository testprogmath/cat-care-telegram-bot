"""What the web pages show, computed from diary rows. Templates only lay it out."""

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import db, foods, meds

RECENT_DAYS = 7
CURRENT_COURSE_DAYS = 2
MINI_CHART_DAYS = 31
DOSE_SHADES = ("#9ED6CC", "#3FA796", "#0F7B6C", "#0B4F45")
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def weekday(day: date) -> str:
    return WEEKDAYS[day.weekday()]


@dataclass
class Share:
    """Two parts of one total, as fractions of a bar 100 units wide."""

    first: float
    second: float

    @classmethod
    def of(cls, first: float, second: float, goal: float) -> "Share":
        scale = max(goal, first + second, 1)
        return cls(round(first / scale * 100, 1), round(second / scale * 100, 1))


@dataclass
class MiniBar:
    x: float
    w: float
    tube_y: float
    tube_h: float
    self_y: float
    self_h: float
    total: int
    label: str


@dataclass
class MiniChart:
    width: float
    height: int
    goal_y: float
    bars: list[MiniBar]
    labelled: bool


def mini_chart(rows: list, goal: float) -> MiniChart | None:
    if not rows or len(rows) > MINI_CHART_DAYS:
        return None
    width, height, top = 240.0, 130.0, 18.0
    slot = width / len(rows)
    peak = max([r.kcal for r in rows] + [goal, 1])
    scale = height / peak
    bars = []
    for i, r in enumerate(rows):
        tube_h, self_h = r.kcal_tube * scale, r.kcal_self * scale
        base = top + height
        bars.append(MiniBar(
            x=round(i * slot + slot * 0.15, 2), w=round(slot * 0.7, 2),
            tube_y=round(base - tube_h, 1), tube_h=round(tube_h, 1),
            self_y=round(base - tube_h - self_h, 1), self_h=round(self_h, 1),
            total=round(r.kcal), label=r.day.strftime("%d.%m"),
        ))
    return MiniChart(width=width, height=int(top + height), goal_y=round(top + height - goal * scale, 1),
                     bars=bars, labelled=len(rows) <= 14)


KINDS = {
    "food_self": ("еда · сама", "self"),
    "food_tube": ("еда · зонд", "tube"),
    "water": ("вода", "water"),
    "medication": ("лекарство", "meds"),
    "refusal": ("отказ", "refusal"),
    "toilet": ("туалет", "toilet"),
    "temperature": ("температура", "state"),
    "state": ("состояние", "state"),
    "other": ("прочее", "state"),
}
FILTERS = {
    "food": ("Еда", {"food_self", "food_tube", "refusal"}),
    "meds": ("Лекарства", {"medication"}),
    "toilet": ("Туалет", {"toilet"}),
    "state": ("Состояние", {"state", "other", "temperature"}),
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


def _kind(row: sqlite3.Row) -> str:
    if row["type"] == "food":
        return "food_tube" if row["feeding"] == "tube" else "food_self"
    return row["type"] if row["type"] in KINDS else "other"


def _extra(message: str | None, *shown: str) -> str | None:
    """The chat message, only when it says more than the entry already shows."""
    if not message:
        return None
    longest = max((len(text) for text in shown if text), default=0)
    if "\n" in message.strip() or len(message) > longest + 40:
        return message
    return None


def _fmt(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def day_events(rows: list[sqlite3.Row], show: str | None) -> tuple[list[DayEvent], WaterLine | None]:
    wanted = FILTERS[show][1] if show in FILTERS else None
    events, water = [], WaterLine(0, 0.0)
    for row in rows:
        kind = _kind(row)
        if kind == "water":
            water.count += 1
            water.ml += row["water_ml"] or 0
            continue
        if wanted is not None and kind not in wanted:
            continue
        label, tone = KINDS[kind]
        tags: list[str] = []
        if kind == "toilet" and db.is_stool(row["description"]):
            label = "туалет · стул"
        title = row["description"] or ""
        detail = ""
        if kind in ("food_self", "food_tube"):
            title = foods.product(row["name"] or title, bool(row["liquid"]), bool(row["name"]))
            if row["amount_ml"]:
                title = f"{title}, {_fmt(round(row['amount_ml'], 1))} мл"
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
            amount = f"{_fmt(round(row['kcal'], 1))} ккал"
        elif row["type"] == "temperature" and row["temp_c"] is not None:
            amount = f"{_fmt(row['temp_c'])} °C"
        events.append(DayEvent(
            time=row["occurred_at"][11:16], kind=label, tone=tone, title=title,
            detail=detail if detail != title else "", amount=amount,
            message=_extra(row["message_text"], title, detail), tags=tags,
        ))
    shown = water if water.count and (wanted is None) else None
    return events, shown


@dataclass
class DoseCell:
    x: int
    shade: str


@dataclass
class CurrentCourse:
    label: str
    dose: str
    since: date
    given: int
    days: int
    first: date
    last: date
    gaps: list[str]
    cells: list[DoseCell]
    width: int


@dataclass
class FinishedCourse:
    label: str
    doses: str
    given: int
    first: date
    last: date


def _span(first: date, last: date) -> str:
    return first.strftime("%d.%m") if first == last else f"{first:%d.%m}–{last:%d.%m}"


def _gaps(days: list[date]) -> list[str]:
    gaps, ordered = [], sorted(days)
    for before, after in zip(ordered, ordered[1:], strict=False):
        if (after - before).days > 1:
            gaps.append(_span(before + timedelta(days=1), after - timedelta(days=1)))
    return gaps


def courses(rows: list[sqlite3.Row], start: date, end: date) -> tuple[list[CurrentCourse], list[FinishedCourse]]:
    current, finished = [], []
    for course in meds.courses(rows):
        if course.last >= end - timedelta(days=CURRENT_COURSE_DAYS):
            amounts = sorted({a for d in course.doses_on.values() for a in map(meds.dose_amount, d) if a is not None})
            shade_of = {a: DOSE_SHADES[min(i, len(DOSE_SHADES) - 1)] for i, a in enumerate(amounts)}
            cells = []
            for offset in range((end - start).days + 1):
                day = start + timedelta(days=offset)
                doses = course.doses_on.get(day)
                if doses is None:
                    continue
                known = [meds.dose_amount(d) for d in doses if meds.dose_amount(d) is not None]
                cells.append(DoseCell(x=offset, shade=shade_of[max(known)] if known else "#C9CFCB"))
            last_doses = sorted(course.doses_on[course.last], key=lambda d: (d == meds.NO_DOSE, d))
            dose = last_doses[0] if last_doses[0] != meds.NO_DOSE else "без дозы"
            amount = meds.dose_amount(dose)
            since = course.last
            while any(meds.dose_amount(d) == amount for d in course.doses_on.get(since - timedelta(days=1), ())):
                since -= timedelta(days=1)
            current.append(CurrentCourse(
                label=meds._label(course.drug), dose=dose, since=since, given=course.given,
                days=len(course.days), first=course.first, last=course.last,
                gaps=_gaps(list(course.days)), cells=cells, width=(end - start).days + 1,
            ))
        else:
            finished.append(FinishedCourse(
                label=meds._label(course.drug), doses=meds._doses(course), given=course.given,
                first=course.first, last=course.last,
            ))
    return current, finished


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
            amount="", message=_extra(row["message_text"], row["description"] or ""),
            tags=foods.refused_products(row),
        ))
    days = [RefusalDay(date.fromisoformat(day), items) for day, items in by_day.items()]
    return counts.most_common(8), days
