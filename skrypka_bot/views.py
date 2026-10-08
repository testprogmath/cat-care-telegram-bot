"""What the web pages show, computed from diary rows. Templates only lay it out."""

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import care_export, db, foods, meds

RECENT_DAYS = 7
CURRENT_COURSE_DAYS = 2
MINI_CHART_DAYS = 31
DOSE_SHADES = ("#9ED6CC", "#3FA796", "#0F7B6C", "#0B4F45")
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


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


def day_rows(chat_id: int, subject: str, start: date, end: date) -> list[DayRow]:
    exported = {d.care_day: d for d in care_export.export(subject, start, end)}
    events = db.events_in_days(chat_id, start, end)
    rows = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        that_day = [e for e in events if e["day"] == day.isoformat()]
        food = [e for e in that_day if e["type"] == "food"]
        drank = [e for e in that_day if e["type"] == "water" and e["feeding"] == "self"]
        given = [e for e in that_day if e["type"] == "water" and e["feeding"] == "tube"]
        record = exported[day]
        rows.append(DayRow(
            day=day,
            recorded=bool(that_day),
            kcal_self=sum(e["kcal"] or 0 for e in food if e["feeding"] != "tube"),
            kcal_tube=sum(e["kcal"] or 0 for e in food if e["feeding"] == "tube"),
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
class Share3:
    """Three parts of one total on a bar 100 units wide, with where each part starts."""

    widths: tuple[float, float, float]

    @classmethod
    def of(cls, parts: tuple[float, float, float], goal: float) -> "Share3":
        scale = max(goal, sum(parts), 1)
        return cls(tuple(round(p / scale * 100, 1) for p in parts))

    @property
    def starts(self) -> tuple[float, float, float]:
        a, b, _ = self.widths
        return (0.0, a, round(a + b, 1))


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
class ToiletBar:
    urine_x: float
    stool_x: float
    w: float
    urine_y: float
    urine_h: float
    stool_y: float
    stool_h: float
    urine: int | None
    stool: int | None


@dataclass
class MiniChart:
    width: float
    height: int
    goal_y: float
    bars: list[MiniBar]
    labelled: bool
    toilet: list[ToiletBar] = field(default_factory=list)
    toilet_height: int = 0


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
    toilet_top, toilet_height = 12.0, 50.0
    most = max([r.urinations or 0 for r in rows] + [r.stools or 0 for r in rows] + [1])
    toilet = []
    for i, r in enumerate(rows):
        bar = round(slot * 0.32, 2)
        urine_h = (r.urinations or 0) / most * toilet_height
        stool_h = (r.stools or 0) / most * toilet_height
        base = toilet_top + toilet_height
        toilet.append(ToiletBar(
            urine_x=round(i * slot + slot * 0.15, 2), stool_x=round(i * slot + slot * 0.15 + bar + slot * 0.06, 2),
            w=bar, urine_y=round(base - urine_h, 1), urine_h=round(urine_h, 1),
            stool_y=round(base - stool_h, 1), stool_h=round(stool_h, 1),
            urine=r.urinations, stool=r.stools,
        ))
    return MiniChart(toilet=toilet, toilet_height=int(toilet_top + toilet_height),
                     width=width, height=int(top + height), goal_y=round(top + height - goal * scale, 1),
                     bars=bars, labelled=len(rows) <= 14)


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


def day_events(rows: list[sqlite3.Row], show: str | None,
               self_label: str = "сама") -> tuple[list[DayEvent], WaterLine | None]:
    wanted = FILTERS[show][1] if show in FILTERS else None
    events, water = [], WaterLine(0, 0.0)
    for row in rows:
        kind = _kind(row)
        if kind == "water":
            water.count += 1
            water.ml += row["water_ml"] or 0
            if row["feeding"] == "self":
                water.drank_count += 1
                water.drank_ml += row["water_ml"] or 0
            continue
        if wanted is not None and kind not in wanted:
            continue
        label, tone = KINDS[kind]
        label = label.format(self=self_label)
        tags: list[str] = []
        if kind == "toilet":
            label = {"stool": "туалет · стул", "failed": "туалет · без результата"}.get(
                db.toilet_kind(row["description"]), label)
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
        elif row["type"] == "weight" and row["weight_kg"]:
            amount = f"{_fmt(row['weight_kg'])} кг"
        elif row["type"] == "breathing" and row["breaths"]:
            amount = f"{_fmt(row['breaths'])}/мин" + (" во сне" if row["asleep"] == 1 else "")
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


WEIGHT_STALE_DAYS = 7
SLEEP_BREATHS_LIMIT = 30
STOOL_WARN_DAYS = 2
TREND_WINDOW = 7
TREND_MIN_DAYS = 4
COMPARE_DAYS = 7
COMPARE_MIN_AFTER = 3
STEADY_DAYS = 3


@dataclass
class Weighing:
    day: date
    kg: float


@dataclass
class WeightSummary:
    last: Weighing
    days_ago: int
    stale: bool
    previous: Weighing | None
    change_30: float | None
    points: list[tuple[float, float]]
    low: float
    high: float


def _weighings(chat_id: int, until: date) -> list[Weighing]:
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT day, weight_kg FROM events WHERE chat_id = ? AND type = 'weight' AND weight_kg > 0 "
            "AND day <= ? ORDER BY occurred_at",
            (chat_id, until.isoformat()),
        ).fetchall()
    return [Weighing(date.fromisoformat(r["day"]), r["weight_kg"]) for r in rows]


def weight_summary(chat_id: int, start: date, end: date, today: date) -> WeightSummary | None:
    weighings = _weighings(chat_id, end)
    if not weighings:
        return None
    last = weighings[-1]

    earlier = [w for w in weighings if w.day <= last.day - timedelta(days=30)]

    shown = [w for w in weighings if start <= w.day <= end] or [last]
    low, high = min(w.kg for w in shown), max(w.kg for w in shown)
    span = max((end - start).days, 1)
    spread = max(high - low, 0.05)
    points = [(round((w.day - start).days / span * 100, 1), round(36 - (w.kg - low) / spread * 28, 1))
              for w in shown]
    return WeightSummary(last=last, days_ago=(today - last.day).days,
                         stale=(today - last.day).days >= WEIGHT_STALE_DAYS,
                         previous=weighings[-2] if len(weighings) > 1 else None,
                         change_30=round(last.kg - earlier[-1].kg, 3) if earlier else None,
                         points=points, low=low, high=high)


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
class TrendBar:
    x: float
    w: float
    y: float
    h: float


@dataclass
class TrendMark:
    number: int
    x: float
    day: date
    label: str


@dataclass
class Trend:
    width: int
    height: int
    left: float
    right: float
    top: float
    bottom: float
    bars: list[TrendBar]
    line: str
    marks: list[TrendMark]
    latest_pct: float
    latest_kcal: float
    first_label: str
    last_label: str

    def y(self, pct: float) -> float:
        return round(self.bottom - min(pct, 100) / 100 * (self.bottom - self.top), 1)


def appetite_trend(rows: list[DayRow], start: date, end: date, goal: float,
                   marks: list[Mark]) -> Trend | None:
    """Each day's self-fed calories as a share of the goal, and their mean over seven recorded days."""
    if not goal:
        return None
    width, height, left, right, top, bottom = 240, 132, 26.0, 236.0, 12.0, 112.0
    days = (end - start).days + 1
    slot = (right - left) / days
    trend = Trend(width, height, left, right, top, bottom, [], "", [], 0.0, 0.0,
                  start.strftime("%d.%m"), end.strftime("%d.%m"))
    points, latest = [], None
    for i, row in enumerate(rows):
        if row.day < start:
            continue
        offset = (row.day - start).days
        centre = left + offset * slot + slot / 2
        if row.recorded:
            pct = row.kcal_self / goal * 100
            y = trend.y(pct)
            trend.bars.append(TrendBar(round(left + offset * slot + slot * 0.18, 2), round(slot * 0.64, 2), y,
                                       round(bottom - y, 1)))
        window = [r for r in rows[max(0, i - TREND_WINDOW + 1): i + 1] if r.recorded]
        if len(window) >= TREND_MIN_DAYS:
            mean_kcal = sum(r.kcal_self for r in window) / len(window)
            latest = mean_kcal
            points.append(f"{round(centre, 1)},{trend.y(mean_kcal / goal * 100)}")
    if latest is None:
        return None
    trend.line = " ".join(points)
    trend.latest_kcal = latest
    trend.latest_pct = latest / goal * 100
    shown = [m for m in marks if start <= m.day <= end]
    trend.marks = [TrendMark(n, round(left + (m.day - start).days * slot + slot / 2, 1), m.day, m.label)
                   for n, m in enumerate(shown, start=1)]
    return trend


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


def compare_around(chat_id: int, subject: str, mark: Mark, today: date,
                   self_label: str = "сама") -> Comparison | None:
    before = (mark.day - timedelta(days=COMPARE_DAYS), mark.day - timedelta(days=1))
    after = (mark.day, min(mark.day + timedelta(days=COMPARE_DAYS - 1), today))
    if (after[1] - after[0]).days + 1 < COMPARE_MIN_AFTER:
        return None
    rows_before = [r for r in day_rows(chat_id, subject, *before) if r.recorded]
    rows_after = [r for r in day_rows(chat_id, subject, *after) if r.recorded]
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


def last_stool(chat_id: int, until: date) -> date | None:
    with db._connect() as conn:
        rows = conn.execute(
            "SELECT day, description FROM events WHERE chat_id = ? AND type = 'toilet' AND day <= ? "
            "ORDER BY occurred_at DESC",
            (chat_id, until.isoformat()),
        ).fetchall()
    return next((date.fromisoformat(r["day"]) for r in rows if db.toilet_kind(r["description"]) == "stool"), None)


@dataclass
class Breath:
    day: date
    time: str
    rate: float
    asleep: bool | None

    @property
    def high(self) -> bool:
        return bool(self.asleep) and self.rate > SLEEP_BREATHS_LIMIT


def breathing(chat_id: int, start: date, end: date) -> list[Breath]:
    rows = [r for r in db.events_in_days(chat_id, start, end) if r["type"] == "breathing" and r["breaths"]]
    return [Breath(date.fromisoformat(r["day"]), r["occurred_at"][11:16], r["breaths"],
                   None if r["asleep"] is None else bool(r["asleep"])) for r in reversed(rows)]
