import io
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from . import db  # noqa: E402
from .profiles import Profile  # noqa: E402

WEEK_DAYS = 7


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
        f"{profile.name} — неделя по {end_day.strftime('%d.%m.%Y')}",
        fontsize=15,
        fontweight="bold",
    )

    ax = axes[0]
    dw = [drink[d] for d in days]
    lw = [liquid_water[d] for d in days]
    ax.bar(x, dw, label="вода (питьё)", color="#4C9BE8")
    ax.bar(x, lw, bottom=dw, label="вода из жидкого корма (85%)", color="#9BD1A0")
    ax.axhline(water_goal, ls="--", color="#E8635C", label=f"цель {water_goal:g} мл")
    ax.set_title("Вода в сутки, мл")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(fontsize=8, loc="upper left")

    ax = axes[1]
    kt = [kcal_tube[d] for d in days]
    ks = [kcal_self[d] for d in days]
    ax.bar(x, kt, label="зонд", color="#7B6CE8")
    ax.bar(x, ks, bottom=kt, label=profile.self_label, color="#E8B54C")
    ax.set_title("Калории в сутки, ккал")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend(fontsize=8, loc="upper left")

    ax = axes[2]
    w = 0.38
    ax.bar([i - w / 2 for i in x], [urine[d] for d in days], w, label="моча", color="#4C9BE8")
    ax.bar([i + w / 2 for i in x], [stool[d] for d in days], w, label="кал", color="#B5793B")
    ax.set_title("Туалет, раз в сутки")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.legend(fontsize=8, loc="upper left")

    ax = axes[3]
    ax.set_title("Температура, °C")
    if temps:
        temps.sort()
        home = [(t, v) for t, v, d in temps if "клиник" not in d]
        clinic = [(t, v) for t, v, d in temps if "клиник" in d]
        ax.axhspan(38.0, 39.2, color="#DFF0DF", label="норма 38,0–39,2")
        if home:
            ax.plot([t for t, _ in home], [v for _, v in home], marker="o", color="#E8635C", label="дома")
        if clinic:
            ax.scatter(
                [t for t, _ in clinic], [v for _, v in clinic],
                marker="X", s=70, color="#E8A33C", zorder=5, label="клиника",
            )
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        ax.set_xlim(
            datetime.combine(days[0], datetime.min.time()),
            datetime.combine(end_day, datetime.max.time()),
        )
        ax.legend(fontsize=8, loc="upper left")
    else:
        ax.text(0.5, 0.5, "нет измерений температуры", ha="center", va="center", transform=ax.transAxes)
        ax.set_yticks([])

    axes[0].set_ylim(0, max(max(drink[d] + liquid_water[d] for d in days), water_goal) * 1.18)
    axes[1].set_ylim(0, max(max(kcal_tube[d] + kcal_self[d] for d in days), 1) * 1.18)
    axes[2].set_ylim(0, max((max(urine[d], stool[d]) for d in days), default=0) + 1)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue()
