"""The feeding reminder counts the wait from the first entry of the morning, a meal or the last reminder."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import db, foods, jobs, main

BERLIN = ZoneInfo("Europe/Berlin")
DAY = datetime(2026, 10, 27, tzinfo=BERLIN)


def at(hour, minute=0):
    return DAY.replace(hour=hour, minute=minute)


def add(chat_id, when, kind="food", description="съела 5 г сухариков", **fields):
    return db.create_event(chat_id, "chipunya", {
        "type": kind, "description": description, "occurred_at": when.isoformat(),
        "day": when.date().isoformat(), **fields,
    }, when)


def reminder(chat_id, now, last_reminder=None, kcal_today=0.0):
    events = db.events_in_range("chipunya", jobs.feeding_window_start(now), now)
    return jobs.render_feeding_reminder(db.profile_for(chat_id), events, last_reminder, kcal_today, now)


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **_):
        self.sent.append(text)
        return SimpleNamespace(message_id=9000 + len(self.sent), date=Clock.moment)


class Clock(datetime):
    moment = DAY

    @classmethod
    def now(cls, tz=None):
        return cls.moment


@pytest.mark.parametrize(
    ("fields", "meal"),
    [
        ({"description": "съела 5 г сухариков Purina One"}, True),
        ({"description": "Felix Soup с тунцом — 27 г", "pieces": "none"}, False),
        ({"description": "Felix Soup с тунцом — 27 г", "pieces": "some"}, True),
        ({"description": "Felix Sensations, только подливка", "pieces": "all"}, True),
        ({"description": "выпил 35 мл соуса Felix с курицей"}, False),
        ({"description": "выпил весь соус", "name": "felix sauce kip"}, False),
        ({"description": "съел 11 г супчика Felix с бифом, без кусочков"}, False),
        ({"description": "выпил 15 г соуса (только бульон, кусочки не тронул)"}, False),
        ({"description": "выпила весь соус Felix Heerlijke Reepjes, кусочки не ела"}, False),
        ({"description": "съел 5 г Royal Canin Kitten (кусочки в соусе)"}, True),
        ({"description": "Felix Sensations с ламбом — 45 г, в соусе"}, True),
        ({"description": "выпил бульон из пауча Felix Soup с бифом"}, False),
        ({"description": "слизала подливку Monge, около 12 мл"}, False),
        ({"description": "выпила бульон, кусочки оставила"}, False),
        ({"description": "выпил бульон, кусочки не стал"}, False),
        ({"description": "выпила весь бульон и съела половину кусочков"}, True),
        ({"description": "съела 42 г — выпила весь соус, съела все кусочки", "name": "felix soup lamb"}, True),
        ({"kind": "refusal", "description": "не стал есть felix soup"}, False),
    ],
)
def test_a_soup_without_its_pieces_and_a_sauce_are_not_meals(chat, fields, meal):
    assert foods.is_meal(add(chat, at(9), **fields)) is meal


def test_before_the_first_entry_of_the_morning_there_is_no_reminder(chat):
    add(chat, at(5, 30), kind="toilet", description="пописала")
    assert reminder(chat, at(12)) is None


def test_the_wait_starts_at_the_first_entry_after_seven(chat):
    add(chat, at(6), description="съела 5 г сухариков ночью")
    add(chat, at(7, 40), kind="toilet", description="пописала")
    assert reminder(chat, at(9, 9)) is None
    assert reminder(chat, at(9, 10), kcal_today=42.0) == (
        "🍗 Пора предложить еду для Чипуни. С 07:40 еды не было.\n"
        "За сутки ~42 ккал из 270. Супчик без кусочков и соус не в счёт."
    )


def test_a_meal_between_reminders_starts_the_wait_again(chat):
    add(chat, at(7, 10), kind="toilet", description="пописала")
    add(chat, at(8, 30))
    assert reminder(chat, at(9, 59)) is None
    assert reminder(chat, at(10, 5), kcal_today=60.5) == (
        "🍗 Пора предложить еду для Чипуни. Последняя еда в 08:30, 1 ч 35 мин назад.\n"
        "За сутки ~60.5 ккал из 270. Супчик без кусочков и соус не в счёт."
    )


def test_a_soup_without_pieces_does_not_start_the_wait_again(chat):
    add(chat, at(8))
    add(chat, at(9), description="Felix Soup с курицей — 25 г", pieces="none")
    assert reminder(chat, at(9, 30)) is not None


def test_a_reminder_starts_the_wait_again(chat):
    add(chat, at(7))
    assert reminder(chat, at(10), last_reminder=at(9)) is None
    assert reminder(chat, at(10, 30), last_reminder=at(9)) is not None


def test_a_reminder_from_yesterday_does_not_hold_back_the_morning(chat):
    add(chat, at(7))
    assert reminder(chat, at(8, 30), last_reminder=at(22) - timedelta(days=1)) is not None


def test_an_entry_dated_later_today_does_not_count_yet(chat):
    add(chat, at(7))
    add(chat, at(23, 30))
    assert reminder(chat, at(9)) is not None


def test_the_calories_leave_out_an_entry_dated_later_today(chat, monkeypatch):
    monkeypatch.setattr(jobs, "datetime", Clock)
    Clock.moment = at(9)
    add(chat, at(7), kcal=10.0)
    add(chat, at(23, 30), kcal=50.0)
    bot = Bot()
    asyncio.run(jobs.feeding_reminder(SimpleNamespace(bot=bot)))
    assert [text.splitlines()[1] for text in bot.sent] == [
        "За сутки ~10 ккал из 270. Супчик без кусочков и соус не в счёт.",
    ]


def test_the_bot_checks_for_a_feeding_reminder_every_five_minutes(chat, monkeypatch):
    started = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(main.Application, "run_polling", lambda app, **_: started.append(app))
    main.main()
    [app] = started
    assert [
        job.job.trigger.interval for job in app.job_queue.jobs() if job.callback is jobs.feeding_reminder
    ] == [jobs.FEEDING_REMINDER_CHECK]


def test_there_is_no_reminder_at_night(chat):
    add(chat, at(7))
    assert reminder(chat, at(23)) is None


def test_the_job_sends_one_reminder_and_waits_another_interval(chat, monkeypatch):
    monkeypatch.setattr(jobs, "datetime", Clock)
    add(chat, at(7, 15))
    bot = Bot()
    for moment in (at(8, 45), at(8, 50), at(10, 14), at(10, 15)):
        Clock.moment = moment
        asyncio.run(jobs.feeding_reminder(SimpleNamespace(bot=bot)))
    assert [text.splitlines()[0] for text in bot.sent] == [
        "🍗 Пора предложить еду для Чипуни. Последняя еда в 07:15, 1 ч 30 мин назад.",
        "🍗 Пора предложить еду для Чипуни. Последняя еда в 07:15, 3 ч 00 мин назад.",
    ]


def test_a_paused_chat_gets_no_feeding_reminder(chat, monkeypatch):
    monkeypatch.setattr(jobs, "datetime", Clock)
    Clock.moment = at(12)
    add(chat, at(7))
    db.set_paused(chat, at(8))
    bot = Bot()
    asyncio.run(jobs.feeding_reminder(SimpleNamespace(bot=bot)))
    assert bot.sent == []
