"""What the medication page shows: courses running and finished, treatment changes, before and after."""

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from . import meds
from .daily import day_rows

CURRENT_COURSE_DAYS = 2
DOSE_SHADES = ("#9ED6CC", "#3FA796", "#0F7B6C", "#0B4F45")
COMPARE_DAYS = 7
COMPARE_MIN_AFTER = 3
STEADY_DAYS = 3


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


def _gaps(days: list[date]) -> list[str]:
    gaps, ordered = [], sorted(days)
    for before, after in zip(ordered, ordered[1:], strict=False):
        if (after - before).days > 1:
            gaps.append(meds.day_span(before + timedelta(days=1), after - timedelta(days=1)))
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
                label=meds.drug_label(course.drug), dose=dose, since=since, given=course.given,
                days=len(course.days), first=course.first, last=course.last,
                gaps=_gaps(list(course.days)), cells=cells, width=(end - start).days + 1,
            ))
        else:
            finished.append(FinishedCourse(
                label=meds.drug_label(course.drug), doses=meds.dose_summary(course), given=course.given,
                first=course.first, last=course.last,
            ))
    return current, finished


@dataclass
class Mark:
    day: date
    label: str


def treatment_marks(rows: list[sqlite3.Row]) -> list[Mark]:
    """The day each medication started, and each day a new dose began that then held.

    A dose counts as changed only when the new amount is given on STEADY_DAYS days running;
    a single evening at another dose is a wobble, not a change of treatment.
    """
    marks = []
    for course in meds.courses(rows):
        days = sorted(course.doses_on)
        amounts = []
        for day in days:
            known = {meds.dose_amount(d) for d in course.doses_on[day]} - {None}
            amounts.append(max(known) if known else None)
        opening = [a for a in amounts[:STEADY_DAYS] if a is not None]
        counts = Counter(opening)
        first_amount = (max(reversed(opening), key=counts.__getitem__) if opening
                        else next((a for a in amounts if a is not None), None))
        marks.append(Mark(days[0], f"{course.drug}: начало" + (f", {first_amount:g}" if first_amount else "")))
        steady = first_amount
        for i, amount in enumerate(amounts):
            if i < STEADY_DAYS:
                continue
            if amount is None or steady is None or amount == steady:
                continue
            run = amounts[i:i + STEADY_DAYS]
            if len(run) == STEADY_DAYS and all(a == amount for a in run):
                marks.append(Mark(days[i], f"{course.drug}: {steady:g} → {amount:g}"))
                steady = amount
    return sorted(marks, key=lambda m: m.day)


@dataclass
class Comparison:
    mark: Mark
    before: tuple[date, date]
    after: tuple[date, date]
    lines: list[tuple[str, str, str]]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def same_day_marks(marks: list[Mark]) -> list[Mark]:
    """One mark per day, so two changes on one day give one comparison."""
    merged: dict[date, list[str]] = {}
    for mark in marks:
        merged.setdefault(mark.day, []).append(mark.label)
    return [Mark(day, "; ".join(labels)) for day, labels in sorted(merged.items())]


def compare_around(subject: str, mark: Mark, today: date,
                   self_label: str = "сама") -> Comparison | None:
    before = (mark.day - timedelta(days=COMPARE_DAYS), mark.day - timedelta(days=1))
    after = (mark.day, min(mark.day + timedelta(days=COMPARE_DAYS - 1), today))
    if (after[1] - after[0]).days + 1 < COMPARE_MIN_AFTER:
        return None
    rows_before = [r for r in day_rows(subject, *before) if r.recorded]
    rows_after = [r for r in day_rows(subject, *after) if r.recorded]
    if not rows_before or not rows_after:
        return None

    def per_day(rows, attr) -> float:
        return _mean([getattr(r, attr) or 0 for r in rows])

    def share(rows, test) -> str:
        return f"{sum(1 for r in rows if test(r))} из {len(rows)}"

    lines = [
        (f"Ккал {self_label}", f"{per_day(rows_before, 'kcal_self'):.0f}", f"{per_day(rows_after, 'kcal_self'):.0f}"),
        ("Ккал через зонд", f"{per_day(rows_before, 'kcal_tube'):.0f}", f"{per_day(rows_after, 'kcal_tube'):.0f}"),
        ("Моча в день", f"{per_day(rows_before, 'urinations'):.1f}", f"{per_day(rows_after, 'urinations'):.1f}"),
        ("Дней со стулом", share(rows_before, lambda r: r.stools), share(rows_after, lambda r: r.stools)),
        ("Дней с рвотой", share(rows_before, lambda r: r.vomiting), share(rows_after, lambda r: r.vomiting)),
        ("Отказов в день", f"{per_day(rows_before, 'refusals'):.1f}", f"{per_day(rows_after, 'refusals'):.1f}"),
    ]
    return Comparison(mark=mark, before=before, after=after, lines=lines)
