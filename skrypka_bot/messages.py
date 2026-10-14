"""Messages from the chats: parsing them, reparsing edits and failures, the hints they trigger."""

import logging
import re
from datetime import datetime, timedelta

from telegram import ReplyParameters, Update
from telegram.ext import (
    ContextTypes,
)

from . import common, db, ingest, profiles
from .parser import ParseFailed, ParseRefused, parse_message
from .profiles import Profile

logger = logging.getLogger(__name__)


HOSPITAL_RE = re.compile(r"\b(opname\w*|опнам\w*)\b", re.IGNORECASE)


HOME_RE = re.compile(
    r"\b(домой|забрал\w*|выписал\w*|ontslag\w*|naar huis)\b", re.IGNORECASE
)


_TUBE = r"(?:зонд\w*|трубк\w*)"


_CAME_OUT = r"(?:вытащ\w*|выдерн\w*|выдрал\w*|выпал\w*|вылез\w*|вышл\w*|выскоч\w*)"


TUBE_OUT_RE = re.compile(
    rf"\b{_CAME_OUT}\W+(?:\w+\W+)?{_TUBE}|\b{_TUBE}\W+(?:\w+\W+)?{_CAME_OUT}", re.IGNORECASE
)


TUBE_IN_RE = re.compile(
    rf"\bпостав\w*\W+(?:\w+\W+)?{_TUBE}|\b{_TUBE}\W+(?:\w+\W+)?постав\w*", re.IGNORECASE
)


TUBE_OUT_HINT = (
    "Похоже, трубка вышла. Если так, напишите /tube off: напоминания о воде станут без порций, "
    "а то, что дали, я буду записывать как «дали», а не «зонд»."
)


TUBE_IN_HINT = "Похоже, трубку поставили. Если так, напишите /tube on."


PARSE_WARNING_INTERVAL = timedelta(hours=2)


_parse_warned_at: dict[int, datetime] = {}


def _history(chat_id: int, sent_at: datetime) -> tuple[list[tuple[str, str]], bool]:
    recent = db.recent_messages(chat_id, sent_at, timedelta(minutes=7))
    report_shown = any(line.startswith(common.REPORT_MARKER_PREFIX) for _, line in recent)
    history = [(at, line) for at, line in recent if not line.startswith(common.REPORT_MARKER_PREFIX)]
    return history, report_shown


PARSE_BROKEN_CAUSES = {
    "credit": "Скорее всего, закончились деньги на OpenAI.",
    "unavailable": "OpenAI сейчас не отвечает.",
    "bug": "Это ошибка в самом боте, её надо чинить.",
}


PARSE_REFUSED_NOTICE = (
    "⚠️ Не смог разобрать это сообщение и ничего из него не записал. "
    "Напишите, пожалуйста, то же самое другими словами."
)


async def _warn_parse_broken(bot, chat_id: int, now: datetime, cause: str) -> None:
    warned_at = _parse_warned_at.get(chat_id)
    if warned_at and now - warned_at < PARSE_WARNING_INTERVAL:
        return
    _parse_warned_at[chat_id] = now
    try:
        await bot.send_message(
            chat_id,
            "⚠️ Не могу разобрать сообщения — записи сейчас не сохраняются. "
            "Я их запомнил и переразберу сам, как только разбор заработает. "
            + PARSE_BROKEN_CAUSES[cause],
        )
    except Exception:
        logger.exception("Failed to warn chat %s about parse failures", chat_id)


async def _track_hospital_stay(
    bot, chat_id: int, profile: Profile, text: str, now: datetime
) -> None:
    paused = db.paused_since(chat_id) is not None
    if not paused and HOSPITAL_RE.search(text):
        await common.switch_pause(bot, chat_id, now, common.pause_notice(profile))
    elif paused and HOME_RE.search(text):
        await common.switch_pause(bot, chat_id, None, common.RESUME_NOTICE)


async def _suggest_tube_switch(bot, chat_id: int, message_id: int, profile: Profile, text: str) -> None:
    if profiles.get(profile.key).tube is None:
        return
    out = db.tube_out_since(chat_id) is not None
    hint = TUBE_IN_HINT if out and TUBE_IN_RE.search(text) else None
    if not out and TUBE_OUT_RE.search(text):
        hint = TUBE_OUT_HINT
    if hint:
        await bot.send_message(
            chat_id, hint, reply_parameters=ReplyParameters(message_id, allow_sending_without_reply=True)
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    if msg is None or chat is None:
        return
    text = msg.text or msg.caption
    if not text:
        return
    if db.message_seen(chat.id, msg.message_id):
        if update.edited_message is not None:
            await _reparse_edited(context.bot, chat.id, msg, text)
        else:
            logger.info("Message %s already seen, skipping", msg.message_id)
        return
    profile = db.upsert_chat(chat.id, chat.title or chat.full_name)
    if profile is None:
        logger.info("Chat %s has no profile, ignoring message %s", chat.id, msg.message_id)
        return
    sent_at = msg.date.astimezone(common.TIMEZONE)
    await _track_hospital_stay(context.bot, chat.id, profile, text, sent_at)
    await _suggest_tube_switch(context.bot, chat.id, msg.message_id, profile, text)
    sender = msg.from_user.full_name if msg.from_user else ""
    replied_to = msg.reply_to_message
    reply_text = (replied_to.text or replied_to.caption) if replied_to else None
    history, report_shown = _history(chat.id, sent_at)
    try:
        events = await parse_message(text, history, reply_text, report_shown, profile)
    except ParseRefused:
        ingest.save_message(chat.id, msg.message_id, sender, sent_at, text, [])
        await context.bot.send_message(
            chat.id, PARSE_REFUSED_NOTICE,
            reply_parameters=ReplyParameters(msg.message_id, allow_sending_without_reply=True),
        )
        return
    except ParseFailed as failure:
        cause = "credit" if failure.out_of_credit else "unavailable"
    except Exception:
        logger.exception("Parsing message %s crashed", msg.message_id)
        cause = "bug"
    else:
        cause = None
    if cause is not None:
        ingest.save_message(chat.id, msg.message_id, sender, sent_at, text, [], parsed=False)
        logger.warning("Message %s stored unparsed, will retry", msg.message_id)
        await _warn_parse_broken(context.bot, chat.id, datetime.now(common.TIMEZONE), cause)
        return
    ingest.save_message(chat.id, msg.message_id, sender, sent_at, text, events)
    if events:
        logger.info("Saved %d event(s) from message %s", len(events), msg.message_id)
    if db.auto_left(chat.id) and db.message_added_kcal(chat.id, msg.message_id):
        await common.send_progress(context.bot, chat.id, reply_to=msg.message_id)


async def _reparse_edited(bot, chat_id: int, msg, text: str) -> None:
    profile = db.profile_for(chat_id)
    if profile is None:
        return
    sent_at = msg.date.astimezone(common.TIMEZONE)
    replied_to = msg.reply_to_message
    reply_text = (replied_to.text or replied_to.caption) if replied_to else None
    history, report_shown = _history(chat_id, sent_at)
    try:
        events = await parse_message(text, history, reply_text, report_shown, profile)
    except Exception:
        logger.exception("Edited message %s could not be parsed, keeping its old events", msg.message_id)
        return
    ingest.replace_message_events(chat_id, msg.message_id, text, events, datetime.now(common.TIMEZONE))
    logger.info("Reparsed edited message %s: %d event(s)", msg.message_id, len(events))
    if db.auto_left(chat_id) and db.message_added_kcal(chat_id, msg.message_id):
        await common.send_progress(bot, chat_id, reply_to=msg.message_id)


async def retry_unparsed(context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = db.unparsed_messages()
    if not pending:
        return
    logger.info("Retrying %d unparsed message(s)", len(pending))
    for row in pending:
        profile = db.profile_for(row["chat_id"])
        if profile is None:
            continue
        sent_at = datetime.fromisoformat(row["sent_at"])
        history, report_shown = _history(row["chat_id"], sent_at)
        try:
            events = await parse_message(row["text"], history, None, report_shown, profile)
        except ParseRefused:
            events = []
        except Exception:
            logger.exception("Reparsing still failing, leaving %d message(s) queued", len(pending))
            return
        ingest.store_reparsed(row["chat_id"], row["message_id"], sent_at, row["text"], events)
        logger.info("Reparsed message %s: %d event(s)", row["message_id"], len(events))
    _parse_warned_at.clear()
