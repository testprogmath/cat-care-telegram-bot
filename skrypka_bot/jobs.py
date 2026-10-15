"""What the bot does on a schedule: the daily summary and the water reminders."""

import logging
import math
from datetime import datetime, timedelta

from telegram.ext import (
    ContextTypes,
)

from . import common, db, figures, fmt
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
