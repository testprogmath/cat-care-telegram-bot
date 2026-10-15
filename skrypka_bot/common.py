"""Things every part of the bot shares: the zone, report markers, the site link, /left and the pause."""

import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from telegram import LinkPreviewOptions, ReplyParameters

from . import db
from .profiles import Profile
from .summary import (
    render_progress,
)

logger = logging.getLogger(__name__)


TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Berlin"))


REPORT_MARKER_PREFIX = "[бот отправил"


SUMMARY_MARKER = f"{REPORT_MARKER_PREFIX} сводку за сутки]"


WEEK_MARKER = f"{REPORT_MARKER_PREFIX} недельный график]"


MEDS_MARKER = f"{REPORT_MARKER_PREFIX} отчёт о лекарствах]"


NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def with_site_link(text: str, profile: Profile, day: date) -> str:
    base = os.environ.get("WEB_BASE_URL", "").rstrip("/")
    if not base:
        return text
    return f"{text}\n\n🔗 {base}/{profile.subject_id}/day/{day.isoformat()}"


async def send_progress(bot, chat_id: int, reply_to: int | None = None) -> None:
    now = datetime.now(TIMEZONE)
    day = db.care_day(now)
    profile = db.profile_for(chat_id)
    text = with_site_link(render_progress(db.events_for_day(profile.subject_id, day), now, profile), profile, day)
    reply = ReplyParameters(reply_to, allow_sending_without_reply=True) if reply_to else None
    sent = await bot.send_message(chat_id, text, reply_parameters=reply, link_preview_options=NO_PREVIEW)
    db.note_bot_report(chat_id, sent.message_id, sent.date.astimezone(TIMEZONE), SUMMARY_MARKER)


def pause_notice(profile: Profile) -> str:
    return (
        f"⏸ Похоже, {profile.name} в стационаре. Ставлю напоминания о воде и ежедневную "
        "сводку на паузу. Напишите «забрали домой» или /reminders on, когда вернётесь — "
        "записи я веду как обычно."
    )


RESUME_NOTICE = "▶️ Возвращаю напоминания о воде и ежедневную сводку."


async def switch_pause(bot, chat_id: int, at: datetime | None, notice: str) -> None:
    db.set_paused(chat_id, at)
    logger.info("Chat %s reminders %s", chat_id, "paused" if at else "resumed")
    try:
        await bot.send_message(chat_id, notice)
    except Exception:
        logger.exception("Failed to announce reminder pause change in chat %s", chat_id)
