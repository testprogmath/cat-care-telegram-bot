"""The bot asks how a stool looked and records the answer, and checks in when the chat is quiet."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import db, foods, ingest, jobs, messages, questions, summary

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


def test_a_bare_score_sent_without_replying_answers_the_open_question(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "покакал", [toilet("покакал")], monkeypatch, bot)
    parsed = receive(chat, 2, "4", [toilet("покакал, стул 4", 4)], monkeypatch, bot)
    assert parsed == []
    assert stools(chat, 1) == [4]
    assert stools(chat, 2) == []


def test_an_answered_question_takes_no_second_bare_score(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "покакал", [toilet("покакал")], monkeypatch, bot)
    receive(chat, 2, "4", [], monkeypatch, bot)
    parsed = receive(chat, 3, "3", [], monkeypatch, bot)
    assert parsed == ["3"]
    assert stools(chat, 1) == [4]


def test_a_bare_score_long_after_the_question_is_parsed_as_any_message(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "покакал", [toilet("покакал")], monkeypatch, bot)
    with db.connect() as conn:
        conn.execute("UPDATE stool_questions SET asked_at = ?",
                     ((datetime.now(BERLIN) - timedelta(minutes=31)).isoformat(),))
    assert receive(chat, 2, "4", [], monkeypatch, bot) == ["4"]
    assert stools(chat, 1) == [None]


@pytest.mark.parametrize(("text", "bare"), [("4", True), (" 3/5 ", True), ("2.", True), ("кашица", False),
                                            ("покакал, 4", False), ("45", False)])
def test_only_a_lone_digit_counts_as_an_unreplied_answer(text, bare):
    assert questions.is_bare_score(text) is bare


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


def soup(description, grams, pieces=None, name="felix soup"):
    return SimpleNamespace(
        type="food", name=name, dose=None, water_ml=None, kcal=round(grams * 0.425, 1), feeding="self",
        amount_ml=grams, temp_c=None, liquid=True, water_fraction=0.95, time=None, pieces=pieces,
        description=description,
    )


def feeding(chat_id, message_id):
    [row] = db.food_events(chat_id, message_id)
    return row["kcal"], row["water_fraction"], row["pieces"]


@pytest.mark.parametrize(
    ("answer", "pieces"),
    [("нет", "none"), ("только бульон", "none"), ("половину", "some"), ("немного", "some"),
     ("все", "all"), ("всё съела", "all"), ("2", "all"), ("не все", "some"), ("не помню", None), ("нет, все", None)],
)
def test_an_answer_names_how_many_pieces_or_none(answer, pieces):
    assert questions.pieces_from_reply(answer) == pieces


@pytest.mark.parametrize(
    ("food", "pieces", "figures"),
    [("Felix Soup", "none", (15.3, 0.95)), ("Felix Soup", "some", (16.7, 0.95)), ("Felix Soup", "all", (17.2, 0.875)),
     ("Felix Sensations", "none", (12.0, 0.88)), ("Felix Sensations", "some", (16.0, 0.867)),
     ("Felix Sensations", "all", (31.5, 0.842))],
)
def test_the_pieces_set_the_calories_and_water_of_the_grams_eaten(food, pieces, figures):
    grams = 36 if food == "Felix Soup" else {"none": 30, "some": 30, "all": 40}[pieces]
    assert foods.with_pieces(food, grams, pieces) == figures


def test_a_soup_without_a_word_on_the_pieces_is_asked_about(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "скушал 36 г супчика", [soup("36 г супчика", 36)], monkeypatch, bot)
    assert [(text, reply_to) for _, text, reply_to in bot.sent][-1] == (questions.PIECES_QUESTION["Felix Soup"], 1)


def test_a_soup_whose_pieces_are_named_is_not_asked_about(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "выпил бульон, кусочки оставил", [soup("бульон", 36, pieces="none")], monkeypatch, bot)
    assert all(text != questions.PIECES_QUESTION["Felix Soup"] for _, text, _ in bot.sent)


def test_the_answer_recounts_the_feeding_without_parsing(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "скушал 36 г супчика", [soup("36 г супчика", 36)], monkeypatch, bot)
    question = bot.sent[-1][0]
    parsed = receive(chat, 2, "половину", [], monkeypatch, bot, reply_to=question)
    assert parsed == []
    assert feeding(chat, 1) == (16.7, 0.95, "some")
    assert bot.sent[-1][1:] == ("Записал: с частью кусочков, 16.7 ккал.", 2)


def test_a_bare_answer_sent_without_replying_answers_the_open_pieces_question(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "выпил 36 г супчика", [soup("36 г супчика", 36)], monkeypatch, bot)
    parsed = receive(chat, 2, "Нет", [], monkeypatch, bot)
    assert parsed == []
    assert feeding(chat, 1) == (15.3, 0.95, "none")
    assert bot.sent[-1][1:] == ("Записал: без кусочков, 15.3 ккал.", 2)


def test_an_answered_pieces_question_takes_no_second_bare_answer(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "выпил 36 г супчика", [soup("36 г супчика", 36)], monkeypatch, bot)
    receive(chat, 2, "нет", [], monkeypatch, bot, reply_to=bot.sent[-1][0])
    assert receive(chat, 3, "все", [], monkeypatch, bot) == ["все"]
    assert feeding(chat, 1) == (15.3, 0.95, "none")


def test_a_bare_answer_long_after_the_pieces_question_is_parsed_as_any_message(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "выпил 36 г супчика", [soup("36 г супчика", 36)], monkeypatch, bot)
    with db.connect() as conn:
        conn.execute("UPDATE pieces_questions SET asked_at = ?",
                     ((datetime.now(BERLIN) - timedelta(minutes=31)).isoformat(),))
    assert receive(chat, 2, "нет", [], monkeypatch, bot) == ["нет"]
    assert feeding(chat, 1)[2] is None


def test_with_two_pieces_questions_open_a_bare_answer_waits_for_a_reply(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "выпил 36 г супчика и 40 г Sensations",
            [soup("36 г супчика", 36), soup("40 г Felix Sensations", 40, name="felix sensations утка")],
            monkeypatch, bot)
    assert receive(chat, 2, "нет", [], monkeypatch, bot) == ["нет"]
    assert [row["pieces"] for row in db.food_events(chat, 1)] == [None, None]


@pytest.mark.parametrize(("text", "bare"), [("Нет", True), ("половину", True), ("всё съела", True),
                                            ("не ел", True), ("нет, все", False), ("2", False),
                                            ("нет, не давали лекарство", False), ("Отказалась от супчика", False)])
def test_only_a_short_answer_counts_as_an_unreplied_pieces_answer(text, bare):
    assert questions.is_bare_pieces(text) is bare


def test_sensations_are_asked_about_with_their_own_wording(chat, monkeypatch):
    bot = Bot()
    receive(chat, 1, "съел 40 г Sensations", [soup("40 г Felix Sensations", 40, name="felix sensations утка")],
            monkeypatch, bot)
    receive(chat, 2, "все", [], monkeypatch, bot, reply_to=bot.sent[-1][0])
    assert feeding(chat, 1) == (31.5, 0.842, "all")


@pytest.mark.parametrize(
    ("text", "model_said", "kept"),
    [
        ("Скушала 36 грамм феликс супчик с тунцом", "none", None),
        ("выпил бульон из супчика, кусочки оставил", "none", "none"),
        ("съела 40 г Sensations, обычная смесь", "all", "all"),
        ("выпила весь супчик", "none", "none"),
        ("съела половину пауча", "some", "some"),
    ],
)
def test_the_models_pieces_count_only_when_the_message_speaks_of_them(text, model_said, kept):
    event = SimpleNamespace(type="food", pieces=model_said)
    assert ingest.known_pieces(event, text) == kept
