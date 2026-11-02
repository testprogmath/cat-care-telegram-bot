"""A medication is due by its /schedule, or a day after it was given, and the bot says so 15 minutes ahead."""

import asyncio
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import commands, db, jobs, main, med_schedule

BERLIN = ZoneInfo("Europe/Berlin")
TODAY = datetime(2026, 11, 2, tzinfo=BERLIN)


def at(hour, minute=0, days=0):
    return TODAY.replace(hour=hour, minute=minute) + timedelta(days=days)


def give(chat_id, when, name, dose):
    db.create_event(chat_id, "chipunya", {
        "type": "medication", "name": name, "dose": dose, "description": f"дали {name}",
        "occurred_at": when.isoformat(), "day": when.date().isoformat(),
    }, when)


def due(chat_id, now):
    return [(d.drug, d.at, d.dose, d.basis) for d in jobs.due_medications(chat_id, "chipunya", now)]


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **_):
        self.sent.append(text)
        return SimpleNamespace(message_id=9000 + len(self.sent), date=Clock.moment)


class Clock(datetime):
    moment = TODAY

    @classmethod
    def now(cls, tz=None):
        return cls.moment


def schedule(chat_id, *args):
    bot = Bot()
    asyncio.run(commands.schedule_command(SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id)),
                                          SimpleNamespace(bot=bot, args=list(args))))
    return bot.sent


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ("бупренорфин 3 раза в день 0.06 мг", med_schedule.Schedule("бупренорфин", 3, (), "0.06 мг")),
        ("Бупренорфин 3x", med_schedule.Schedule("бупренорфин", 3)),
        ("бупренорфин 08:00 16:00 00:00 0,06мг (0.2 мл)",
         med_schedule.Schedule("бупренорфин", 3, (time(0), time(8), time(16)), "0.06 мг (0.2 мл)")),
        ("бупренорфин 3 раза 8:00 16:00 0:00", med_schedule.Schedule("бупренорфин", 3, (time(0), time(8), time(16)))),
        ("бупренорфин 2 раза 8:00 16:00 0:00", None),
        ("бупренорфин 0.06 мг", None),
        ("бупренорфин 3 раза после еды", None),
        ("бупренорфин 25:00", None),
        ("бупренорфин", None),
    ],
)
def test_a_schedule_is_read_from_the_command(args, expected):
    assert med_schedule.parse(args.split()) == expected


def test_a_dose_given_yesterday_is_due_at_the_same_time_today(chat):
    for name, dose in (("ондансетрон", "6 мг"), ("преднизолон", "7.5 мг"), ("серения", "8 мг")):
        give(chat, at(18, 52, days=-1), name, dose)
    assert due(chat, at(18, 36)) == []
    assert due(chat, at(18, 37)) == [
        ("ондансетрон", at(18, 52), "6 мг", "вчера в 18:52"),
        ("преднизолон", at(18, 52), "7.5 мг", "вчера в 18:52"),
        ("серения", at(18, 52), "8 мг", "вчера в 18:52"),
    ]
    give(chat, at(18, 40), "серения", "8 мг")
    assert [d[0] for d in due(chat, at(18, 45))] == ["ондансетрон", "преднизолон"]
    assert due(chat, at(19, 53)) == []


def test_a_dose_given_today_does_not_cover_the_next_one_of_a_twice_daily_drug(chat):
    give(chat, at(8, days=-1), "габапентин", "25 мг")
    give(chat, at(20, days=-1), "габапентин", "25 мг")
    give(chat, at(8, 10), "габапентин", "25 мг")
    assert due(chat, at(19, 50)) == [("габапентин", at(20), "25 мг", "вчера в 20:00")]


def test_an_early_dose_counts_for_the_slot(chat):
    give(chat, at(19, days=-1), "серения", "8 мг")
    give(chat, at(16, 30), "серения", "8 мг")
    assert due(chat, at(18, 50)) == []


def test_a_schedule_by_count_is_due_after_the_last_dose(chat):
    schedule(chat, "бупренорфин", "3", "раза", "в", "день", "0.06", "мг")
    give(chat, at(10, 55), "бупренорфин", "0.06 мг (0.2 мл)")
    assert due(chat, at(18, 39)) == []
    assert due(chat, at(18, 40)) == [
        ("бупренорфин", at(18, 55), "0.06 мг", "3 раза в день, последний раз в 10:55"),
    ]
    give(chat, at(18, 50), "бупренорфин", "0.06 мг")
    assert due(chat, at(18, 55)) == []


def test_a_schedule_by_count_without_any_dose_yet_waits(chat):
    schedule(chat, "бупренорфин", "3x")
    assert due(chat, at(12)) == []


def test_a_schedule_by_the_clock_is_due_at_its_times_also_past_midnight(chat):
    schedule(chat, "бупренорфин", "08:00", "16:00", "00:00")
    give(chat, at(16, 5), "бупренорфин", "0.06 мг")
    assert due(chat, at(23, 44)) == []
    assert due(chat, at(23, 45)) == [("бупренорфин", at(0, days=1), None, "по расписанию: 00:00, 08:00, 16:00")]
    give(chat, at(23, 50), "бупренорфин", "0.06 мг")
    assert due(chat, at(23, 55)) == []


def test_a_scheduled_drug_is_not_also_due_by_yesterday(chat):
    schedule(chat, "бупренорфин", "3x")
    give(chat, at(9, days=-1), "бупренорфин", "0.06 мг")
    give(chat, at(17, days=-1), "бупренорфин", "0.06 мг")
    assert due(chat, at(8, 50)) == []


def test_a_dose_missed_by_more_than_an_hour_is_no_longer_reminded(chat):
    give(chat, at(9, days=-1), "серения", "8 мг")
    assert [d[0] for d in due(chat, at(10))] == ["серения"]
    assert due(chat, at(10, 1)) == []


def test_the_job_sends_one_message_per_time_and_only_once(chat, monkeypatch):
    monkeypatch.setattr(jobs, "datetime", Clock)
    give(chat, at(18, 52, days=-1), "ондансетрон", "6 мг")
    give(chat, at(18, 52, days=-1), "серения", "8 мг")
    bot = Bot()
    for moment in (at(18, 40), at(18, 45), at(19, 0)):
        Clock.moment = moment
        asyncio.run(jobs.med_reminder(SimpleNamespace(bot=bot)))
    assert bot.sent == [
        "💊 В 18:52 лекарства для Чипуни:\n"
        "• ондансетрон 6 мг (вчера в 18:52)\n"
        "• серения (маропитант, таблетки) 8 мг (вчера в 18:52)",
    ]


def test_a_late_reminder_says_when_it_was_due(chat, monkeypatch):
    monkeypatch.setattr(jobs, "datetime", Clock)
    give(chat, at(9, days=-1), "серения", "8 мг")
    Clock.moment = at(9, 20)
    bot = Bot()
    asyncio.run(jobs.med_reminder(SimpleNamespace(bot=bot)))
    assert bot.sent == ["💊 Пора дать лекарство для Чипуни, по плану было в 09:00:\n"
                        "• серения (маропитант, таблетки) 8 мг (вчера в 09:00)"]


def test_a_paused_chat_gets_no_medication_reminder(chat, monkeypatch):
    monkeypatch.setattr(jobs, "datetime", Clock)
    give(chat, at(9, days=-1), "серения", "8 мг")
    db.set_paused(chat, at(7))
    Clock.moment = at(8, 50)
    bot = Bot()
    asyncio.run(jobs.med_reminder(SimpleNamespace(bot=bot)))
    assert bot.sent == []


def test_the_command_sets_shows_and_removes_a_schedule(chat):
    assert schedule(chat, "бупренорфин", "3", "раза", "в", "день", "0.06", "мг") == [
        "Записал расписание: бупренорфин 0.06 мг: 3 раза в день, от последнего приёма. "
        "Напомню минут за 15 до приёма."
    ]
    assert schedule(chat) == ["\n".join([
        "Расписание лекарств Чипуни:",
        "• бупренорфин 0.06 мг: 3 раза в день, от последнего приёма",
        "Остальные лекарства напоминаю за 15 минут до того времени, когда их дали вчера.",
        commands.SCHEDULE_FORMAT,
    ])]
    assert schedule(chat, "бупренорфин", "off") == [
        "Убрал расписание: бупренорфин. Теперь напоминаю о нём по вчерашнему времени."
    ]
    assert schedule(chat, "бупренорфин", "off") == ["Расписания для «бупренорфин» не было."]
    assert schedule(chat, "бупренорфин", "когда-нибудь") == [commands.SCHEDULE_FORMAT]


def test_the_bot_checks_for_medication_reminders_every_five_minutes(chat, monkeypatch):
    started = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(main.Application, "run_polling", lambda app, **_: started.append(app))
    main.main()
    [app] = started
    assert [
        job.job.trigger.interval for job in app.job_queue.jobs() if job.callback is jobs.med_reminder
    ] == [jobs.MED_REMINDER_CHECK]
