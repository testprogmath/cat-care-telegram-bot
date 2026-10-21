"""Each care day's figures from the diary, the base of the week, day and medication pages."""

from dataclasses import dataclass
from datetime import date, timedelta

from . import care_export, db, figures


@dataclass
class DayRow:
    day: date
    recorded: bool
    kcal_self: float
    kcal_tube: float
    drinking_ml: float | None
    from_food_ml: float | None
    urinations: int | None
    stools: int | None
    vomiting: int
    refusals: int
    temperatures: list[float]
    drank_times: int = 0
    drank_ml: float = 0.0
    given_ml: float = 0.0

    @property
    def kcal(self) -> float:
        return self.kcal_self + self.kcal_tube


def day_rows(subject: str, start: date, end: date) -> list[DayRow]:
    exported = {d.care_day: d for d in care_export.export(subject, start, end)}
    events = db.events_in_days(subject, start, end)
    rows = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        that_day = [e for e in events if e["day"] == day.isoformat()]
        food = [e for e in that_day if e["type"] == "food"]
        drank = [e for e in that_day if e["type"] == "water" and not figures.is_given(e)]
        given = [e for e in that_day if e["type"] == "water" and figures.is_given(e)]
        record = exported[day]
        rows.append(DayRow(
            day=day,
            recorded=bool(that_day),
            kcal_self=sum(e["kcal"] or 0 for e in food if not figures.is_given(e)),
            kcal_tube=sum(e["kcal"] or 0 for e in food if figures.is_given(e)),
            drinking_ml=record.water_drinking_ml,
            from_food_ml=record.water_from_food_ml,
            urinations=record.urinations_observed,
            stools=record.stools_observed,
            vomiting=len(record.vomiting_episodes),
            refusals=len(record.food_refusals),
            temperatures=[t.value_c for t in record.temperatures],
            drank_times=len(drank),
            drank_ml=sum(e["water_ml"] or 0 for e in drank),
            given_ml=sum(e["water_ml"] or 0 for e in given),
        ))
    return rows


@dataclass
class Averages:
    days: int
    kcal_self: float
    kcal_tube: float
    kcal: float
    drinking_ml: float
    from_food_ml: float
    urinations: float
    stools: float
    drank_times: float = 0.0
    drank_ml: float = 0.0
    given_ml: float = 0.0


def averages(rows: list[DayRow]) -> Averages | None:
    """Per-day means over the days that have any record at all; a silent day is not a zero."""
    recorded = [r for r in rows if r.recorded]
    if not recorded:
        return None
    n = len(recorded)

    def mean(values) -> float:
        return sum(v or 0 for v in values) / n

    return Averages(
        days=n,
        kcal_self=mean(r.kcal_self for r in recorded),
        kcal_tube=mean(r.kcal_tube for r in recorded),
        kcal=mean(r.kcal for r in recorded),
        drinking_ml=mean(r.drinking_ml for r in recorded),
        from_food_ml=mean(r.from_food_ml for r in recorded),
        urinations=mean(r.urinations for r in recorded),
        stools=mean(r.stools for r in recorded),
        drank_times=mean(r.drank_times for r in recorded),
        drank_ml=mean(r.drank_ml for r in recorded),
        given_ml=mean(r.given_ml for r in recorded),
    )
