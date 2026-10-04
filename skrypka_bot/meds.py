import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape

from .profiles import Profile
from .summary import _plural

UNNAMED = "не названо"
NO_DOSE = "без дозы"

FORMS = {
    "серения": "маропитант, таблетки",
    "превомакс": "маропитант, инъекция",
}

NAMES_EN = {
    "бупренорфин": "buprenorphine",
    "кротакс": "Krotax",
    "марбоцил": "Marbocyl",
    "мелоксикам": "meloxicam",
    "миратаз": "Mirataz",
    "омепразол": "omeprazole",
    "ондансетрон": "ondansetron",
    "превомакс": "Prevomax",
    "преднизолон": "prednisolone",
    "серения": "Cerenia",
    "сукральфат": "sucralfate",
    UNNAMED: "not named",
}

FORMS_EN = {
    "серения": "maropitant, tablets",
    "превомакс": "maropitant, injection",
}

_UNITS_EN = (("мг", "mg"), ("мл", "ml"))

_DECIMAL_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_NUMBER_UNIT_RE = re.compile(r"(?<=\d)(?=[^\d\s.,()/])")


def normalise_dose(dose: str | None) -> str | None:
    if not dose:
        return None
    text = _DECIMAL_COMMA_RE.sub(".", dose.strip())
    return _NUMBER_UNIT_RE.sub(" ", text)


def _drug(row: sqlite3.Row) -> str:
    return (row["name"] or "").strip().lower() or UNNAMED


def _label(drug: str) -> str:
    form = FORMS.get(drug)
    return f"{drug} ({form})" if form else drug


def label_en(drug: str) -> str:
    name = NAMES_EN.get(drug, drug)
    form = FORMS_EN.get(drug)
    return f"{name} ({form})" if form else name


def dose_en(dose: str) -> str:
    for ru, en in _UNITS_EN:
        dose = dose.replace(ru, en)
    return dose


_AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(мг|мл)?")


def dose_amount(dose: str) -> float | None:
    match = _AMOUNT_RE.match(dose)
    return float(match.group(1)) if match else None


def dose_unit(course: "Course") -> str | None:
    for dose, _ in course.doses.most_common():
        match = _AMOUNT_RE.match(dose)
        if match and match.group(2):
            return dose_en(match.group(2))
    return None


@dataclass
class Course:
    drug: str
    days: Counter = field(default_factory=Counter)
    doses: Counter = field(default_factory=Counter)
    doses_on: dict[date, set[str]] = field(default_factory=dict)

    @property
    def given(self) -> int:
        return sum(self.days.values())

    @property
    def first(self) -> date:
        return min(self.days)

    @property
    def last(self) -> date:
        return max(self.days)


def courses(rows: list[sqlite3.Row]) -> list[Course]:
    by_drug: dict[str, Course] = {}
    for row in rows:
        course = by_drug.setdefault(_drug(row), Course(_drug(row)))
        day = date.fromisoformat(row["day"])
        dose = normalise_dose(row["dose"]) or NO_DOSE
        course.days[day] += 1
        course.doses[dose] += 1
        course.doses_on.setdefault(day, set()).add(dose)
    return sorted(by_drug.values(), key=lambda c: (c.drug == UNNAMED, -c.last.toordinal(), c.drug))


def _dm(day: date) -> str:
    return day.strftime("%d.%m")


def _span(first: date, last: date) -> str:
    return _dm(first) if first == last else f"{_dm(first)}–{_dm(last)}"


def _doses(course: Course) -> str:
    ranked = sorted(course.doses.items(), key=lambda item: (item[0] == NO_DOSE, -item[1]))
    return ", ".join(f"{dose} ×{n}" for dose, n in ranked)


def render_week(rows: list[sqlite3.Row], end_day: date, profile: Profile) -> str:
    days = [end_day - timedelta(days=offset) for offset in range(6, -1, -1)]
    header = f"💊 {profile.name}: лекарства {_dm(days[0])}–{_dm(days[-1])}"
    found = courses(rows)
    if not found:
        return escape(f"{header}\nЗа эти дни лекарств не записано.")
    width = max(len(c.drug) for c in found)
    grid = [" " * width + " " + " ".join(d.strftime("%d") for d in days)]
    for course in found:
        cells = " ".join(f"{course.days[d] or '·':>2}" for d in days)
        grid.append(f"{course.drug:<{width}} {cells}")
    doses = [f"{_label(c.drug)}: {_doses(c)}" for c in found]
    return (
        f"{escape(header)}\n<pre>{escape(chr(10).join(grid))}</pre>\n"
        "Число в клетке: сколько раз дали за сутки, · не записано.\n\n"
        + escape("\n".join(doses))
    )


def render_period(rows: list[sqlite3.Row], day_from: date, day_to: date, profile: Profile) -> str:
    span = (day_to - day_from).days + 1
    header = (
        f"💊 {profile.name}: лекарства {_dm(day_from)}–{_dm(day_to)} "
        f"({span} {_plural(span, 'день', 'дня', 'дней')})"
    )
    found = courses(rows)
    if not found:
        return escape(f"{header}\nЗа этот период лекарств не записано.")
    lines = [header]
    for course in found:
        given, on_days = course.given, len(course.days)
        lines += [
            "",
            _label(course.drug),
            f"  {given} {_plural(given, 'приём', 'приёма', 'приёмов')} "
            f"за {on_days} {_plural(on_days, 'день', 'дня', 'дней')}, "
            f"{_span(course.first, course.last)}",
            f"  дозы: {_doses(course)}",
        ]
    return escape("\n".join(lines))
