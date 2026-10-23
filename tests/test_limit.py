"""/limit sets a chat's daily goals, and everything that counts from a goal follows it."""

import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import commands, db, ingest, profiles, summary

BERLIN = ZoneInfo("Europe/Berlin")


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **_):
        self.sent.append(text)
        return SimpleNamespace(message_id=len(self.sent), date=datetime.now(BERLIN))


def limit(chat_id, *args):
    bot = Bot()
    asyncio.run(commands.limit_command(SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id)),
                                       SimpleNamespace(bot=bot, args=list(args))))
    return bot.sent


def test_without_arguments_it_shows_the_goals(chat):
    assert limit(chat) == [f"Цели Чипуни на сутки: еда 270 ккал, вода 340 мл.\n{commands.GOAL_FORMAT}"]


def test_a_new_goal_is_kept_for_the_chat_and_the_reply_says_what_it_was(chat):
    [reply] = limit(chat, "food", "250")
    assert reply.startswith("Цели Чипуни на сутки: еда 250 ккал, вода 340 мл (было: еда 270 ккал, вода 340 мл).")
    assert db.profile_for(chat).kcal_goal == 250
    limit(chat, "вода", "300,5")
    assert (db.profile_for(chat).kcal_goal, db.profile_for(chat).water_goal_ml) == (250, 300.5)


def test_default_goes_back_to_the_configured_goal(chat):
    limit(chat, "food", "250")
    limit(chat, "food", "default")
    assert db.profile_for(chat).kcal_goal == 270


def test_a_goal_out_of_range_changes_nothing(chat):
    assert limit(chat, "food", "2250") == ["Цель должна быть от 50 до 600. Ничего не поменял."]
    assert db.profile_for(chat).kcal_goal == 270


def test_an_unknown_kind_or_number_shows_the_format(chat):
    assert limit(chat, "сон", "8") == [commands.GOAL_FORMAT]
    assert limit(chat, "food", "много") == [commands.GOAL_FORMAT]


def test_a_band_targeted_at_the_goal_moves_with_it_and_a_range_band_stays():
    moved = profiles.SKRIPA.with_goals(kcal=200, water_ml=300)
    assert (moved.kcal_bands.target_low, moved.kcal_bands.target_high) == (200, 200)
    assert moved.kcal_bands.alarm == profiles.SKRIPA.kcal_bands.alarm
    assert moved.water_bands == profiles.SKRIPA.water_bands


def test_left_counts_from_the_chats_goal(chat):
    limit(chat, "food", "250")
    now = datetime.now(BERLIN)
    ingest.save_message(chat, 1, "owner", now, "съел 10 ккал", [SimpleNamespace(
        type="food", name=None, dose=None, water_ml=None, kcal=10.0, feeding="self", amount_ml=None,
        temp_c=None, liquid=None, water_fraction=None, time=None, description="съел 10 ккал")])
    text = summary.render_progress(db.events_for_day("chipunya", db.care_day(now)), now, db.profile_for(chat))
    assert "~10 из 250 — осталось 240" in text
