"""When each medication is next due: by a schedule set with /schedule, or at yesterday's time."""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from . import fmt, meds

AHEAD = timedelta(minutes=15)
LATE = timedelta(hours=1)
YESTERDAY_WINDOW = timedelta(hours=4)
MAX_PER_DAY = 12

_TIME_RE = re.compile(r"(?<![\d.:])([01]?\d|2[0-3]):([0-5]\d)(?![\d.:])")
_DOSE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:мг|мл|mg|ml)\b", re.IGNORECASE)
_PER_DAY_RE = re.compile(r"(?<![\d.,])(\d{1,2})\s*(?:раза|раз|р|x|х|×)?(?![\d.,])", re.IGNORECASE)
_FILLER = {"в", "день", "сутки", "/день", "раз", "раза"}


@dataclass(frozen=True)
class Schedule:
    drug: str
    per_day: int
    times: tuple[time, ...] = ()
    dose: str | None = None

    def describe(self) -> str:
        dose = f" {self.dose}" if self.dose else ""
        if self.times:
            when = ", ".join(f"{t:%H:%M}" for t in self.times)
        else:
            when = (f"{self.per_day} {fmt.plural(self.per_day, 'раз', 'раза', 'раз')} в день, "
                    "от последнего приёма")
        return f"{self.drug}{dose}: {when}"


@dataclass(frozen=True)
class Due:
    drug: str
    at: datetime
    dose: str | None
    basis: str


def parse(args: list[str]) -> Schedule | None:
    """A schedule from /schedule's arguments: the drug, then times, a count per day and a dose in any order."""
    if len(args) < 2:
        return None
    drug = args[0].lower()
    rest = " ".join(args[1:])
    times = tuple(sorted({time(int(h), int(m)) for h, m in _TIME_RE.findall(rest)}))
    rest = _TIME_RE.sub(" ", rest)
    doses = [meds.normalise_dose(d) for d in _DOSE_RE.findall(rest)]
    rest = _DOSE_RE.sub(" ", rest)
    counts = [int(n) for n in _PER_DAY_RE.findall(rest)]
    rest = _PER_DAY_RE.sub(" ", rest)
    if any(word not in _FILLER for word in re.sub(r"[(),;]", " ", rest).lower().split()) or len(counts) > 1:
        return None
    per_day = counts[0] if counts else len(times)
    if not 1 <= per_day <= MAX_PER_DAY or (times and per_day != len(times)):
        return None
    dose = f"{doses[0]} ({', '.join(doses[1:])})" if len(doses) > 1 else (doses[0] if doses else None)
    return Schedule(drug, per_day, times, dose)


def from_row(row: sqlite3.Row) -> Schedule:
    times = tuple(time.fromisoformat(t) for t in row["times"].split(",")) if row["times"] else ()
    return Schedule(row["drug"], row["per_day"], times, row["dose"])


def covers(schedule: Schedule, drug: str) -> bool:
    return drug == schedule.drug or drug.startswith(f"{schedule.drug} ")


def _in_window(at: datetime, now: datetime) -> bool:
    return at - AHEAD <= now <= at + LATE


def _scheduled(schedule: Schedule, given: list[datetime], now: datetime) -> Due | None:
    gap = timedelta(days=1) / schedule.per_day
    if schedule.times:
        for day in (now.date() - timedelta(days=1), now.date(), now.date() + timedelta(days=1)):
            for t in schedule.times:
                at = datetime.combine(day, t, tzinfo=now.tzinfo)
                if _in_window(at, now) and not any(at - gap / 2 <= g <= now for g in given):
                    when = ", ".join(f"{t:%H:%M}" for t in schedule.times)
                    return Due(schedule.drug, at, schedule.dose, f"по расписанию: {when}")
        return None
    if not given:
        return None
    last = max(given)
    at = last + gap
    if not _in_window(at, now):
        return None
    times = fmt.plural(schedule.per_day, "раз", "раза", "раз")
    return Due(schedule.drug, at, schedule.dose,
               f"{schedule.per_day} {times} в день, последний раз в {last:%H:%M}")


def due(schedules: list[Schedule], rows: list[sqlite3.Row], now: datetime) -> list[Due]:
    """Doses due in the next 15 minutes or in the last hour that nobody has recorded yet.

    `rows` are the medication rows from the start of yesterday's care day to now. A drug with a
    schedule follows it; any other drug is due a day after each dose given yesterday or today.
    """
    given: dict[str, list[tuple[datetime, str | None]]] = {}
    for row in rows:
        given.setdefault(meds.drug_name(row), []).append(
            (datetime.fromisoformat(row["occurred_at"]), meds.normalise_dose(row["dose"]))
        )
    found = []
    for schedule in schedules:
        times = [at for drug, doses in given.items() if covers(schedule, drug) for at, _ in doses]
        if (item := _scheduled(schedule, times, now)) is not None:
            found.append(item)
    for drug, doses in given.items():
        if drug == meds.UNNAMED or any(covers(s, drug) for s in schedules):
            continue
        doses.sort()
        for i, (when, dose) in enumerate(doses):
            at = datetime.combine(when.date() + timedelta(days=1), when.time(), tzinfo=now.tzinfo)
            window = YESTERDAY_WINDOW if i == 0 else min(YESTERDAY_WINDOW, (when - doses[i - 1][0]) / 2)
            if _in_window(at, now) and not any(at - window <= g <= now for g, _ in doses):
                found.append(Due(drug, at, dose, f"вчера в {when:%H:%M}"))
    return sorted(found, key=lambda d: (d.at, d.drug))


def marker(at: datetime) -> str:
    return f"[бот напомнил о лекарствах на {at:%Y-%m-%d %H:%M}]"


def render(name_genitive: str, items: list[Due], now: datetime) -> str:
    at = items[0].at
    word = "лекарство" if len(items) == 1 else "лекарства"
    if at > now:
        head = f"💊 В {at:%H:%M} {word} для {name_genitive}:"
    else:
        head = f"💊 Пора дать {word} для {name_genitive}, по плану было в {at:%H:%M}:"
    lines = [
        f"• {meds.drug_label(item.drug)}{f' {item.dose}' if item.dose else ''} ({item.basis})" for item in items
    ]
    return "\n".join([head, *lines])
