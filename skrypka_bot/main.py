import asyncio
import logging
import os
import re
from datetime import date, datetime, time, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

from telegram import LinkPreviewOptions, ReplyParameters, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import charts, db, meds, profiles
from .parser import ParseFailed, parse_message
from .profiles import Profile
from .summary import (
    effective_water,
    render_progress,
    render_risk,
    render_summary,
    weighing_reminder,
)

WATER_REMINDER_START_HOUR = 9
WATER_REMINDER_END_HOUR = 23
WATER_REMINDER_STEP_HOURS = 2
WATER_PACE_BUFFER_ML = 25.0

HOSPITAL_RE = re.compile(r"\b(opname\w*|опнам\w*)\b", re.IGNORECASE)
HOME_RE = re.compile(
    r"\b(домой|забрал\w*|выписал\w*|ontslag\w*|naar huis)\b", re.IGNORECASE
)

RETRY_INTERVAL = timedelta(minutes=15)
PARSE_WARNING_INTERVAL = timedelta(hours=2)
_parse_warned_at: dict[int, datetime] = {}

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Berlin"))

REPORT_MARKER_PREFIX = "[бот отправил"
SUMMARY_MARKER = f"{REPORT_MARKER_PREFIX} сводку за сутки]"
WEEK_MARKER = f"{REPORT_MARKER_PREFIX} недельный график]"
MEDS_MARKER = f"{REPORT_MARKER_PREFIX} отчёт о лекарствах]"

def help_text(profile: Profile) -> str:
    return (
        f"Я собираю дневник ухода за {profile.name} из сообщений в этом чате: "
        "лекарства, вода, еда, состояние.\n\n"
        f"Сутки считаются с {db.DAY_START} до {db.DAY_START} следующего дня.\n\n"
        "Команды:\n"
        "/left — только вода и калории: сколько уже и сколько осталось. Приходит и сам, "
        "ответом на сообщение о еде с калориями\n"
        "/autoleft off — не присылать /left после записи еды, /autoleft on — снова присылать\n"
        "/stats — сводка за текущие сутки\n"
        "/stats 2026-08-03 — сводка за сутки, начавшиеся в эту дату\n"
        "/stats 09:00 — сводка за сегодня, начиная с указанного часа\n"
        "/risk — прогноз на конец суток по еде и жидкости против порогов тревоги\n"
        "/week — графики за неделю (вода, калории, туалет, температура)\n"
        "/meds — лекарства за 7 дней по суткам\n"
        "/meds all — лекарства за весь срок наблюдений, с графиком\n"
        "/meds 2026-09-01 2026-09-30 — лекарства за период, с графиком\n"
        "/profile — чей дневник ведётся в этом чате\n"
        "/reminders — напоминания и автосводка: пауза или работа\n\n"
        f"Каждый день в {db.DAY_START} я сам присылаю сводку за прошедшие сутки.\n"
        f"С 09:00 до 23:00 напоминаю дать воды, если {profile.name} отстаёт от "
        f"{profile.water_goal_ml:g} мл в день. Вода из влажного корма идёт в зачёт по влажности "
        "продукта: от 79% у паучей до 88.5% у жидких снеков.\n\n"
        "Слово «opname» или «опнаме» в чате ставит напоминания и автосводку на паузу: пока "
        f"{profile.name} в стационаре, поить дома некому. Пауза снимается сообщением о "
        "возвращении («забрали», «домой», «выписали», «ontslag») или командой /reminders on. "
        "Записи и команды /stats, /left, /week работают и на паузе."
    )


BOT_COMMANDS = [
    ("left", "Вода и калории: сколько уже и сколько осталось"),
    ("autoleft", "Сводка /left после записи еды: вкл или выкл"),
    ("stats", "Сводка за текущие сутки"),
    ("risk", "Прогноз на конец суток: еда и жидкость против порогов"),
    ("week", "Графики за неделю: вода, калории, туалет, температура"),
    ("meds", "Лекарства: неделя, весь срок или период"),
    ("profile", "Чей дневник ведётся в этом чате"),
    ("reminders", "Напоминания и автосводка: пауза на время стационара"),
    ("help", "Что я умею и как считаю"),
]


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands(BOT_COMMANDS)


def _parse_hour(arg: str) -> tuple[int, int] | None:
    parts = arg.split(":")
    if len(parts) > 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) == 2 else 0
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _history(chat_id: int, sent_at: datetime) -> tuple[list[tuple[str, str]], bool]:
    recent = db.recent_messages(chat_id, sent_at, timedelta(minutes=7))
    report_shown = any(line.startswith(REPORT_MARKER_PREFIX) for _, line in recent)
    history = [(at, line) for at, line in recent if not line.startswith(REPORT_MARKER_PREFIX)]
    return history, report_shown


async def _warn_parse_broken(bot, chat_id: int, now: datetime) -> None:
    warned_at = _parse_warned_at.get(chat_id)
    if warned_at and now - warned_at < PARSE_WARNING_INTERVAL:
        return
    _parse_warned_at[chat_id] = now
    try:
        await bot.send_message(
            chat_id,
            "⚠️ Не могу разобрать сообщения — записи сейчас не сохраняются. "
            "Я их запомнил и переразберу сам, как только разбор заработает. "
            "Скорее всего, закончились деньги на OpenAI.",
        )
    except Exception:
        logger.exception("Failed to warn chat %s about parse failures", chat_id)


def pause_notice(profile: Profile) -> str:
    return (
        f"⏸ Похоже, {profile.name} в стационаре. Ставлю напоминания о воде и ежедневную "
        "сводку на паузу. Напишите «забрали домой» или /reminders on, когда вернётесь — "
        "записи я веду как обычно."
    )


RESUME_NOTICE = "▶️ Возвращаю напоминания о воде и ежедневную сводку."


async def _switch_pause(bot, chat_id: int, at: datetime | None, notice: str) -> None:
    db.set_paused(chat_id, at)
    logger.info("Chat %s reminders %s", chat_id, "paused" if at else "resumed")
    try:
        await bot.send_message(chat_id, notice)
    except Exception:
        logger.exception("Failed to announce reminder pause change in chat %s", chat_id)


async def _track_hospital_stay(
    bot, chat_id: int, profile: Profile, text: str, now: datetime
) -> None:
    paused = db.paused_since(chat_id) is not None
    if not paused and HOSPITAL_RE.search(text):
        await _switch_pause(bot, chat_id, now, pause_notice(profile))
    elif paused and HOME_RE.search(text):
        await _switch_pause(bot, chat_id, None, RESUME_NOTICE)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    if msg is None or chat is None:
        return
    text = msg.text or msg.caption
    if not text:
        return
    if db.message_seen(chat.id, msg.message_id):
        logger.info("Message %s already seen, skipping", msg.message_id)
        return
    profile = db.upsert_chat(chat.id, chat.title or chat.full_name)
    sent_at = msg.date.astimezone(TIMEZONE)
    await _track_hospital_stay(context.bot, chat.id, profile, text, sent_at)
    sender = msg.from_user.full_name if msg.from_user else ""
    replied_to = msg.reply_to_message
    reply_text = (replied_to.text or replied_to.caption) if replied_to else None
    history, report_shown = _history(chat.id, sent_at)
    try:
        events = await parse_message(text, history, reply_text, report_shown, profile)
    except ParseFailed:
        db.save_message(chat.id, msg.message_id, sender, sent_at, text, [], parsed=False)
        logger.warning("Message %s stored unparsed, will retry", msg.message_id)
        await _warn_parse_broken(context.bot, chat.id, datetime.now(TIMEZONE))
        return
    db.save_message(chat.id, msg.message_id, sender, sent_at, text, events)
    if events:
        logger.info("Saved %d event(s) from message %s", len(events), msg.message_id)
    if db.auto_left(chat.id) and db.message_added_kcal(chat.id, msg.message_id):
        await _send_progress(context.bot, chat.id, reply_to=msg.message_id)


async def retry_unparsed(context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = db.unparsed_messages()
    if not pending:
        return
    logger.info("Retrying %d unparsed message(s)", len(pending))
    for row in pending:
        sent_at = datetime.fromisoformat(row["sent_at"])
        history, report_shown = _history(row["chat_id"], sent_at)
        try:
            events = await parse_message(
                row["text"], history, None, report_shown, db.profile_for(row["chat_id"])
            )
        except ParseFailed:
            logger.warning("Reparsing still failing, leaving %d message(s) queued", len(pending))
            return
        db.store_reparsed(row["chat_id"], row["message_id"], sent_at, row["text"], events)
        logger.info("Reparsed message %s: %d event(s)", row["message_id"], len(events))
    _parse_warned_at.clear()


def _parse_date(arg: str) -> date | None:
    try:
        return date.fromisoformat(arg)
    except ValueError:
        return None


NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


def with_site_link(text: str, profile: Profile, day: date) -> str:
    base = os.environ.get("WEB_BASE_URL", "").rstrip("/")
    if not base:
        return text
    return f"{text}\n\n🔗 {base}/{profile.subject_id}/day/{day.isoformat()}"


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    now = datetime.now(TIMEZONE)
    profile = db.profile_for(chat.id)
    arg = context.args[0] if context.args else None

    if arg is None:
        day = db.care_day(now)
        text = await render_summary(
            day, db.events_for_day(chat.id, day), profile, chat_id=chat.id, complete=False
        )
    elif (day := _parse_date(arg)) is not None:
        text = await render_summary(
            day,
            db.events_for_day(chat.id, day),
            profile,
            chat_id=chat.id,
            complete=day < db.care_day(now),
        )
    elif (parsed := _parse_hour(arg)) is not None:
        hour, minute = parsed
        start = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start > now:
            start -= timedelta(days=1)
        end = start + timedelta(days=1)
        events = db.events_in_range(chat.id, start, end)
        header = f"📊 {profile.name} — сводка с {start.strftime('%d.%m.%Y %H:%M')}"
        day = start.date()
        text = await render_summary(
            start.date(), events, profile, header=header, chat_id=chat.id, complete=False
        )
    else:
        text = "Формат: /stats, /stats 2026-08-03 или /stats 09:00"
        await context.bot.send_message(chat.id, text)
        return

    text = with_site_link(text, profile, day)
    sent = await context.bot.send_message(chat.id, text, link_preview_options=NO_PREVIEW)
    db.note_bot_report(chat.id, sent.message_id, sent.date.astimezone(TIMEZONE), SUMMARY_MARKER)


async def _send_progress(bot, chat_id: int, reply_to: int | None = None) -> None:
    now = datetime.now(TIMEZONE)
    day = db.care_day(now)
    profile = db.profile_for(chat_id)
    text = with_site_link(render_progress(db.events_for_day(chat_id, day), now, profile), profile, day)
    reply = ReplyParameters(reply_to, allow_sending_without_reply=True) if reply_to else None
    sent = await bot.send_message(chat_id, text, reply_parameters=reply, link_preview_options=NO_PREVIEW)
    db.note_bot_report(chat_id, sent.message_id, sent.date.astimezone(TIMEZONE), SUMMARY_MARKER)


async def left_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    await _send_progress(context.bot, chat.id)


async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    now = datetime.now(TIMEZONE)
    day = db.care_day(now)
    text = render_risk(
        db.events_for_day(chat.id, day),
        now,
        db.profile_for(chat.id),
        day_pace(now),
        chat_id=chat.id,
    )
    sent = await context.bot.send_message(chat.id, text)
    db.note_bot_report(chat.id, sent.message_id, sent.date.astimezone(TIMEZONE), SUMMARY_MARKER)


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    end_day = db.care_day(datetime.now(TIMEZONE))
    if context.args:
        parsed = _parse_date(context.args[0])
        if parsed is not None:
            end_day = parsed
    png = await asyncio.to_thread(charts.render_week, chat.id, end_day, db.profile_for(chat.id))
    sent = await context.bot.send_photo(chat.id, photo=BytesIO(png))
    db.note_bot_report(chat.id, sent.message_id, sent.date.astimezone(TIMEZONE), WEEK_MARKER)


def meds_period(chat_id: int, args: list[str], today: date) -> tuple[date, date] | None:
    if args == ["all"]:
        return db.first_event_day(chat_id) or today, today
    if len(args) == 2:
        start, end = _parse_date(args[0]), _parse_date(args[1])
        if start is not None and end is not None and start <= end:
            return start, end
    return None


def render_meds(chat_id: int, args: list[str], today: date) -> str | None:
    profile = db.profile_for(chat_id)
    if not args:
        start = today - timedelta(days=6)
        return meds.render_week(db.medications_in_days(chat_id, start, today), today, profile)
    period = meds_period(chat_id, args, today)
    if period is None:
        return None
    start, end = period
    return meds.render_period(db.medications_in_days(chat_id, start, end), start, end, profile)


async def meds_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    args = context.args or []
    today = db.care_day(datetime.now(TIMEZONE))
    text = render_meds(chat.id, args, today)
    if text is None:
        await context.bot.send_message(
            chat.id, "Формат: /meds, /meds all или /meds 2026-09-01 2026-09-30"
        )
        return
    sent = await context.bot.send_message(chat.id, text, parse_mode="HTML")
    db.note_bot_report(chat.id, sent.message_id, sent.date.astimezone(TIMEZONE), MEDS_MARKER)
    period = meds_period(chat.id, args, today)
    if period is None:
        return
    rows = db.medications_in_days(chat.id, *period)
    if not rows:
        return
    png = await asyncio.to_thread(charts.render_meds, rows, *period, db.profile_for(chat.id))
    sent = await context.bot.send_photo(chat.id, photo=BytesIO(png))
    db.note_bot_report(chat.id, sent.message_id, sent.date.astimezone(TIMEZONE), MEDS_MARKER)


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    if not context.args:
        current = db.profile_for(chat.id)
        await context.bot.send_message(
            chat.id,
            f"В этом чате я веду дневник: {current.name}.\n"
            f"Сменить: /profile <имя>. Доступны: {profiles.names()}.",
        )
        return
    chosen = profiles.resolve(context.args[0])
    if chosen is None:
        await context.bot.send_message(
            chat.id, f"Не знаю такого. Доступны: {profiles.names()}."
        )
        return
    db.set_profile(chat.id, chosen.key)
    await context.bot.send_message(
        chat.id,
        f"Готово, теперь этот чат — дневник {chosen.name}. "
        "Уже сохранённые записи этого чата остаются на месте, я их не переношу.",
    )


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    now = datetime.now(TIMEZONE)
    profile = db.profile_for(chat.id)
    arg = context.args[0].lower() if context.args else None

    if arg in ("on", "вкл"):
        if db.paused_since(chat.id) is None:
            await context.bot.send_message(chat.id, "Напоминания и так работают.")
            return
        await _switch_pause(context.bot, chat.id, None, RESUME_NOTICE)
        return
    if arg in ("off", "выкл"):
        if db.paused_since(chat.id) is not None:
            await context.bot.send_message(chat.id, "Напоминания уже на паузе.")
            return
        await _switch_pause(context.bot, chat.id, now, pause_notice(profile))
        return
    if arg is not None:
        await context.bot.send_message(chat.id, "Формат: /reminders, /reminders on или /reminders off")
        return

    paused_at = db.paused_since(chat.id)
    if paused_at is None:
        text = (
            "▶️ Напоминания о воде и ежедневная сводка работают.\n"
            "Поставить на паузу: /reminders off или слово «opname» в чате."
        )
    else:
        text = (
            f"⏸ Напоминания о воде и ежедневная сводка на паузе с "
            f"{paused_at.strftime('%d.%m %H:%M')}.\n"
            "Вернуть: /reminders on или сообщение о возвращении домой."
        )
    await context.bot.send_message(chat.id, text)


async def autoleft_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    arg = context.args[0].lower() if context.args else None
    if arg in ("on", "вкл"):
        db.set_auto_left(chat.id, True)
    elif arg in ("off", "выкл"):
        db.set_auto_left(chat.id, False)
    elif arg is not None:
        await context.bot.send_message(chat.id, "Формат: /autoleft, /autoleft on или /autoleft off")
        return
    if db.auto_left(chat.id):
        text = (
            "▶️ После каждой записи еды с калориями я отвечаю сводкой /left.\n"
            "Выключить: /autoleft off"
        )
    else:
        text = "⏸ Сводка /left после записи еды выключена.\nВключить: /autoleft on"
    await context.bot.send_message(chat.id, text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if update.effective_message and chat:
        await update.effective_message.reply_text(help_text(db.profile_for(chat.id)))


async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    day = db.care_day(datetime.now(TIMEZONE)) - timedelta(days=1)
    for chat_id, profile in db.active_chats():
        events = db.events_for_day(chat_id, day)
        if not events:
            continue
        text = await render_summary(day, events, profile, chat_id=chat_id)
        reminder = weighing_reminder(db.last_weight(chat_id), day + timedelta(days=1))
        if reminder:
            text = f"{text}\n\n{reminder}"
        try:
            sent = await context.bot.send_message(chat_id, text)
        except Exception:
            logger.exception("Failed to send daily summary to chat %s", chat_id)
            continue
        db.note_bot_report(chat_id, sent.message_id, sent.date.astimezone(TIMEZONE), SUMMARY_MARKER)


def day_pace(now: datetime) -> float:
    span = WATER_REMINDER_END_HOUR - WATER_REMINDER_START_HOUR
    elapsed = now.hour + now.minute / 60 - WATER_REMINDER_START_HOUR
    return min(max(elapsed / span, 0.0), 1.0)


async def water_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    now = datetime.now(TIMEZONE)
    day = db.care_day(now)
    pace = day_pace(now)
    for chat_id, profile in db.active_chats():
        goal = profile.water_goal_ml
        got = effective_water(db.events_for_day(chat_id, day))
        if got >= goal or got >= goal * pace - WATER_PACE_BUFFER_ML:
            continue
        remaining = goal - got
        try:
            await context.bot.send_message(
                chat_id,
                f"💧 Напоминание: {profile.name} {profile.verb_received} {got:g} мл воды "
                f"из {goal:g} (осталось {remaining:g}). Пора дать ~15-20 мл.",
            )
        except Exception:
            logger.exception("Failed to send water reminder to chat %s", chat_id)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> None:
    configure_logging()
    db.init()

    app = (
        Application.builder()
        .token(os.environ["TELEGRAM_BOT_TOKEN"])
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("left", left_command))
    app.add_handler(CommandHandler("autoleft", autoleft_command))
    app.add_handler(CommandHandler("risk", risk_command))
    app.add_handler(CommandHandler("week", week_command))
    app.add_handler(CommandHandler("meds", meds_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler(["help", "start"], help_command))
    app.add_handler(
        MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, handle_message)
    )

    hour, minute = (int(part) for part in db.DAY_START.split(":"))
    app.job_queue.run_daily(daily_summary, time(hour, minute, tzinfo=TIMEZONE))
    app.job_queue.run_repeating(
        retry_unparsed, interval=RETRY_INTERVAL, first=timedelta(minutes=1)
    )

    for reminder_hour in range(
        WATER_REMINDER_START_HOUR, WATER_REMINDER_END_HOUR + 1, WATER_REMINDER_STEP_HOURS
    ):
        app.job_queue.run_daily(water_reminder, time(reminder_hour, 0, tzinfo=TIMEZONE))

    logger.info("Starting bot (day boundary and summary at %s %s)", db.DAY_START, TIMEZONE)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
