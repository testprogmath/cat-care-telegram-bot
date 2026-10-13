"""The day page's 24-hour chart: where each event sits, the running totals and the legend."""

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import classify, db, figures, fmt


@dataclass
class ClockMark:
    x: float
    y: float
    shape: str
    tone: str
    r: float
    title: str


@dataclass
class DayClock:
    """One care day on a 24-hour axis: progress towards the goals, and when each thing happened."""
    width: int
    height: int
    left: float
    right: float
    top: float
    bottom: float
    scale: float
    kcal_line: str
    water_line: str
    kcal_pct: float
    water_pct: float
    lanes: list[tuple[str, float]]
    marks: list[ClockMark]
    ticks: list[tuple[float, str]]
    axis_y: float
    tick_anchor: dict[int, str] = field(default_factory=dict)

    def y(self, pct: float) -> float:
        return round(self.bottom - min(pct, self.scale) / self.scale * (self.bottom - self.top), 1)


CLOCK_LANES = ("Еда", "Вода", "Туалет", "Лекарства")


def _size(amount: float | None, factor: float, low: float = 2.0, high: float = 6.5) -> float:
    if not amount:
        return low
    return round(min(high, max(low, 1.6 + math.sqrt(amount) * factor)), 1)


def day_clock(rows: list[sqlite3.Row], day: date, kcal_goal: float, water_goal: float,
              now: datetime) -> DayClock | None:
    timed = [r for r in rows if r["type"] in ("food", "refusal", "water", "toilet", "medication")]
    if not timed:
        return None
    start = db.care_day_start(day, now.tzinfo)
    width, height, left, right, top, bottom = 240, 164, 40.0, 234.0, 10.0, 70.0
    lane_y = {name: 88.0 + i * 16 for i, name in enumerate(CLOCK_LANES)}

    def hours(row: sqlite3.Row) -> float:
        at = datetime.fromisoformat(row["occurred_at"])
        return min(24.0, max(0.0, (at - start).total_seconds() / 3600))

    def x(h: float) -> float:
        return round(left + h / 24 * (right - left), 1)

    marks: list[ClockMark] = []
    kcal_steps: list[tuple[float, float]] = []
    water_steps: list[tuple[float, float]] = []
    meds_at: dict[float, list[str]] = {}
    for row in timed:
        h, kind, desc = hours(row), row["type"], row["description"] or ""
        clock = datetime.fromisoformat(row["occurred_at"]).strftime("%H:%M")
        if kind == "food":
            tone = "tube" if figures.is_given(row) else "self"
            kcal = row["kcal"] or 0
            marks.append(ClockMark(x(h), lane_y["Еда"], "circle", tone, _size(kcal, 0.7),
                                   f"{clock} {desc}" + (f", {fmt.comma(round(kcal, 1))} ккал" if kcal else "")))
            if kcal:
                kcal_steps.append((h, kcal))
            if (water := figures.food_water_ml(row)):
                water_steps.append((h, water))
        elif kind == "refusal":
            marks.append(ClockMark(x(h), lane_y["Еда"], "ring", "refused", 2.6, f"{clock} отказ: {desc}"))
        elif kind == "water":
            ml = row["water_ml"] or 0
            drank = not figures.is_given(row)
            marks.append(ClockMark(x(h), lane_y["Вода"], "circle" if drank else "ring", "drink",
                                   _size(ml, 0.55, high=6.0), f"{clock} {desc}"))
            if ml:
                water_steps.append((h, ml))
        elif kind == "toilet":
            shape, tone = {"stool": ("square", "stool"), "urine": ("circle", "toilet"),
                           "failed": ("ring", "toilet")}[classify.toilet_kind(desc)]
            marks.append(ClockMark(x(h), lane_y["Туалет"], shape, tone, 3.0, f"{clock} {desc}"))
        else:
            label = " ".join(part for part in (row["name"] or desc, row["dose"]) if part)
            meds_at.setdefault(x(h), []).append(f"{clock} {label}")
    for at, labels in meds_at.items():
        marks.append(ClockMark(at, lane_y["Лекарства"], "diamond", "meds", 3.4, "; ".join(labels)))

    until = 24.0 if now >= start + timedelta(days=1) else min(24.0, max(0.0, (now - start).total_seconds() / 3600))

    def cumulative(steps: list[tuple[float, float]], goal: float) -> tuple[list[tuple[float, float]], float]:
        points, total = [(0.0, 0.0)], 0.0
        for h, amount in sorted(steps):
            points.append((h, total))
            total += amount / goal * 100
            points.append((h, total))
        points.append((max(until, points[-1][0]), total))
        return points, total

    kcal_points, kcal_pct = cumulative(kcal_steps, kcal_goal) if kcal_goal else ([], 0.0)
    water_points, water_pct = cumulative(water_steps, water_goal) if water_goal else ([], 0.0)
    scale = min(150.0, max(100.0, math.ceil(max(kcal_pct, water_pct) / 25) * 25))
    clock = DayClock(width, height, left, right, top, bottom, scale, "", "", kcal_pct, water_pct,
                     [(name, y) for name, y in lane_y.items()], marks, [], 156.0)
    clock.kcal_line = " ".join(f"{x(h)},{clock.y(p)}" for h, p in kcal_points)
    clock.water_line = " ".join(f"{x(h)},{clock.y(p)}" for h, p in water_points)
    clock.ticks = [(x(h), (start + timedelta(hours=h)).strftime("%H:%M")) for h in (0, 6, 12, 18, 24)]
    clock.tick_anchor = {0: "start", len(clock.ticks) - 1: "end"}
    return clock


@dataclass
class LegendItem:
    shape: str
    tone: str
    label: str


def clock_legend(clock: DayClock, self_label: str, drank: str) -> list[tuple[str, list[LegendItem]]]:
    """What each mark on this day's clock means, listing only the marks it has."""
    seen = {(m.y, m.shape, m.tone) for m in clock.marks}
    lane = dict(clock.lanes)
    tube = (lane["Еда"], "circle", "tube") in seen
    groups = [
        ("Еда", lane["Еда"], [("circle", "self", self_label), ("circle", "tube", "зонд"), ("ring", "refused", "отказ")]),
        ("Вода", lane["Вода"], [("circle", "drink", drank), ("ring", "drink", "дали в зонд" if tube else "дали")]),
        ("Туалет", lane["Туалет"], [("circle", "toilet", "моча"), ("square", "stool", "стул"),
                                    ("ring", "toilet", "без результата")]),
        ("Лекарства", lane["Лекарства"], [("diamond", "meds", "лекарства")]),
    ]
    legend = []
    for name, y, items in groups:
        present = [LegendItem(shape, tone, label) for shape, tone, label in items if (y, shape, tone) in seen]
        if present:
            legend.append((name, present))
    return legend

