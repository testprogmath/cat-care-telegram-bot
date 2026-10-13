"""The bot, the site and the export read one animal's diary, whichever chat each row came from."""

from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from skrypka_bot import care_export, db, ingest, profiles, summary, views

BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 10, 6)
NEW_CHAT = -5


def event(type, **fields):
    base = dict(type=type, name=None, dose=None, water_ml=None, kcal=None, feeding="self",
                amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None, description="запись")
    return SimpleNamespace(**{**base, **fields})


def test_a_diary_moved_to_another_chat_keeps_one_set_of_figures(chat):
    ingest.save_message(chat, 1, "owner", datetime(2026, 10, 6, 9, 0, tzinfo=BERLIN), "старый чат",
                    [event("food", kcal=40.0), event("water", water_ml=20.0)])
    db.set_profile(chat, None)
    db.set_profile(NEW_CHAT, "chipunya")
    ingest.save_message(NEW_CHAT, 2, "owner", datetime(2026, 10, 6, 15, 0, tzinfo=BERLIN), "новый чат",
                    [event("food", kcal=12.0), event("water", water_ml=10.0)])

    bot = db.events_for_day("chipunya", DAY)
    [site] = views.day_rows("chipunya", DAY, DAY)
    [export] = care_export.export("chipunya", DAY, DAY, now=datetime(2026, 10, 7, 12, 0, tzinfo=BERLIN))

    assert summary.kcal_total([e for e in bot if e["type"] == "food"]) == 52.0
    assert site.kcal == export.food_kcal == 52.0
    assert summary.effective_water(bot) == site.drinking_ml == export.water_drinking_ml == 30.0
    assert site.drank_ml == 30.0 and site.drank_times == 2
    assert profiles.get(db.profile_for(NEW_CHAT).key).subject_id == "chipunya"


def test_a_row_that_does_not_say_who_fed_counts_as_taken_alone_everywhere(chat):
    ingest.save_message(chat, 1, "owner", datetime(2026, 10, 6, 9, 0, tzinfo=BERLIN), "записи", [
        event("food", kcal=30.0, feeding=None), event("food", kcal=10.0, feeding="tube"),
        event("water", water_ml=20.0, feeding=None), event("water", water_ml=5.0, feeding="tube"),
    ])
    rows = db.events_for_day("chipunya", DAY)
    _, by_feeding, _, _ = summary._kcal_totals([e for e in rows if e["type"] == "food"])
    [site] = views.day_rows("chipunya", DAY, DAY)

    assert by_feeding == {"tube": 10.0, "self": 30.0}
    assert (site.kcal_tube, site.kcal_self) == (10.0, 30.0)
    assert (site.drank_ml, site.given_ml) == (20.0, 5.0)
