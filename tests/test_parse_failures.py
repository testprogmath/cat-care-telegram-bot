"""What happens to a message when the model is unreachable, refuses, or the bot itself fails."""

import asyncio
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import openai
import pytest

from skrypka_bot import db, main, parser, profiles

BERLIN = ZoneInfo("Europe/Berlin")
REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def model(answer):
    """A client whose completion either raises `answer` or returns a message built from it."""

    async def parse(**_):
        if isinstance(answer, BaseException):
            raise answer
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(**answer))])

    return lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))


def out_of_credit():
    return openai.RateLimitError("quota", response=httpx.Response(429, request=REQUEST),
                                 body={"code": "insufficient_quota", "type": "insufficient_quota"})


def parse(monkeypatch, answer):
    monkeypatch.setattr(parser, "client", model(answer))
    return asyncio.run(parser.parse_message("съела 5 г", None, None, False, profiles.SKRIPA))


def test_no_credit_is_a_retryable_failure_that_says_so(monkeypatch):
    with pytest.raises(parser.ParseFailed) as failure:
        parse(monkeypatch, out_of_credit())
    assert failure.value.out_of_credit


def test_an_unreachable_model_is_a_retryable_failure_without_blaming_credit(monkeypatch):
    with pytest.raises(parser.ParseFailed) as failure:
        parse(monkeypatch, openai.APIConnectionError(request=REQUEST))
    assert not failure.value.out_of_credit


@pytest.mark.parametrize("answer", [
    {"parsed": None, "refusal": "I can't help with that."},
    {"parsed": None, "refusal": None},
])
def test_an_answer_without_events_is_a_refusal_not_an_empty_message(monkeypatch, answer):
    with pytest.raises(parser.ParseRefused):
        parse(monkeypatch, answer)


def test_a_bug_in_the_bot_is_not_disguised_as_a_model_failure(monkeypatch):
    with pytest.raises(KeyError):
        parse(monkeypatch, KeyError("events"))


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **_):
        self.sent.append(text)
        return SimpleNamespace(message_id=len(self.sent), date=datetime.now(BERLIN))


def receive(chat_id, monkeypatch, failure):
    async def fail(*_):
        raise failure

    monkeypatch.setattr(main, "parse_message", fail)
    main._parse_warned_at.clear()
    bot = Bot()
    message = SimpleNamespace(message_id=7, text="съел 5 г", caption=None, date=datetime.now(BERLIN),
                              from_user=SimpleNamespace(full_name="owner"), reply_to_message=None)
    update = SimpleNamespace(effective_message=message,
                             effective_chat=SimpleNamespace(id=chat_id, title="Чипуня", full_name="Чипуня"))
    asyncio.run(main.handle_message(update, SimpleNamespace(bot=bot)))
    with sqlite3.connect(db.DB_PATH) as conn:
        parsed = conn.execute("SELECT parsed FROM messages WHERE message_id = 7").fetchone()[0]
    return bot.sent, parsed


def test_a_refused_message_is_answered_and_not_retried(chat, monkeypatch):
    sent, parsed = receive(chat, monkeypatch, parser.ParseRefused("no"))
    assert sent == [main.PARSE_REFUSED_NOTICE]
    assert parsed == 1


@pytest.mark.parametrize(("failure", "cause"), [
    (parser.ParseFailed("quota", out_of_credit=True), "credit"),
    (parser.ParseFailed("timeout"), "unavailable"),
    (KeyError("events"), "bug"),
])
def test_a_failed_message_is_kept_for_retry_and_the_warning_names_the_cause(chat, monkeypatch, failure, cause):
    sent, parsed = receive(chat, monkeypatch, failure)
    assert parsed == 0
    assert len(sent) == 1 and sent[0].endswith(main.PARSE_BROKEN_CAUSES[cause])
