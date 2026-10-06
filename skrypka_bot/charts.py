import io
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from . import db, meds  # noqa: E402
from .profiles import Profile  # noqa: E402

WEEK_DAYS = 7


def _label_stack(ax, lower, upper, lower_values, upper_values) -> None:
    totals = [a + b for a, b in zip(lower_values, upper_values)]
    smallest = max(totals, default=0) * 0.06
    for bars, values in ((lower, lower_values), (upper, upper_values)):
        ax.bar_label(
            bars, labels=[f"{v:.0f}" if v >= smallest and v > 0 else "" for v in values],
            label_type="center", fontsize=8,
        )
    ax.bar_label(
        upper, labels=[f"{t:.0f}" if t > 0 else "" for t in totals],
        padding=2, fontsize=9, fontweight="bold",
    )


def render_week(chat_id: int, end_day: date, profile: Profile) -> bytes:
    water_goal = profile.water_goal_ml
    days = [end_day - timedelta(days=i) for i in range(WEEK_DAYS - 1, -1, -1)]
    rows = db.events_in_days(chat_id, days[0], days[-1])

    drink = {d: 0.0 for d in days}
    liquid_water = {d: 0.0 for d in days}
    kcal_tube = {d: 0.0 for d in days}
    kcal_self = {d: 0.0 for d in days}
    urine = {d: 0 for d in days}
    stool = {d: 0 for d in days}
    temps: list[tuple[datetime, float]] = []

    for r in rows:
        d = date.fromisoformat(r["day"])
        if d not in drink:
            continue
        t = r["type"]
        if t == "water":
            drink[d] += r["water_ml"] or 0
        elif t == "food":
            liquid_water[d] += db.food_water_ml(r)
            if r["feeding"] == "tube":
                kcal_tube[d] += r["kcal"] or 0
            else:
                kcal_self[d] += r["kcal"] or 0
        elif t == "toilet":
            if db.is_stool(r["description"]):
                stool[d] += 1
            else:
                urine[d] += 1
        elif t == "temperature" and r["temp_c"] is not None:
            temps.append(
                (datetime.fromisoformat(r["occurred_at"]), r["temp_c"], (r["description"] or "").lower())
            )

    labels = [d.strftime("%d.%m") for d in days]
    x = list(range(len(days)))

    fig, axes = plt.subplots(4, 1, figsize=(9, 13), constrained_layout=True)
    fig.suptitle(
        f"{profile.name_en}: week to {end_day.strftime('%d.%m.%Y')}",
        fontsize=15,
        fontweight="bold",
    )

    ax = axes[0]
    dw = [drink[d] for d in days]
    lw = [liquid_water[d] for d in days]
    drink_bars = ax.bar(x, dw, label="water (drinking)", color="#4C9BE8")
    food_bars = ax.bar(x, lw, bottom=dw, label="water from wet food", color="#9BD1A0")
    _label_stack(ax, drink_bars, food_bars, dw, lw)
    ax.axhline(water_goal, ls="--", color="#E8635C", label=f"goal {water_goal:g} ml")
    ax.set_title("Water per day, ml")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(fontsize=8, loc="upper left")

    ax = axes[1]
    kt = [kcal_tube[d] for d in days]
    ks = [kcal_self[d] for d in days]
    tube_bars = ax.bar(x, kt, label="tube", color="#7B6CE8")
    self_bars = ax.bar(x, ks, bottom=kt, label="self-fed", color="#E8B54C")
    _label_stack(ax, tube_bars, self_bars, kt, ks)
    ax.set_title("Calories per day, kcal")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(fontsize=8, loc="upper left")

    ax = axes[2]
    w = 0.38
    for offset, counts, label, color in (
        (-w / 2, [urine[d] for d in days], "urine", "#4C9BE8"),
        (w / 2, [stool[d] for d in days], "stool", "#B5793B"),
    ):
        bars = ax.bar([i + offset for i in x], counts, w, label=label, color=color)
        ax.bar_label(bars, labels=[str(n) if n else "" for n in counts], padding=2, fontsize=8)
    ax.set_title("Litter box, times per day")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.legend(fontsize=8, loc="upper left")

    ax = axes[3]
    ax.set_title("Temperature, °C")
    if temps:
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
        ax.legend(fontsize=8, loc="upper left")
    else:
        ax.text(0.5, 0.5, "no temperature readings", ha="center", va="center", transform=ax.transAxes)
        ax.set_yticks([])

    axes[0].set_ylim(0, max(max(drink[d] + liquid_water[d] for d in days), water_goal) * 1.18)
    axes[1].set_ylim(0, max(max(kcal_tube[d] + kcal_self[d] for d in days), 1) * 1.18)
    axes[2].set_ylim(0, max((max(urine[d], stool[d]) for d in days), default=0) + 1)

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

    for ax, course in zip(axes[:, 0], courses):
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
