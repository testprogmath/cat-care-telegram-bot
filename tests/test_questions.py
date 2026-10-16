"""The bot asks how a stool looked and records the answer, and checks in when the chat is quiet."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import db, jobs, messages, questions, summary

BERLIN = ZoneInfo("Europe/Berlin")
_ids = iter(range(5000, 6000))


class Bot:
    def __init__(self, at=None):
        self.sent = []
        self.at = at

    async def send_message(self, chat_id, text, reply_parameters=None, **_):
        message_id = next(_ids)
        self.sent.append((message_id, text, reply_parameters and reply_parameters.message_id))
        return SimpleNamespace(message_id=message_id, date=self.at or datetime.now(BERLIN))


def toilet(description, stool_score=None):
    return SimpleNamespace(
        type="toilet", name=None, dose=None, water_ml=None, kcal=None, feeding=None, amount_ml=None,
        temp_c=None, liquid=None, water_fraction=None, time=None, stool_score=stool_score,
        description=description,
    )


def receive(chat_id, message_id, text, events, monkeypatch, bot, reply_to=None):
    parsed = []

    async def parse(*_args):
        parsed.append(text)
        return events

    monkeypatch.setattr(messages, "parse_message", parse)
    replied = SimpleNamespace(message_id=reply_to, text="", caption=None) if reply_to else None
    message = SimpleNamespace(
        message_id=message_id, text=text, caption=None, date=datetime.now(BERLIN),
        from_user=SimpleNamespace(full_name="owner"), reply_to_message=replied,
    )
    update = SimpleNamespace(
        effective_message=message,
        effective_chat=SimpleNamespace(id=chat_id, title="Чипуня", full_name="Чипуня"),
    )
    asyncio.run(messages.handle_message(update, SimpleNamespace(bot=bot)))
    return parsed


def stools(chat_id, message_id):
    return [row["stool_score"] for row in db.toilet_events(chat_id, message_id)]


@pytest.mark.parametrize(
    ("answer", "score"),
    [
        ("3", 3),
        ("4, норма", 4),
        ("кашица", 3),
        ("жидкий совсем", 1),
        ("твёрдый", 5),
        ("скорее сухой", 5),
        ("не видела", None),
        ("между 3 и 4", None),
        ("2.5", None),
        ("мягкий, но оформленный", None),
    ],
)
def test_an_answer_names_one_point_of_the_scale_or_none(answer, score):
    assert questions.score_from_reply(answer) == score


def test_a_stool_without_its_consistency_is_answered_with_the_scale(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "покакал", [toilet("покакал")], monkeypatch, bot)
    assert [(text, reply_to) for _, text, reply_to in bot.sent] == [(questions.STOOL_QUESTION, 1)]


def test_a_described_stool_and_a_urination_are_not_asked_about(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "покакал, нормальная колбаска", [toilet("покакал, нормальный стул", 4)], monkeypatch, bot)
    receive(chat, 2, "пописал", [toilet("пописал")], monkeypatch, bot)
    assert bot.sent == []
    assert stools(chat, 1) == [4]


def test_the_answer_to_the_question_scores_the_stool_without_parsing(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "покакал", [toilet("покакал")], monkeypatch, bot)
    question = bot.sent[0][0]
    parsed = receive(chat, 2, "3", [], monkeypatch, bot, reply_to=question)
    assert parsed == []
    assert stools(chat, 1) == [3]
    assert bot.sent[-1][1:] == ("Записал: стул 3/5, кашица.", 2)
    assert db.message_seen(chat, 2)


def test_an_answer_without_a_score_is_parsed_as_any_message(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "покакал", [toilet("покакал")], monkeypatch, bot)
    parsed = receive(chat, 2, "не видела, убрали", [], monkeypatch, bot, reply_to=bot.sent[0][0])
    assert parsed == ["не видела, убрали"]
    assert stools(chat, 1) == [None]


def test_a_score_on_a_urination_is_dropped(chat, monkeypatch):
    receive(chat, 1, "пописал", [toilet("пописал", 3)], monkeypatch, Bot())
    assert stools(chat, 1) == [None]


def test_the_summary_shows_the_score_next_to_the_stool(chat, monkeypatch):
    receive(chat, 1, "покакал, кашица", [toilet("покакал, мягкий стул", 3)], monkeypatch, Bot())
    events = db.events_for_day("chipunya", db.care_day(datetime.now(BERLIN)))
    text = asyncio.run(summary.render_summary(db.care_day(datetime.now(BERLIN)), events, db.profile_for(chat)))
    assert "покакал, мягкий стул (стул 3/5, кашица)" in text


NOON = datetime(2026, 10, 16, 12, 0, tzinfo=BERLIN)


@pytest.mark.parametrize(
    ("now", "last", "due"),
    [
        (NOON, NOON - timedelta(hours=3), True),
        (NOON, NOON - timedelta(hours=2, minutes=59), False),
        (NOON, None, True),
        (NOON.replace(hour=8, minute=59), None, False),
        (NOON.replace(hour=22, minute=0), None, False),
        (NOON.replace(hour=21, minute=30), NOON.replace(hour=18), True),
    ],
)
def test_a_check_in_comes_only_by_day_and_after_three_quiet_hours(now, last, due):
    assert questions.checkin_due(now, last) is due


def test_the_check_in_counts_as_a_message_so_the_next_waits_three_hours(chat, monkeypatch):
    class Clock(datetime):
        moment = NOON

        @classmethod
        def now(cls, tz=None):
            return cls.moment

    monkeypatch.setattr(jobs, "datetime", Clock)
    bot = Bot(at=NOON)
    asyncio.run(jobs.checkin(SimpleNamespace(bot=bot)))
    Clock.moment = NOON + timedelta(hours=2, minutes=30)
    asyncio.run(jobs.checkin(SimpleNamespace(bot=bot)))
    Clock.moment = NOON + timedelta(hours=3)
    asyncio.run(jobs.checkin(SimpleNamespace(bot=bot)))
    assert [text for _, text, _ in bot.sent] == ["Как Чипуня? Что сейчас делает?"] * 2


def test_a_paused_chat_gets_no_check_in(chat, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOON

    monkeypatch.setattr(jobs, "datetime", Clock)
    db.set_paused(chat, NOON - timedelta(days=1))
    bot = Bot()
    asyncio.run(jobs.checkin(SimpleNamespace(bot=bot)))
    assert bot.sent == []
