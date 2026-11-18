import io
import math
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from . import classify, db, figures, meds, questions  # noqa: E402
from .profiles import Profile  # noqa: E402

WEEK_DAYS = 7
SEGMENT_LABEL_DAYS = 14
TOTAL_LABEL_DAYS = 31

STOOL_TONES = {"ok": "#3B7A57", "warn": "#C08A1E", "bad": "#C9563F"}
TICKS_PER_CHART = 14

PAGE, CARD, INK, MUTED, GRID = "#F6F1EA", "#FFFFFF", "#2B2A28", "#8A847B", "#EEE8DF"
GOAL, MET = "#E0675A", "#3B7A57"
HEADER_IN, PANEL_IN = 2.0, 3.25


def _stack(ax, x: list[int], segments: list[tuple[list[float], str, str]], goal: float | None = None) -> None:
    bottom = [0.0] * len(x)
    stacked = []
    for values, label, color in segments:
        bars = ax.bar(x, values, 0.64, bottom=bottom, label=label, color=color, zorder=3)
        if not any(values):
            bars.set_label("_nolegend_")
        stacked.append((bars, values))
        bottom = [b + v for b, v in zip(bottom, values, strict=True)]
    totals = bottom
    if len(totals) <= SEGMENT_LABEL_DAYS:
        smallest = max(totals, default=0) * 0.06
        for bars, values in stacked:
            ax.bar_label(
                bars, labels=[f"{v:.0f}" if v >= smallest and v > 0 else "" for v in values],
                label_type="center", fontsize=8, color="white",
            )
    if len(totals) <= TOTAL_LABEL_DAYS:
        texts = ax.bar_label(
            stacked[-1][0], labels=[f"{t:.0f}" if t > 0 else "" for t in totals],
            padding=3, fontsize=9 if len(totals) <= SEGMENT_LABEL_DAYS else 7, fontweight="bold", color=INK,
        )
        if goal:
            for text, total in zip(texts, totals, strict=True):
                if total >= goal:
                    text.set_color(MET)


def _day_axis(ax, x: list[int], days: list[date]) -> None:
    step = max(1, math.ceil(len(x) / TICKS_PER_CHART))
    ax.set_xticks(x[::step])
    if len(days) <= SEGMENT_LABEL_DAYS:
        ax.set_xticklabels([f"{d.strftime('%a')[:2]}\n{d.day}" for d in days])
    else:
        ax.set_xticklabels([d.strftime("%d.%m") for d in days][::step],
                           rotation=45 if step > 1 else 0, ha="right" if step > 1 else "center")


def _panel(ax, title: str, subtitle: str) -> None:
    ax.set_facecolor(CARD)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)
    ax.grid(axis="y", color=GRID, lw=1)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK, pad=26)
    ax.annotate(subtitle, (0, 1), xycoords="axes fraction", xytext=(0, 9), textcoords="offset points",
                fontsize=9.5, color=MUTED)


def _goal(ax, goal: float) -> None:
    ax.axhline(goal, ls=(0, (4, 3)), lw=1.4, color=GOAL, zorder=4)
    ax.annotate(f"goal {goal:g}", (1, goal), xycoords=("axes fraction", "data"), xytext=(4, 0),
                textcoords="offset points", va="center", fontsize=8.5, fontweight="bold", color=GOAL)


def _legend(ax) -> None:
    if ax.get_legend_handles_labels()[0]:
        ax.legend(loc="lower right", bbox_to_anchor=(1, 1.02), ncol=5, frameon=False, fontsize=8.5,
                  labelcolor=MUTED, handlelength=0.9, handleheight=0.9, columnspacing=1.2)


def _header(ax, profile: Profile, start: date, end_day: date, tiles: list[tuple[str, str, str, str]]) -> None:
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0, 1, profile.name_en, fontsize=24, fontweight="bold", color=INK, va="top")
    ax.text(0, 0.72, f"{start.strftime('%-d %b')} – {end_day.strftime('%-d %b %Y')}", fontsize=11,
            color=MUTED, va="top")
    gap = 0.02
    width = (1 - gap * (len(tiles) - 1)) / len(tiles)
    for i, (label, value, unit, color) in enumerate(tiles):
        x = i * (width + gap)
        ax.add_patch(FancyBboxPatch((x, 0), width, 0.5, boxstyle="round,pad=0,rounding_size=0.012",
                                    mutation_aspect=ax.figure.get_figwidth() / HEADER_IN, fc=CARD, ec="none"))
        ax.text(x + 0.015, 0.4, label.upper(), fontsize=8, color=MUTED, va="center")
        ax.text(x + 0.015, 0.21, value, fontsize=22, fontweight="bold", color=color, va="center")
        ax.text(x + 0.015, 0.06, unit, fontsize=8, color=MUTED, va="center")


def _cards(fig, axes) -> None:
    """Freeze the layout and lay a white card under each panel, its title and legend included."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    to_fig = fig.transFigure.inverted()
    fig.set_layout_engine("none")
    pad = 14
    boxes = [ax.get_tightbbox(renderer) for ax in axes]
    left, right = min(b.x0 for b in boxes) - pad, max(b.x1 for b in boxes) + pad
    for box in boxes:
        (x0, y0), (x1, y1) = to_fig.transform([(left, box.y0 - pad), (right, box.y1 + pad)])
        fig.patches.append(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=0.012",
                                          mutation_aspect=fig.get_figwidth() / fig.get_figheight(),
                                          transform=fig.transFigure, fc=CARD, ec="none", zorder=-1))


def _round_tops(ax, radius_px: float = 6) -> None:
    """Round the top corners of each bar, a stacked bar as a whole."""
    box = ax.get_window_extent()
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    px_x, px_y = box.width / (x1 - x0), box.height / (y1 - y0)
    columns: dict[float, list] = {}
    for container in ax.containers:
        for bar in getattr(container, "patches", []):
            if bar.get_height() > 0:
                columns.setdefault(round(bar.get_x(), 6), []).append(bar)
    for left, bars in columns.items():
        width = bars[0].get_width()
        r = min(radius_px / px_x, width / 2)
        aspect = px_x / px_y
        top = max(b.get_y() + b.get_height() for b in bars)
        clip = FancyBboxPatch((left, -2 * r * aspect), width, top + 2 * r * aspect,
                              boxstyle=f"round,pad=0,rounding_size={r}", mutation_aspect=aspect,
                              transform=ax.transData, fc="none", ec="none")
        ax.add_patch(clip)
        for bar in bars:
            bar.set_clip_path(clip)


def render_week(end_day: date, profile: Profile) -> bytes:
    return render_days(end_day - timedelta(days=WEEK_DAYS - 1), end_day, profile)


def render_days(start: date, end_day: date, profile: Profile) -> bytes:
    water_goal = profile.water_goal_ml
    kcal_goal = profile.kcal_goal
    days = [start + timedelta(days=i) for i in range((end_day - start).days + 1)]
    rows = db.events_in_days(profile.subject_id, days[0], days[-1])

    drank = {d: 0.0 for d in days}
    given = {d: 0.0 for d in days}
    infused = {d: 0.0 for d in days}
    liquid_water = {d: 0.0 for d in days}
    kcal_tube = {d: 0.0 for d in days}
    kcal_wet = {d: 0.0 for d in days}
    kcal_dry = {d: 0.0 for d in days}
    urine = {d: 0 for d in days}
    stool = {d: 0 for d in days}
    scores: dict[date, list[int]] = {d: [] for d in days}
    temps: list[tuple[datetime, float]] = []
    recorded: set[date] = set()

    for r in rows:
        d = date.fromisoformat(r["day"])
        if d not in drank:
            continue
        recorded.add(d)
        t = r["type"]
        if t == "water":
            parts = {"drank": drank, "given": given, "infusion": infused}
            parts[figures.water_source(r)][d] += r["water_ml"] or 0
        elif t == "food":
            liquid_water[d] += figures.food_water_ml(r)
            if figures.is_given(r):
                kcal_tube[d] += r["kcal"] or 0
            elif r["liquid"]:
                kcal_wet[d] += r["kcal"] or 0
            else:
                kcal_dry[d] += r["kcal"] or 0
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

    water = {d: drank[d] + given[d] + liquid_water[d] + infused[d] for d in days}
    kcal = {d: kcal_tube[d] + kcal_wet[d] + kcal_dry[d] for d in days}
    n = len(recorded) or 1
    avg_water = sum(water[d] for d in recorded) / n
    avg_kcal = sum(kcal[d] for d in recorded) / n
    all_scores = [s for d in days for s in scores[d]]
    tiles = [
        ("water / day", f"{avg_water:.0f}", f"ml · goal {water_goal:g}", MET if avg_water >= water_goal else GOAL),
        ("calories / day", f"{avg_kcal:.0f}", f"kcal · goal {kcal_goal:g}", MET if avg_kcal >= kcal_goal else GOAL),
        ("water goal met", f"{sum(water[d] >= water_goal for d in recorded)}/{len(recorded)}", "days", INK),
        ("stool score", f"{sum(all_scores) / len(all_scores):.1f}" if all_scores else "–",
         "average · 4 is normal", INK),
    ]

    x = list(range(len(days)))
    panels = 4 if temps else 3
    fig, axes = plt.subplots(
        panels + 1, 1, figsize=(min(18, max(10, len(days) * 0.3)), HEADER_IN + PANEL_IN * panels),
        height_ratios=[HEADER_IN] + [PANEL_IN] * panels, facecolor=PAGE,
        layout="constrained",
    )
    fig.get_layout_engine().set(h_pad=0.25, hspace=0.06, w_pad=0.3)
    _header(axes[0], profile, start, end_day, tiles)
    axes = axes[1:]

    ax = axes[0]
    _panel(ax, "Water per day, ml", f"average {avg_water:.0f} ml a day · goal {water_goal:g} ml")
    _stack(ax, x, [
        ([drank[d] for d in days], "drank", "#5AA9E6"),
        ([given[d] for d in days], "given by mouth or tube", "#2F6FB0"),
        ([liquid_water[d] for d in days], "from wet food", "#9BD6B4"),
        ([infused[d] for d in days], "infusion (under the skin or IV)", "#B79CE0"),
    ], water_goal)
    _goal(ax, water_goal)
    _day_axis(ax, x, days)
    _legend(ax)

    ax = axes[1]
    _panel(ax, "Calories per day, kcal", f"average {avg_kcal:.0f} kcal a day · goal {kcal_goal:g} kcal")
    _stack(ax, x, [
        ([kcal_tube[d] for d in days], "tube", "#8C7AE6"),
        ([kcal_wet[d] for d in days], "wet food", "#4FB3A2"),
        ([kcal_dry[d] for d in days], "dry food", "#F2B84B"),
    ], kcal_goal)
    _goal(ax, kcal_goal)
    _day_axis(ax, x, days)
    _legend(ax)

    ax = axes[2]
    has_scores = any(scores.values())
    _panel(ax, "Litter box, times per day",
           "stool score in the dot: 1 liquid · 2 slimy · 3 mushy · 4 normal · 5 hard" if has_scores else "")
    w = 0.32
    for offset, counts, label, color in (
        (-w / 2 - 0.02, [urine[d] for d in days], "urine", "#5AA9E6"),
        (w / 2 + 0.02, [stool[d] for d in days], "stool", "#B98450"),
    ):
        bars = ax.bar([i + offset for i in x], counts, w, label=label, color=color, zorder=3)
        if len(days) <= TOTAL_LABEL_DAYS:
            ax.bar_label(bars, labels=[str(n) if n else "" for n in counts], padding=2, fontsize=8, color=MUTED)
    if len(days) <= TOTAL_LABEL_DAYS:
        for i, d in enumerate(days):
            for row, score in enumerate(scores[d]):
                ax.text(i + w / 2 + 0.02, 0.15 + row * 0.5, str(score), ha="center", va="bottom", fontsize=8,
                        fontweight="bold", color="white", zorder=5,
                        bbox={"boxstyle": "circle,pad=0.25", "fc": STOOL_TONES[questions.stool_tone(score)],
                              "ec": "white", "lw": 1.2})
    _day_axis(ax, x, days)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    _legend(ax)

    if temps:
        ax = axes[3]
        _panel(ax, "Temperature, °C", "normal 38.0–39.2 °C")
        temps.sort()
        home = [(t, v) for t, v, d in temps if "клиник" not in d]
        clinic = [(t, v) for t, v, d in temps if "клиник" in d]
        ax.axhspan(38.0, 39.2, color="#E4F1E4", label="normal 38.0–39.2")
        if home:
            ax.plot([t for t, _ in home], [v for _, v in home], marker="o", color=GOAL, label="home", zorder=3)
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
        _legend(ax)

    for ax in axes[:3]:
        ax.set_xlim(-0.6, len(days) - 0.4)
    axes[0].set_ylim(0, max(max(water.values()), water_goal) * 1.2)
    axes[1].set_ylim(0, max(max(kcal.values()), kcal_goal, 1) * 1.2)
    axes[2].set_ylim(0, max((max(urine[d], stool[d]) for d in days), default=0) * 1.3 + 1)

    _cards(fig, axes)
    for ax in axes[:3]:
        _round_tops(ax, 6 if ax is not axes[2] else 4)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=PAGE)
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
