"""When the tube comes out, the animal is treated as one without a tube until it is back."""

import asyncio
import sqlite3
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from conftest import animal

from skrypka_bot import db, ingest, main, parser, profiles, summary
from skrypka_bot.profiles import Tube

BERLIN = ZoneInfo("Europe/Berlin")
TUBED = -2


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **_):
        self.sent.append(text)
        return SimpleNamespace(message_id=len(self.sent), date=datetime.now(BERLIN))


@pytest.fixture
def tubed(chat, monkeypatch):
    profile = animal("tubed", feeding_field="ПРАВИЛО БЕЗ ЗОНДА",
                     tube=Tube(water_portion_ml=25.0, max_feed_ml=100.0, feeding_field="ПРАВИЛО ЗОНДА"))
    monkeypatch.setattr(profiles, "PROFILES", {**profiles.PROFILES, "tubed": profile})
    db.set_profile(TUBED, "tubed")


def tube(chat_id, *args):
    bot = Bot()
    asyncio.run(main.tube_command(SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id)),
                                  SimpleNamespace(bot=bot, args=list(args))))
    return bot.sent


def tube_feed(chat_id, message_id, ml):
    event = SimpleNamespace(type="food", name=None, dose=None, water_ml=None, kcal=ml, feeding="tube",
                            amount_ml=ml, temp_c=None, liquid=True, water_fraction=None, time=None,
                            description=f"дала {ml:g} мл")
    ingest.save_message(chat_id, message_id, "owner", datetime(2026, 10, 11, 12, message_id, tzinfo=BERLIN),
                    event.description, [event])
    with sqlite3.connect(db.DB_PATH) as conn:
        return [row[0] for row in conn.execute("SELECT amount_ml FROM events WHERE chat_id = ?", (chat_id,))]


def test_with_the_tube_out_the_animal_has_no_tube_until_it_is_back(tubed):
    assert db.profile_for(TUBED).tube is not None
    tube(TUBED, "off")
    assert db.profile_for(TUBED).tube is None
    assert dict(db.active_chats())[TUBED].tube is None
    tube(TUBED, "on")
    assert db.profile_for(TUBED).tube == profiles.PROFILES["tubed"].tube


def test_with_the_tube_out_the_water_reminder_gives_no_portions(tubed):
    at = datetime(2026, 10, 11, 15, 0)
    assert len(main.render_water_reminder(db.profile_for(TUBED), 120.0, at).splitlines()) == 3
    tube(TUBED, "off")
    assert len(main.render_water_reminder(db.profile_for(TUBED), 120.0, at).splitlines()) == 2


def test_with_the_tube_out_the_tube_feed_limit_does_not_apply(tubed):
    tube(TUBED, "off")
    assert tube_feed(TUBED, 1, 120.0) == [120.0]


def test_the_command_says_what_it_did_and_what_the_state_is(tubed):
    assert tube(TUBED) == ["Трубка стоит, порции воды не больше 25 мл. Если выпадет: /tube off"]
    [off] = tube(TUBED, "off")
    assert off.startswith("Записал: трубки нет с ") and off.endswith(
        "Напоминания о воде теперь без порций, как у животного без зонда. Когда трубку поставят: /tube on")
    assert tube(TUBED)[0].startswith("Трубки нет с ")
    assert tube(TUBED, "on") == [
        "Записал: трубка стоит. Напоминания о воде снова делят остаток на порции не больше 25 мл. "
        "Если выпадет: /tube off"
    ]
    assert tube(TUBED, "x") == ["Формат: /tube, /tube off или /tube on"]


def test_an_animal_without_a_tube_has_nothing_to_switch(chat, monkeypatch):
    monkeypatch.setattr(profiles, "PROFILES", {**profiles.PROFILES, "untubed": animal("untubed")})
    db.set_profile(-3, "untubed")
    assert tube(-3, "off") == ["Мурка без зонда, переключать нечего."]
    assert db.tube_out_since(-3) is None


def test_the_prompt_takes_its_feeding_rules_from_the_tube_while_it_is_in(tubed):
    prompt = parser.system_prompt(db.profile_for(TUBED))
    assert "ПРАВИЛО ЗОНДА" in prompt and "ПРАВИЛО БЕЗ ЗОНДА" not in prompt
    tube(TUBED, "off")
    prompt = parser.system_prompt(db.profile_for(TUBED))
    assert "ПРАВИЛО БЕЗ ЗОНДА" in prompt and "ПРАВИЛО ЗОНДА" not in prompt


def test_food_given_without_a_tube_is_labelled_given_not_tube(tubed):
    tube(TUBED, "off")
    assert summary._feeding_labels(db.profile_for(TUBED))["tube"] == "дали"
    tube(TUBED, "on")
    assert summary._feeding_labels(db.profile_for(TUBED))["tube"] == "зонд"


def say(chat_id, text, monkeypatch, message_id=50):
    async def nothing(*_):
        return []

    monkeypatch.setattr(main, "parse_message", nothing)
    bot = Bot()
    message = SimpleNamespace(message_id=message_id, text=text, caption=None, date=datetime.now(BERLIN),
                              from_user=SimpleNamespace(full_name="owner"), reply_to_message=None)
    update = SimpleNamespace(effective_message=message, edited_message=None,
                             effective_chat=SimpleNamespace(id=chat_id, title="", full_name=""))
    asyncio.run(main.handle_message(update, SimpleNamespace(bot=bot)))
    return bot.sent


def test_a_message_that_the_tube_came_out_suggests_switching_it_off(tubed, monkeypatch):
    assert say(TUBED, "Скрипка вытащила зонд", monkeypatch) == [main.TUBE_OUT_HINT]
    assert say(TUBED, "дала через зонд 30 мл", monkeypatch, 51) == []


def test_once_it_is_off_only_putting_it_back_is_suggested(tubed, monkeypatch):
    tube(TUBED, "off")
    assert say(TUBED, "трубка выпала", monkeypatch) == []
    assert say(TUBED, "поставили трубку обратно", monkeypatch, 51) == [main.TUBE_IN_HINT]


def test_an_animal_without_a_tube_gets_no_suggestion(chat, monkeypatch):
    assert say(chat, "вытащил зонд", monkeypatch) == []
