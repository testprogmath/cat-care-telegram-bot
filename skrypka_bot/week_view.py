"""What the week page shows: shares, the mini charts, weight, the appetite trend, stool and breathing."""

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import classify, db, questions
from .daily import DayRow
from .meds_view import Mark

MINI_CHART_DAYS = 31
WEIGHT_STALE_DAYS = 7
SLEEP_BREATHS_LIMIT = 30
STOOL_WARN_DAYS = 2
TREND_WINDOW = 7
TREND_MIN_DAYS = 4


@dataclass
class Share:
    """Two parts of one total, as fractions of a bar 100 units wide."""

    first: float
    second: float

    @classmethod
    def of(cls, first: float, second: float, goal: float) -> Share:
        scale = max(goal, first + second, 1)
        return cls(round(first / scale * 100, 1), round(second / scale * 100, 1))


@dataclass
class Share3:
    """Three parts of one total on a bar 100 units wide, with where each part starts."""

    widths: tuple[float, float, float]

    @classmethod
    def of(cls, parts: tuple[float, float, float], goal: float) -> Share3:
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
    scores: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class MiniChart:
    width: float
    height: int
    goal_y: float
    bars: list[MiniBar]
    labelled: bool
    toilet: list[ToiletBar] = field(default_factory=list)
    toilet_height: int = 0
    score_rows: int = 0


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
            scores=[(score, questions.stool_tone(score)) for score in getattr(r, "stool_scores", [])],
        ))
    return MiniChart(toilet=toilet, toilet_height=int(toilet_top + toilet_height),
                     score_rows=max((len(t.scores) for t in toilet), default=0),
                     width=width, height=int(top + height), goal_y=round(top + height - goal * scale, 1),
                     bars=bars, labelled=len(rows) <= 14)


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


def _weighings(subject: str, until: date) -> list[Weighing]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT day, weight_kg FROM events WHERE subject = ? AND type = 'weight' AND weight_kg > 0 "
            "AND day <= ? ORDER BY occurred_at",
            (subject, until.isoformat()),
        ).fetchall()
    return [Weighing(date.fromisoformat(r["day"]), r["weight_kg"]) for r in rows]


def weight_summary(subject: str, start: date, end: date, today: date) -> WeightSummary | None:
    weighings = _weighings(subject, end)
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


def last_stool(subject: str, until: date) -> date | None:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT day, description FROM events WHERE subject = ? AND type = 'toilet' AND day <= ? "
            "ORDER BY occurred_at DESC",
            (subject, until.isoformat()),
        ).fetchall()
    return next((date.fromisoformat(r["day"]) for r in rows if classify.toilet_kind(r["description"]) == "stool"), None)


@dataclass
class Breath:
    day: date
    time: str
    rate: float
    asleep: bool | None

    @property
    def high(self) -> bool:
        return bool(self.asleep) and self.rate > SLEEP_BREATHS_LIMIT


def breathing(subject: str, start: date, end: date) -> list[Breath]:
    rows = [r for r in db.events_in_days(subject, start, end) if r["type"] == "breathing" and r["breaths"]]
    return [Breath(date.fromisoformat(r["day"]), r["occurred_at"][11:16], r["breaths"],
                   None if r["asleep"] is None else bool(r["asleep"])) for r in reversed(rows)]
