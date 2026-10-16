import re
import sqlite3
from datetime import date, datetime, timedelta

from . import classify, db, figures, fmt, questions
from .parser import condense_states
from .profiles import Bands, Profile

CONDENSE_THRESHOLD = 6
STREAK_LOOKBACK_DAYS = 3


def _feeding_labels(profile: Profile) -> dict[str, str]:
    return {"tube": "зонд" if profile.tube else "дали", "self": profile.self_label}


def _kcal_totals(food: list[sqlite3.Row]) -> tuple[float, dict[str, float], int, int]:
    total = 0.0
    by_feeding = {"tube": 0.0, "self": 0.0}
    unquantified = 0
    gravy = 0
    for e in food:
        kcal = e["kcal"]
        if not kcal:
            if e["liquid"] and e["amount_ml"]:
                gravy += 1
            else:
                unquantified += 1
            continue
        total += kcal
        by_feeding["tube" if figures.is_given(e) else "self"] += kcal
    return total, by_feeding, unquantified, gravy


def _kcal_split(by_feeding: dict[str, float], labels: dict[str, str]) -> str:
    return ", ".join(f"{labels[key]} ~{fmt.num(value)}" for key, value in by_feeding.items() if value)


def _wet_note(count: int) -> str:
    return (
        f"  ещё {count} {_plural_episodes(count)} влажного корма без количества — "
        "в зачёт воды не пошли"
    )


def _time_of(row: sqlite3.Row) -> str:
    return datetime.fromisoformat(row["occurred_at"]).strftime("%H:%M")


_KCAL_PAREN_RE = re.compile(
    r"\s*\(\s*[~≈]?\s*\d+(?:[.,]\d+)?\s*(?:ккал|kcal)\s*\)", re.IGNORECASE
)


def _strip_kcal(text: str) -> str:
    return _KCAL_PAREN_RE.sub("", text).strip()


SLEEP_BREATHS_LIMIT = 30
WEIGHING_INTERVAL_DAYS = 7


def weighing_reminder(last: tuple[date, float] | None, today: date) -> str | None:
    if last is None:
        return "⚖️ Взвешиваний в дневнике ещё нет. Взвесьте, пожалуйста, и напишите вес в чат."
    day, kg = last
    ago = (today - day).days
    if ago < WEIGHING_INTERVAL_DAYS:
        return None
    return (f"⚖️ Последнее взвешивание {day.strftime('%d.%m')}, {kg:g} кг — "
            f"{ago} {fmt.plural(ago, 'день', 'дня', 'дней')} назад. Пора взвесить.")


def _plural_episodes(n: int) -> str:
    return fmt.plural(n, "эпизод", "эпизода", "эпизодов")


def _remaining(left: float) -> str:
    return f"осталось {fmt.num(left)}" if left > 0 else "цель достигнута"


def _uncounted_note(count: int) -> str:
    if not count:
        return ""
    return f"плюс {count} {_plural_episodes(count)} без количества"


def _gravy_note(count: int) -> str:
    if not count:
        return ""
    return f"плюс {count} {fmt.plural(count, 'подливка', 'подливки', 'подливок')} без калорий, вода зачтена"


def _kcal_details(
    by_feeding: dict[str, float], unquantified: int, gravy: int, labels: dict[str, str]
) -> str:
    parts = (_kcal_split(by_feeding, labels), _uncounted_note(unquantified), _gravy_note(gravy))
    return ", ".join(p for p in parts if p)


def render_progress(events: list[sqlite3.Row], now: datetime, profile: Profile) -> str:
    header = f"📈 {profile.name} — итог на {now.strftime('%H:%M')} (сутки с {db.DAY_START})"
    if not events:
        return f"{header}\nЗаписей пока нет."

    water_goal = profile.water_goal_ml
    kcal_goal = profile.kcal_goal
    food = [e for e in events if e["type"] == "food"]
    drink = sum(e["water_ml"] or 0 for e in events if e["type"] == "water")
    water = figures.effective_water(events)
    total_kcal, kcal_by_feeding, unquantified, gravy = _kcal_totals(food)

    lines = [
        header,
        f"\n💧 Вода: {fmt.num(water)} из {water_goal:g} мл — {_remaining(water_goal - water)}",
        f"  питьё {fmt.num(drink)} + из корма {fmt.num(water - drink)}",
    ]
    missed_wet = figures.uncounted_wet(events)
    if missed_wet:
        lines.append(_wet_note(missed_wet))
    lines += [
        f"\n🍗 Калории: ~{fmt.num(total_kcal)} из {kcal_goal:g} — "
        f"{_remaining(kcal_goal - total_kcal)}",
    ]
    details = _kcal_details(kcal_by_feeding, unquantified, gravy, _feeding_labels(profile))
    if details:
        lines.append(f"  {details}")
    return "\n".join(lines)


def vomited(events: list[sqlite3.Row]) -> bool:
    return any(
        classify.reports_vomiting(e["description"])
        for e in events
        if e["type"] in ("state", "other")
    )


def _low_kcal_streak(subject: str, day: date, threshold: float) -> int:
    streak = 0
    for back in range(STREAK_LOOKBACK_DAYS):
        events = db.events_for_day(subject, day - timedelta(days=back))
        if not events or figures.kcal_total(events) >= threshold:
            break
        streak += 1
    return streak


def _verdict(bands: Bands, value: float) -> str:
    if value >= bands.target_low:
        return "✅ в цели"
    if value >= bands.alarm:
        return "🟡 ниже цели"
    if value >= bands.severe:
        return "🟠 тревога"
    return "🔴 серьёзная тревога"


def _band_line(icon: str, label: str, bands: Bands, value: float, verdict: str = "") -> str:
    tail = f" — {verdict}" if verdict else ""
    target = (
        f"{bands.target_low:g}"
        if bands.target_low == bands.target_high
        else f"{bands.target_low:g}–{bands.target_high:g}"
    )
    return f"  {icon} {label}: {fmt.num(value)} {bands.unit} из {target}{tail}"


def _plural_days(n: int) -> str:
    return "сутки" if n % 10 == 1 and n % 100 != 11 else "суток"


def render_assessment(
    profile: Profile,
    events: list[sqlite3.Row],
    day: date,
    chat_id: int | None,
    complete: bool = True,
) -> list[str]:
    kcal_bands = profile.kcal_bands
    water_bands = profile.water_bands
    if kcal_bands is None or water_bands is None:
        return []

    kcal = figures.kcal_total(events)
    water = figures.effective_water(events)
    if not complete:
        return [
            "\n⚖️ Сутки ещё идут:",
            _band_line("🍗", "Еда", kcal_bands, kcal),
            _band_line("💧", "Жидкость", water_bands, water),
            "  Оценка — в сводке за завершённые сутки, прогноз на конец дня — /risk",
        ]

    lines = ["\n⚖️ Оценка суток:"]
    lines.append(_band_line("🍗", "Еда", kcal_bands, kcal, _verdict(kcal_bands, kcal)))
    lines.append(_band_line("💧", "Жидкость", water_bands, water, _verdict(water_bands, water)))

    if kcal < kcal_bands.critical:
        streak = (
            _low_kcal_streak(profile.subject_id, day, kcal_bands.critical) if chat_id is not None else 1
        )
        if streak >= kcal_bands.streak_days:
            lines.append(
                f"  🔴 меньше {kcal_bands.critical:g} ккал {streak} {_plural_days(streak)} "
                f"подряд — {kcal_bands.critical_note}"
            )
    if water < water_bands.critical:
        lines.append(
            f"  🔴 меньше {water_bands.critical:g} мл за сутки — {water_bands.critical_note}"
        )
    elif vomited(events):
        lines.append(f"  🔴 жидкость не удерживается (рвота) — {water_bands.critical_note}")
    return lines


def _need(value: float, threshold: float, unit: str, label: str) -> str:
    return f"{fmt.num(threshold - value)} {unit} до {label} {threshold:g}"


def _catch_up(bands: Bands, value: float, forecast: float) -> str:
    goals = []
    if forecast < bands.alarm:
        step = bands.severe if forecast < bands.severe else bands.alarm
        goals.append(_need(value, step, bands.unit, "порога"))
    if forecast < bands.target_low:
        goals.append(_need(value, bands.target_low, bands.unit, "цели"))
    return f"  добрать {', '.join(goals)}" if goals else ""


def _risk_metric(
    icon: str, label: str, bands: Bands, value: float, pace: float
) -> list[str]:
    forecast = value / pace
    lines = [
        f"\n{icon} {label}: {fmt.num(value)} {bands.unit} сейчас, по темпу к концу суток "
        f"≈ {fmt.num(forecast)} {bands.unit} — {_verdict(bands, forecast)}"
    ]
    catch_up = _catch_up(bands, value, forecast)
    if catch_up:
        lines.append(catch_up)
    return lines


def render_risk(
    events: list[sqlite3.Row],
    now: datetime,
    profile: Profile,
    pace: float,
    chat_id: int | None = None,
) -> str:
    header = f"🚨 {profile.name} — прогноз на {now.strftime('%H:%M')} (сутки с {db.DAY_START})"
    kcal_bands = profile.kcal_bands
    water_bands = profile.water_bands
    kcal = figures.kcal_total(events)
    water = figures.effective_water(events)

    if kcal_bands is None or water_bands is None:
        return (
            f"{header}\n"
            f"\n🍗 Калории: ~{fmt.num(kcal)} из {profile.kcal_goal:g}"
            f"\n💧 Жидкость: {fmt.num(water)} из {profile.water_goal_ml:g} мл"
            "\n\nПороги тревоги для этого профиля не заданы, прогноз по ним не считаю."
        )

    lines = [header]
    if pace <= 0:
        lines.append(
            f"\n🍗 Еда: {fmt.num(kcal)} ккал\n💧 Жидкость: {fmt.num(water)} мл"
            "\n\nТемп считается с 09:00, для прогноза ещё рано."
        )
        return "\n".join(lines)

    lines += _risk_metric("🍗", "Еда", kcal_bands, kcal, pace)
    lines += _risk_metric("💧", "Жидкость", water_bands, water, pace)

    if water / pace < water_bands.critical:
        lines.append(
            f"\n🔴 по прогнозу меньше {water_bands.critical:g} мл — {water_bands.critical_note}"
        )
    if vomited(events):
        lines.append(f"\n🔴 жидкость не удерживается (рвота) — {water_bands.critical_note}")
    if kcal / pace < kcal_bands.critical and chat_id is not None:
        before = _low_kcal_streak(profile.subject_id, db.care_day(now) - timedelta(days=1), kcal_bands.critical)
        if before >= kcal_bands.streak_days - 1 and before > 0:
            lines.append(
                f"\n🔴 меньше {kcal_bands.critical:g} ккал вчера, и сегодня по прогнозу тоже — "
                f"{kcal_bands.critical_note}"
            )
    return "\n".join(lines)


async def render_summary(
    day: date,
    events: list[sqlite3.Row],
    profile: Profile,
    header: str | None = None,
    chat_id: int | None = None,
    complete: bool = True,
) -> str:
    if header is None:
        header = (
            f"📊 {profile.name} — сводка за {day.strftime('%d.%m.%Y')} (сутки с {db.DAY_START})"
        )
    if not events:
        return f"{header}\nЗаписей пока нет."

    meds = [e for e in events if e["type"] == "medication"]
    water = [e for e in events if e["type"] == "water"]
    food = [e for e in events if e["type"] == "food"]
    refused = [e for e in events if e["type"] == "refusal"]
    toilet = [e for e in events if e["type"] == "toilet"]
    states = [e for e in events if e["type"] == "state"]
    other = [e for e in events if e["type"] == "other"]

    water_goal = profile.water_goal_ml
    kcal_goal = profile.kcal_goal
    labels = _feeding_labels(profile)
    lines = [header]

    if meds:
        lines.append("\n💊 Лекарства:")
        for e in meds:
            name = e["name"] or e["description"]
            dose = f" {e['dose']}" if e["dose"] else ""
            lines.append(f"  {_time_of(e)} — {name}{dose}")

    drink = sum(e["water_ml"] or 0 for e in water)
    food_water = figures.water_from_food(events)
    missed_wet = figures.uncounted_wet(events)
    if water or food_water or missed_wet:
        total = drink + food_water
        lines.append(
            f"\n💧 Вода: {fmt.num(total)} мл из {water_goal:g} "
            f"(питьё {fmt.num(drink)} + из корма {fmt.num(food_water)})"
        )
        if missed_wet:
            lines.append(_wet_note(missed_wet))
        drank = [e for e in water if not figures.is_given(e)]
        given = [e for e in water if figures.is_given(e)]
        if drank or given:
            parts = [f"{profile.pick('пила сама', 'пил сам')} {len(drank)} {fmt.plural(len(drank), 'раз', 'раза', 'раз')}"
                     f" ({fmt.num(sum(e['water_ml'] or 0 for e in drank))} мл)"]
            if given:
                parts.append(f"дали {fmt.num(sum(e['water_ml'] or 0 for e in given))} мл")
            lines.append("  " + ", ".join(parts))
        for e in water:
            ml = f"{e['water_ml']:g} мл" if e["water_ml"] else e["description"]
            source = " (дали)" if figures.is_given(e) else f" ({profile.self_label})"
            lines.append(f"  {_time_of(e)} — {ml}{source}")

    if food:
        lines.append("\n🍗 Еда:")
        for e in food:
            feeding = e["feeding"]
            kcal_note = f" (~{e['kcal']:g} ккал)" if e["kcal"] else ""
            label = f" [{labels[feeding]}]" if feeding in labels else ""
            description = _strip_kcal(e["description"])
            lines.append(f"  {_time_of(e)} — {description}{kcal_note}{label}")
        total_kcal, kcal_by_feeding, unquantified, gravy = _kcal_totals(food)
        if total_kcal:
            lines.append(
                f"  Итого: ~{fmt.num(total_kcal)} из {kcal_goal:g} ккал — "
                f"{_remaining(kcal_goal - total_kcal)}"
            )
            details = _kcal_details(kcal_by_feeding, unquantified, gravy, labels)
            if details:
                lines.append(f"  {details}")

    if refused:
        lines.append("\n🚫 Не стал есть:")
        for e in refused:
            lines.append(f"  {_time_of(e)} — {e['name'] or e['description']}")

    weights = [e for e in events if e["type"] == "weight" and e["weight_kg"]]
    if weights:
        lines.append("\n⚖️ Вес:")
        lines.extend(f"  {_time_of(e)} — {e['weight_kg']:g} кг" for e in weights)

    breathing = [e for e in events if e["type"] == "breathing" and e["breaths"]]
    if breathing:
        lines.append("\n🫁 Дыхание:")
        for e in breathing:
            state = {1: " во сне", 0: " не во сне"}.get(e["asleep"], "")
            flag = " — выше 30 во сне" if e["asleep"] == 1 and e["breaths"] > SLEEP_BREATHS_LIMIT else ""
            lines.append(f"  {_time_of(e)} — {fmt.num(e['breaths'])} в минуту{state}{flag}")

    temperature = [e for e in events if e["type"] == "temperature"]
    if temperature:
        lines.append("\n🌡 Температура:")
        for e in temperature:
            value = f"{e['temp_c']:g} °C" if e["temp_c"] is not None else e["description"]
            lines.append(f"  {_time_of(e)} — {value}")

    if toilet:
        lines.append("\n🚽 Туалет:")
        for e in toilet:
            score = f" ({questions.stool_label(e['stool_score'])})" if e["stool_score"] else ""
            lines.append(f"  {_time_of(e)} — {e['description']}{score}")

    if states:
        lines.append("\n😴 Состояние:")
        state_items = [(_time_of(e), e["description"]) for e in states]
        condensed = None
        if len(state_items) > CONDENSE_THRESHOLD:
            timeline = [(t, "state", d) for t, d in state_items]
            timeline += [
                (_time_of(e), "context", e["description"])
                for e in events
                if e["type"] in ("medication", "other")
            ]
            timeline.sort(key=lambda item: item[0])
            condensed = await condense_states(timeline)
        if condensed:
            lines.extend(f"  {line}" for line in condensed)
        else:
            lines.extend(f"  {time} — {description}" for time, description in state_items)

    if other:
        lines.append("\n📌 Прочее:")
        for e in other:
            lines.append(f"  {_time_of(e)} — {e['description']}")

    lines.extend(render_assessment(profile, events, day, chat_id, complete))
    return "\n".join(lines)
