import io
import math
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from . import classify, db, figures, meds, questions  # noqa: E402
from .profiles import Profile  # noqa: E402

WEEK_DAYS = 7
SEGMENT_LABEL_DAYS = 14
TOTAL_LABEL_DAYS = 31

STOOL_TONES = {"ok": "#3B7A57", "warn": "#C08A1E", "bad": "#C9563F"}
TICKS_PER_CHART = 14


def _stack(ax, x: list[int], segments: list[tuple[list[float], str, str]]) -> None:
    bottom = [0.0] * len(x)
    stacked = []
    for values, label, color in segments:
        stacked.append((ax.bar(x, values, bottom=bottom, label=label, color=color), values))
        bottom = [b + v for b, v in zip(bottom, values, strict=True)]
    totals = bottom
    if len(totals) <= SEGMENT_LABEL_DAYS:
        smallest = max(totals, default=0) * 0.06
        for bars, values in stacked:
            ax.bar_label(
                bars, labels=[f"{v:.0f}" if v >= smallest and v > 0 else "" for v in values],
                label_type="center", fontsize=8,
            )
    if len(totals) <= TOTAL_LABEL_DAYS:
        ax.bar_label(
            stacked[-1][0], labels=[f"{t:.0f}" if t > 0 else "" for t in totals],
            padding=2, fontsize=9 if len(totals) <= SEGMENT_LABEL_DAYS else 7, fontweight="bold",
        )


def _day_axis(ax, x: list[int], labels: list[str]) -> None:
    step = max(1, math.ceil(len(x) / TICKS_PER_CHART))
    ax.set_xticks(x[::step])
    ax.set_xticklabels(labels[::step], rotation=45 if step > 1 else 0, ha="right" if step > 1 else "center")


def render_week(end_day: date, profile: Profile) -> bytes:
    start = end_day - timedelta(days=WEEK_DAYS - 1)
    return render_days(start, end_day, profile,
                       f"{profile.name_en}: week to {end_day.strftime('%d.%m.%Y')}")


def render_days(start: date, end_day: date, profile: Profile, title: str = "") -> bytes:
    water_goal = profile.water_goal_ml
    days = [start + timedelta(days=i) for i in range((end_day - start).days + 1)]
    rows = db.events_in_days(profile.subject_id, days[0], days[-1])

    drank = {d: 0.0 for d in days}
    given = {d: 0.0 for d in days}
    infused = {d: 0.0 for d in days}
    liquid_water = {d: 0.0 for d in days}
    kcal_tube = {d: 0.0 for d in days}
    kcal_self = {d: 0.0 for d in days}
    urine = {d: 0 for d in days}
    stool = {d: 0 for d in days}
    scores: dict[date, list[int]] = {d: [] for d in days}
    temps: list[tuple[datetime, float]] = []

    for r in rows:
        d = date.fromisoformat(r["day"])
        if d not in drank:
            continue
        t = r["type"]
        if t == "water":
            parts = {"drank": drank, "given": given, "infusion": infused}
            parts[figures.water_source(r)][d] += r["water_ml"] or 0
        elif t == "food":
            liquid_water[d] += figures.food_water_ml(r)
            if figures.is_given(r):
                kcal_tube[d] += r["kcal"] or 0
            else:
                kcal_self[d] += r["kcal"] or 0
        elif t == "toilet":
            kind = classify.toilet_kind(r["description"])
            if kind == "stool":
                stool[d] += 1
                if r["stool_score"]:
                    scores[d].append(r["stool_score"])
            elif kind == "urine":
                urine[d] += 1
        elif t == "temperature" and r["temp_c"] is not None:
            temps.append(
                (datetime.fromisoformat(r["occurred_at"]), r["temp_c"], (r["description"] or "").lower())
            )

    labels = [d.strftime("%d.%m") for d in days]
    x = list(range(len(days)))

    panels = 4 if temps else 3
    fig, axes = plt.subplots(panels, 1, figsize=(min(18, max(9, len(days) * 0.3)), 3.25 * panels),
                             constrained_layout=True)
    fig.suptitle(
        title or f"{profile.name_en}: {start.strftime('%d.%m')}–{end_day.strftime('%d.%m.%Y')}",
        fontsize=15,
        fontweight="bold",
    )

    ax = axes[0]
    _stack(ax, x, [
        ([drank[d] for d in days], "drank", "#4C9BE8"),
        ([given[d] for d in days], "given by mouth or tube", "#2B5F9E"),
        ([liquid_water[d] for d in days], "from wet food", "#9BD1A0"),
        ([infused[d] for d in days], "infusion (under the skin or IV)", "#A77BCA"),
    ])
    ax.axhline(water_goal, ls="--", color="#E8635C", label=f"goal {water_goal:g} ml")
    ax.set_title("Water per day, ml")
    _day_axis(ax, x, labels)
    ax.legend(fontsize=8, loc="upper left", ncol=5, frameon=False)

    ax = axes[1]
    _stack(ax, x, [
        ([kcal_tube[d] for d in days], "tube", "#7B6CE8"),
        ([kcal_self[d] for d in days], "self-fed", "#E8B54C"),
    ])
    ax.set_title("Calories per day, kcal")
    _day_axis(ax, x, labels)
    ax.legend(fontsize=8, loc="upper left", ncol=3, frameon=False)

    ax = axes[2]
    w = 0.38
    for offset, counts, label, color in (
        (-w / 2, [urine[d] for d in days], "urine", "#4C9BE8"),
        (w / 2, [stool[d] for d in days], "stool", "#B5793B"),
    ):
        bars = ax.bar([i + offset for i in x], counts, w, label=label, color=color)
        if len(days) <= TOTAL_LABEL_DAYS:
            ax.bar_label(bars, labels=[str(n) if n else "" for n in counts], padding=2, fontsize=8)
    if len(days) <= TOTAL_LABEL_DAYS:
        for i, d in enumerate(days):
            for row, score in enumerate(scores[d]):
                ax.text(i + w / 2, 0.15 + row * 0.45, str(score), ha="center", va="bottom", fontsize=8,
                        fontweight="bold", color="white",
                        bbox={"boxstyle": "round,pad=0.2", "fc": STOOL_TONES[questions.stool_tone(score)], "ec": "white", "lw": 1.2})
    has_scores = any(scores.values())
    ax.set_title("Litter box, times per day"
                 + ("; stool score in the stool bar: 1 liquid · 2 slimy · 3 mushy · 4 normal · 5 hard" if has_scores else ""))
    _day_axis(ax, x, labels)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.legend(fontsize=8, loc="upper left", ncol=3, frameon=False)

    if temps:
        ax = axes[3]
        ax.set_title("Temperature, °C")
        temps.sort()
        home = [(t, v) for t, v, d in temps if "клиник" not in d]
        clinic = [(t, v) for t, v, d in temps if "клиник" in d]
        ax.axhspan(38.0, 39.2, color="#DFF0DF", label="normal 38.0–39.2")
        if home:
            ax.plot([t for t, _ in home], [v for _, v in home], marker="o", color="#E8635C", label="home")
        if clinic:
            ax.scatter(
                [t for t, _ in clinic], [v for _, v in clinic],
                marker="X", s=70, color="#E8A33C", zorder=5, label="clinic",
            )
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        ax.set_xlim(
            datetime.combine(days[0], datetime.min.time()),
            datetime.combine(end_day, datetime.max.time()),
        )
        ax.legend(fontsize=8, loc="upper left", ncol=3, frameon=False)

    water_top = max(drank[d] + given[d] + liquid_water[d] + infused[d] for d in days)
    axes[0].set_ylim(0, max(water_top, water_goal) * 1.3)
    axes[1].set_ylim(0, max(max(kcal_tube[d] + kcal_self[d] for d in days), 1) * 1.3)
    axes[2].set_ylim(0, max((max(urine[d], stool[d]) for d in days), default=0) * 1.3 + 1)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue()


def render_meds(rows: list, day_from: date, day_to: date, profile: Profile) -> bytes:
    courses = meds.courses(rows)
    span = (day_to - day_from).days + 1
    fig, axes = plt.subplots(
        len(courses), 1, sharex=True, squeeze=False,
        figsize=(max(9, span * 0.16), 0.8 + 1.0 * len(courses)), constrained_layout=True,
    )
    fig.suptitle(
        f"{profile.name_en}: medications {day_from.strftime('%d.%m')}–{day_to.strftime('%d.%m.%Y')}",
        fontsize=14,
        fontweight="bold",
    )

    for ax, course in zip(axes[:, 0], courses, strict=True):
        points = [
            (day, amount)
            for day, doses in sorted(course.doses_on.items())
            for amount in sorted({meds.dose_amount(d) for d in doses}, key=lambda a: (a is None, a or 0))
        ]
        measured = [(day, amount) for day, amount in points if amount is not None]
        unmeasured = [day for day, amount in points if amount is None]
        values = sorted({amount for _, amount in measured})
        if measured:
            ax.plot([d for d, _ in measured], [a for _, a in measured], "o", ms=5, color="#7B6CE8")
            ax.set_yticks(values if len(values) <= 6 else [values[0], values[-1]])
            ax.yaxis.set_major_formatter(lambda v, _: f"{v:g}")
            pad = (values[-1] - values[0]) * 0.25 or values[0] * 0.25 or 1
            ax.set_ylim(values[0] - pad, values[-1] + pad)
        else:
            ax.set_yticks([])
        if unmeasured:
            base = values[0] if values else 0
            ax.plot(unmeasured, [base] * len(unmeasured), "o", ms=5, mfc="none", color="#7B6CE8")
        for day, count in course.days.items():
            if count > 1:
                top = max((a for d, a in measured if d == day), default=values[0] if values else 0)
                ax.annotate(
                    f"×{count}", (day, top), xytext=(0, 5), textcoords="offset points",
                    ha="center", fontsize=7, color="#444444",
                )
        unit = meds.dose_unit(course)
        ax.set_ylabel(
            meds.label_en(course.drug) + (f"\n{unit}" if unit else ""),
            rotation=0, ha="right", va="center", fontsize=9,
        )
        ax.grid(axis="x", color="#E5E5E5")
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)

    ax = axes[-1, 0]
    start = datetime.combine(day_from, datetime.min.time())
    ax.set_xlim(start - timedelta(hours=12), start + timedelta(days=span - 0.5))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=12))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    fig.supxlabel("hollow dot: dose not recorded · ×2: given twice that day", fontsize=8, color="#666666")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue()
