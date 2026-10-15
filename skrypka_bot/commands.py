"""The bot's commands."""

import asyncio
import functools
import logging
from datetime import date, datetime, timedelta
from io import BytesIO

from telegram import Update
from telegram.ext import (
    ContextTypes,
)

from . import charts, common, db, jobs, meds, profiles
from .profiles import Profile
from .summary import (
    render_risk,
    render_summary,
)

logger = logging.getLogger(__name__)


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
        "/reminders — напоминания и автосводка: пауза или работа\n"
        + ("/tube off — трубка выпала, /tube on — трубку поставили\n" if profiles.get(profile.key).tube else "")
        + "\n"
        f"Каждый день в {db.DAY_START} я сам присылаю сводку за прошедшие сутки.\n"
        f"С 09:00 до 23:00 напоминаю дать воды, если {profile.name} отстаёт от "
        f"{profile.water_goal_ml:g} мл в день. Вода из влажного корма идёт в зачёт по влажности "
        "продукта: от 79% у паучей до 88.5% у жидких снеков.\n\n"
        "Если про стул не сказано, какой он, я спрошу балл по шкале 1-5: ответьте на вопрос цифрой. "
        "С 09:00 до 22:00, если в чате три часа тихо, спрашиваю, как дела.\n\n"
        "Слово «opname» или «опнаме» в чате ставит напоминания, вопросы «как дела» и автосводку на паузу: пока "
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
    ("tube", "Зонд: стоит или выпал"),
    ("help", "Что я умею и как считаю"),
]


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


def for_known_chat(command):
    @functools.wraps(command)
    async def run(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        if chat is None or db.profile_for(chat.id) is None:
            return
        await command(update, context)

    return run


def _parse_date(arg: str) -> date | None:
    try:
        return date.fromisoformat(arg)
    except ValueError:
        return None


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    now = datetime.now(common.TIMEZONE)
    profile = db.profile_for(chat.id)
    arg = context.args[0] if context.args else None

    if arg is None:
        day = db.care_day(now)
        text = await render_summary(
            day, db.events_for_day(profile.subject_id, day), profile, chat_id=chat.id, complete=False
        )
    elif (day := _parse_date(arg)) is not None:
        text = await render_summary(
            day,
            db.events_for_day(profile.subject_id, day),
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
        events = db.events_in_range(profile.subject_id, start, end)
        header = f"📊 {profile.name} — сводка с {start.strftime('%d.%m.%Y %H:%M')}"
        day = start.date()
        text = await render_summary(
            start.date(), events, profile, header=header, chat_id=chat.id, complete=False
        )
    else:
        text = "Формат: /stats, /stats 2026-08-03 или /stats 09:00"
        await context.bot.send_message(chat.id, text)
        return

    text = common.with_site_link(text, profile, day)
    sent = await context.bot.send_message(chat.id, text, link_preview_options=common.NO_PREVIEW)
    db.note_bot_report(chat.id, sent.message_id, sent.date.astimezone(common.TIMEZONE), common.SUMMARY_MARKER)


async def left_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    await common.send_progress(context.bot, chat.id)


async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    now = datetime.now(common.TIMEZONE)
    day = db.care_day(now)
    profile = db.profile_for(chat.id)
    text = render_risk(
        db.events_for_day(profile.subject_id, day),
        now,
        profile,
        jobs.day_pace(now),
        chat_id=chat.id,
    )
    sent = await context.bot.send_message(chat.id, text)
    db.note_bot_report(chat.id, sent.message_id, sent.date.astimezone(common.TIMEZONE), common.SUMMARY_MARKER)


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    end_day = db.care_day(datetime.now(common.TIMEZONE))
    if context.args:
        parsed = _parse_date(context.args[0])
        if parsed is not None:
            end_day = parsed
    png = await asyncio.to_thread(charts.render_week, end_day, db.profile_for(chat.id))
    sent = await context.bot.send_photo(chat.id, photo=BytesIO(png))
    db.note_bot_report(chat.id, sent.message_id, sent.date.astimezone(common.TIMEZONE), common.WEEK_MARKER)


def meds_period(chat_id: int, args: list[str], today: date) -> tuple[date, date] | None:
    if args == ["all"]:
        return db.first_event_day(db.profile_for(chat_id).subject_id) or today, today
    if len(args) == 2:
        start, end = _parse_date(args[0]), _parse_date(args[1])
        if start is not None and end is not None and start <= end:
            return start, end
    return None


def render_meds(chat_id: int, args: list[str], today: date) -> str | None:
    profile = db.profile_for(chat_id)
    if not args:
        start = today - timedelta(days=6)
        return meds.render_week(db.medications_in_days(profile.subject_id, start, today), today, profile)
    period = meds_period(chat_id, args, today)
    if period is None:
        return None
    start, end = period
    return meds.render_period(db.medications_in_days(profile.subject_id, start, end), start, end, profile)


async def meds_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    args = context.args or []
    today = db.care_day(datetime.now(common.TIMEZONE))
    text = render_meds(chat.id, args, today)
    if text is None:
        await context.bot.send_message(
            chat.id, "Формат: /meds, /meds all или /meds 2026-09-01 2026-09-30"
        )
        return
    sent = await context.bot.send_message(chat.id, text, parse_mode="HTML")
    db.note_bot_report(chat.id, sent.message_id, sent.date.astimezone(common.TIMEZONE), common.MEDS_MARKER)
    period = meds_period(chat.id, args, today)
    if period is None:
        return
    profile = db.profile_for(chat.id)
    rows = db.medications_in_days(profile.subject_id, *period)
    if not rows:
        return
    png = await asyncio.to_thread(charts.render_meds, rows, *period, profile)
    sent = await context.bot.send_photo(chat.id, photo=BytesIO(png))
    db.note_bot_report(chat.id, sent.message_id, sent.date.astimezone(common.TIMEZONE), common.MEDS_MARKER)


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    if not context.args:
        current = db.profile_for(chat.id)
        if current is None:
            return
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
    try:
        db.set_profile(chat.id, chosen.key)
    except db.ProfileTaken:
        await context.bot.send_message(
            chat.id, f"Дневник {chosen.name} уже ведётся в другом чате, второй чат я не завожу."
        )
        return
    await context.bot.send_message(
        chat.id,
        f"Готово, теперь этот чат — дневник {chosen.name}. "
        "Уже сохранённые записи этого чата остаются на месте, я их не переношу.",
    )


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    now = datetime.now(common.TIMEZONE)
    profile = db.profile_for(chat.id)
    arg = context.args[0].lower() if context.args else None

    if arg in ("on", "вкл"):
        if db.paused_since(chat.id) is None:
            await context.bot.send_message(chat.id, "Напоминания и так работают.")
            return
        await common.switch_pause(context.bot, chat.id, None, common.RESUME_NOTICE)
        return
    if arg in ("off", "выкл"):
        if db.paused_since(chat.id) is not None:
            await context.bot.send_message(chat.id, "Напоминания уже на паузе.")
            return
        await common.switch_pause(context.bot, chat.id, now, common.pause_notice(profile))
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


async def tube_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None:
        return
    animal = db.profile_for(chat.id)
    tube = profiles.get(animal.key).tube
    if tube is None:
        await context.bot.send_message(chat.id, f"{animal.name} без зонда, переключать нечего.")
        return
    arg = context.args[0].lower() if context.args else None
    now = datetime.now(common.TIMEZONE)
    if arg in ("off", "выкл"):
        db.set_tube_out(chat.id, now)
        text = (
            f"Записал: трубки нет с {now:%d.%m %H:%M}. Напоминания о воде теперь без порций, "
            "как у животного без зонда. Когда трубку поставят: /tube on"
        )
    elif arg in ("on", "вкл"):
        db.set_tube_out(chat.id, None)
        text = (
            f"Записал: трубка стоит. Напоминания о воде снова делят остаток на порции "
            f"не больше {tube.water_portion_ml:g} мл. Если выпадет: /tube off"
        )
    elif arg is not None:
        text = "Формат: /tube, /tube off или /tube on"
    elif (since := db.tube_out_since(chat.id)) is not None:
        text = f"Трубки нет с {since:%d.%m %H:%M}. Когда поставят: /tube on"
    else:
        text = f"Трубка стоит, порции воды не больше {tube.water_portion_ml:g} мл. Если выпадет: /tube off"
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
