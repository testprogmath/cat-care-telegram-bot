"""What the bot does on a schedule: the daily summary, the water and feeding reminders and the check-ins."""

import logging
import math
from datetime import datetime, timedelta

from telegram.ext import (
    ContextTypes,
)

from . import common, db, figures, fmt, foods, questions
from .profiles import Profile
from .summary import (
    render_summary,
    weighing_reminder,
)

logger = logging.getLogger(__name__)


WATER_REMINDER_START_HOUR = 9


WATER_REMINDER_END_HOUR = 23


WATER_REMINDER_STEP_HOURS = 2


WATER_PACE_BUFFER_ML = 25.0


FEEDING_REMINDER_START_HOUR = 7


FEEDING_REMINDER_END_HOUR = 23


FEEDING_REMINDER_AFTER = timedelta(hours=1, minutes=30)


FEEDING_REMINDER_CHECK = timedelta(minutes=5)


FEEDING_REMINDER_MARKER = "[бот напомнил о еде]"


async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    day = db.care_day(datetime.now(common.TIMEZONE)) - timedelta(days=1)
    for chat_id, profile in db.active_chats():
        events = db.events_for_day(profile.subject_id, day)
        if not events:
            continue
        text = await render_summary(day, events, profile, chat_id=chat_id)
        reminder = weighing_reminder(db.last_weight(profile.subject_id), day + timedelta(days=1))
        if reminder:
            text = f"{text}\n\n{reminder}"
        try:
            sent = await context.bot.send_message(chat_id, text)
        except Exception:
            logger.exception("Failed to send daily summary to chat %s", chat_id)
            continue
        db.note_bot_report(chat_id, sent.message_id, sent.date.astimezone(common.TIMEZONE), common.SUMMARY_MARKER)


def day_pace(now: datetime) -> float:
    span = WATER_REMINDER_END_HOUR - WATER_REMINDER_START_HOUR
    elapsed = now.hour + now.minute / 60 - WATER_REMINDER_START_HOUR
    return min(max(elapsed / span, 0.0), 1.0)


def render_water_reminder(profile: Profile, got: float, now: datetime) -> str | None:
    goal = profile.water_goal_ml
    expected = goal * day_pace(now)
    if got >= goal or got >= expected - WATER_PACE_BUFFER_ML:
        return None
    text = (
        f"💧 Напоминание: {profile.name} {profile.verb_received} {fmt.num(got)} мл воды "
        f"из {goal:g} (осталось {fmt.num(goal - got)}).\n"
        f"К {now:%H:%M} по графику должно быть ~{expected:.0f} мл, не хватает ~{expected - got:.0f} мл "
        f"(график: {goal:g} мл равномерно с {WATER_REMINDER_START_HOUR:02d}:00 "
        f"до {WATER_REMINDER_END_HOUR:02d}:00)."
    )
    if profile.tube:
        remaining = goal - got
        portions = math.ceil(remaining / profile.tube.water_portion_ml)
        by = f" до {WATER_REMINDER_END_HOUR:02d}:00" if now.hour < WATER_REMINDER_END_HOUR else ""
        text += (
            f"\nЧтобы добрать {fmt.num(remaining)} мл{by}: примерно {portions} "
            f"{fmt.plural(portions, 'раз', 'раза', 'раз')} по ~{remaining / portions:.0f} мл "
            f"(не больше {profile.tube.water_portion_ml:g} мл за раз)."
        )
    return text


async def water_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(common.TIMEZONE)
    day = db.care_day(now)
    for chat_id, profile in db.active_chats():
        text = render_water_reminder(profile, figures.effective_water(db.events_for_day(profile.subject_id, day)), now)
        if text is None:
            continue
        try:
            await context.bot.send_message(chat_id, text)
        except Exception:
            logger.exception("Failed to send water reminder to chat %s", chat_id)


def feeding_window_start(now: datetime) -> datetime:
    return now.replace(hour=FEEDING_REMINDER_START_HOUR, minute=0, second=0, microsecond=0)


def render_feeding_reminder(
    profile: Profile, events: list, last_reminder: datetime | None, kcal_today: float, now: datetime
) -> str | None:
    """A nudge to offer food once the wait has run past the interval.

    The wait starts at the first entry of the morning, and a meal or a reminder starts it again.
    `events` are the rows from the start of the window to now.
    """
    if not FEEDING_REMINDER_START_HOUR <= now.hour < FEEDING_REMINDER_END_HOUR:
        return None
    if not events:
        return None
    start = feeding_window_start(now)
    meals = [datetime.fromisoformat(e["occurred_at"]) for e in events if foods.is_meal(e)]
    first_entry = datetime.fromisoformat(events[0]["occurred_at"])
    marks = [first_entry, *meals]
    if last_reminder is not None and last_reminder >= start:
        marks.append(last_reminder)
    if now - max(marks) < FEEDING_REMINDER_AFTER:
        return None
    if meals:
        wait = now - meals[-1]
        hours, minutes = divmod(int(wait.total_seconds()) // 60, 60)
        since = f"Последняя еда в {meals[-1]:%H:%M}, {hours} ч {minutes:02d} мин назад."
    else:
        since = f"С {first_entry:%H:%M} еды не было."
    return (
        f"🍗 Пора предложить еду для {profile.name_genitive}. {since}\n"
        f"За сутки ~{fmt.num(kcal_today)} ккал из {profile.kcal_goal:g}. "
        "Супчик без кусочков и соус не в счёт."
    )


async def feeding_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(common.TIMEZONE)
    for chat_id, profile in db.active_chats():
        events = db.events_in_range(profile.subject_id, feeding_window_start(now), now)
        last = db.last_bot_report_at(chat_id, FEEDING_REMINDER_MARKER)
        kcal_today = figures.kcal_total(db.events_for_day(profile.subject_id, db.care_day(now)))
        text = render_feeding_reminder(profile, events, last, kcal_today, now)
        if text is None:
            continue
        try:
            sent = await context.bot.send_message(chat_id, text)
        except Exception:
            logger.exception("Failed to send a feeding reminder to chat %s", chat_id)
            continue
        db.note_bot_report(chat_id, sent.message_id, sent.date.astimezone(common.TIMEZONE), FEEDING_REMINDER_MARKER)


async def checkin(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(common.TIMEZONE)
    for chat_id, profile in db.active_chats():
        if not questions.checkin_due(now, db.last_message_at(chat_id)):
            continue
        try:
            sent = await context.bot.send_message(chat_id, questions.checkin_text(profile))
        except Exception:
            logger.exception("Failed to send a check-in to chat %s", chat_id)
            continue
        db.note_bot_report(chat_id, sent.message_id, sent.date.astimezone(common.TIMEZONE), questions.CHECKIN_MARKER)
