"""CareDay v1 export. The contract these tests defend is that a number means a number
and a silence means a silence."""

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone as _tz

utc = _tz.utc
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from skrypka_bot import care_export, db

BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 9, 25)
AFTER = datetime(2026, 9, 27, 12, 0, tzinfo=BERLIN)


def event(type, at="12:00", **overrides):
    base = dict(type=type, name=None, dose=None, water_ml=None, kcal=None, feeding=None,
                amount_ml=None, temp_c=None, liquid=None, water_fraction=None, time=None,
                description="")
    return SimpleNamespace(**{**base, **overrides, "time": at})


def record(chat_id, *events, day=DAY, text="запись"):
    sent = datetime.combine(day, datetime.min.time(), tzinfo=BERLIN).replace(hour=23, minute=59)
    record.n = getattr(record, "n", 0) + 1
    db.save_message(chat_id, record.n, "owner", sent, text, list(events))


def only(subject="chipunya", day=DAY, now=AFTER):
    return care_export.export(subject, day, day, now=now)[0]


def test_export_refuses_an_event_without_a_subject(chat):
    record(chat, event("food", kcal=10.0))
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.execute("UPDATE events SET subject = NULL")
    with pytest.raises(SystemExit, match="have no subject"):
        only()


def test_day_start_decides_which_day_an_event_lands_in(chat, monkeypatch):
    monkeypatch.setattr(db, "_DAY_START_HOUR", 11)
    row = {"occurred_at": datetime(2026, 9, 25, 1, 37, tzinfo=BERLIN).isoformat()}
    assert care_export.care_day_of(row, BERLIN) == date(2026, 9, 24)
    row = {"occurred_at": datetime(2026, 9, 25, 11, 0, tzinfo=BERLIN).isoformat()}
    assert care_export.care_day_of(row, BERLIN) == date(2026, 9, 25)


def test_the_boundary_holds_its_wall_clock_time_across_a_dst_change(monkeypatch):
    """25 Oct 2026 has 25 hours. A care day still starts at 11:00 local on both sides."""
    monkeypatch.setattr(db, "_DAY_START_HOUR", 11)
    for moment, expected in [
        (datetime(2026, 10, 25, 10, 30, tzinfo=BERLIN), date(2026, 10, 24)),
        (datetime(2026, 10, 25, 11, 30, tzinfo=BERLIN), date(2026, 10, 25)),
        (datetime(2026, 10, 26, 10, 30, tzinfo=BERLIN), date(2026, 10, 25)),
    ]:
        assert care_export.care_day_of({"occurred_at": moment.isoformat()}, BERLIN) == expected
    start, end = care_export.window_of(date(2026, 10, 24), BERLIN)
    assert start.hour == end.hour == 11
    assert start.utcoffset() == timedelta(hours=2) and end.utcoffset() == timedelta(hours=1)
    elapsed = end.astimezone(utc) - start.astimezone(utc)
    assert elapsed == timedelta(hours=25)


def test_a_timestamp_without_an_offset_is_read_in_the_configured_zone(chat):
    """Otherwise the same database exports differently depending on the host clock."""
    naive = {"occurred_at": "2026-09-16T10:00:00"}
    assert care_export.occurred_local(naive, BERLIN).utcoffset() == timedelta(hours=2)


def test_calories_sum_over_the_day(chat):
    record(chat, event("food", kcal=31.5), event("food", at="13:00", kcal=23.6))
    day = only()
    assert day.food_kcal == 55.1 and day.food_kcal_fully_quantified and day.food_events_recorded == 2


def test_a_feeding_without_calories_makes_the_total_incomplete(chat):
    record(chat, event("food", kcal=31.5), event("food", at="13:00", description="съел супчик"))
    day = only()
    assert day.food_kcal == 31.5 and not day.food_kcal_fully_quantified and day.food_events_recorded == 2


def test_food_with_no_usable_calorie_value_is_unknown_not_zero(chat):
    """The cat ate. How much is not known, and that is not the same as a fast."""
    record(chat, event("food", description="съел супчик"))
    day = only()
    assert day.food_kcal is None and not day.food_kcal_fully_quantified and day.food_events_recorded == 1


def test_a_day_with_no_food_recorded_reports_nothing_rather_than_zero(chat):
    record(chat, event("state", description="спит"))
    day = only()
    assert day.food_kcal is None and day.food_events_recorded == 0
    assert day.water_from_food_ml is None


@pytest.mark.parametrize(("events", "expected"), [
    ([], (0, None, False)),
    ([event("food", description="съел супчик")], (1, None, False)),
    ([event("food", kcal=31.5), event("food", at="13:00", description="съел супчик")], (2, 31.5, False)),
    ([event("food", kcal=31.5), event("food", at="13:00", kcal=23.6)], (2, 55.1, True)),
], ids=["nothing recorded", "recorded, none quantifiable", "lower bound", "all recorded accounted for"])
def test_the_four_food_states(chat, events, expected):
    """kcal is null until something quantifiable was recorded, and a floor until all of it was."""
    record(chat, *events, event("state", at="23:00", description="спит"))
    day = only()
    assert (day.food_events_recorded, day.food_kcal, day.food_kcal_fully_quantified) == expected


def test_drinking_and_water_from_food_are_reported_separately(chat):
    record(chat,
           event("water", water_ml=27.0),
           event("food", at="16:00", kcal=31.6, liquid=True, amount_ml=40.0, water_fraction=0.8))
    day = only()
    assert day.water_drinking_ml == 27.0 and day.water_drinking_fully_quantified
    assert day.water_from_food_ml == 32.0 and day.water_from_food_fully_quantified


def test_wet_food_without_an_amount_makes_water_from_food_incomplete(chat):
    record(chat, event("food", kcal=20.0, liquid=True))
    day = only()
    assert day.water_from_food_ml == 0.0 and not day.water_from_food_fully_quantified


def test_no_water_event_is_unknown_not_a_dry_day(chat):
    record(chat, event("food", kcal=10.0))
    day = only()
    assert day.water_drinking_ml is None and not day.water_drinking_fully_quantified


def test_toilet_counts_are_what_was_seen(chat):
    record(chat, event("toilet", description="пописал"), event("toilet", at="13:00", description="покакал"))
    day = only()
    assert day.urinations_observed == 1 and day.stools_observed == 1


def test_no_toilet_event_leaves_both_counts_unknown(chat):
    record(chat, event("state", description="спит"))
    day = only()
    assert day.urinations_observed is None and day.stools_observed is None


def test_logged_urinations_say_nothing_about_stools(chat):
    """The owner writing down three urinations did not watch the tray all day."""
    for n, at in enumerate(("08:00", "13:00", "19:00")):
        record(chat, event("toilet", at=at, description="пописал"))
    day = only()
    assert day.urinations_observed == 3
    assert day.stools_observed is None


def test_a_logged_stool_says_nothing_about_urination(chat):
    record(chat, event("toilet", at="09:00", description="покакал"))
    day = only()
    assert day.stools_observed == 1 and day.urinations_observed is None


def test_absence_of_a_vomiting_event_is_not_an_absence_of_vomiting(chat):
    record(chat, event("food", kcal=10.0))
    day = only()
    assert day.vomiting_episodes == [] and not day.vomiting_asserted_absent


def test_an_owner_saying_there_was_no_vomiting_is_recorded_as_such(chat):
    record(chat, event("state", description="рвоты не было, поел нормально"))
    day = only()
    assert day.vomiting_asserted_absent and day.vomiting_episodes == []


def test_vomiting_episodes_keep_their_time(chat):
    record(chat, event("state", at="17:06", description="его вырвало после еды"))
    day = only()
    assert len(day.vomiting_episodes) == 1
    assert day.vomiting_episodes[0].at.hour == 17 and day.vomiting_episodes[0].at.minute == 6
    assert not day.vomiting_asserted_absent


def test_struggling_free_is_not_vomiting(chat):
    record(chat, event("state", description="вырвалась из рук при уколе"))
    assert only().vomiting_episodes == []


def test_medications_keep_time_name_and_dose(chat):
    record(chat, event("medication", at="13:02", name="бупренорфин", dose="0.2 мл",
                       description="дала бупренорфин"))
    med = only().medications[0]
    assert med.name == "бупренорфин" and med.dose_text == "0.2 мл"
    assert med.at.hour == 13 and med.at.minute == 2


def test_temperatures_keep_time_and_value(chat):
    record(chat, event("temperature", at="09:10", temp_c=38.4))
    reading = only().temperatures[0]
    assert reading.value_c == 38.4 and reading.at.hour == 9 and reading.at.minute == 10


def test_the_current_day_is_marked_partial(chat):
    record(chat, event("food", kcal=10.0))
    during = care_export.export("chipunya", DAY, DAY, now=datetime(2026, 9, 25, 14, 0, tzinfo=BERLIN))[0]
    assert during.partial
    assert not only().partial


def test_days_with_nothing_recorded_are_still_exported(chat):
    """A snapshot must be able to empty a day that a previous import filled.

    So every requested day is emitted, and an empty one says "nothing is recorded for
    this subject and day", never "nothing happened".
    """
    record(chat, event("food", kcal=10.0))
    days = care_export.export("chipunya", DAY, DAY + timedelta(days=2), now=AFTER)
    assert [d.care_day for d in days] == [DAY, DAY + timedelta(days=1), DAY + timedelta(days=2)]
    empty = days[1]
    assert (empty.food_kcal, empty.water_drinking_ml, empty.water_from_food_ml) == (None, None, None)
    assert (empty.urinations_observed, empty.stools_observed) == (None, None)
    assert empty.food_events_recorded == 0
    assert not any([empty.food_kcal_fully_quantified, empty.water_drinking_fully_quantified,
                    empty.water_from_food_fully_quantified, empty.vomiting_asserted_absent])
    assert empty.temperatures == [] and empty.vomiting_episodes == []
    assert empty.medications == [] and empty.notes == [] and empty.food_refusals == []
    assert empty.content_hash and empty.subject_id == "chipunya"


def test_the_hash_ignores_row_order(chat):
    record(chat, event("medication", at="09:00", name="а"), event("medication", at="13:00", name="б"))
    forward = only()
    reversed_rows = forward.model_copy(update={"medications": list(reversed(forward.medications))})
    assert reversed_rows.with_hash().content_hash == forward.content_hash


def test_the_hash_ignores_when_the_export_ran(chat):
    record(chat, event("food", kcal=10.0))
    first = only(now=AFTER)
    second = only(now=AFTER + timedelta(hours=3))
    assert first.content_hash == second.content_hash


def test_the_hash_ignores_database_row_ids(chat):
    record(chat, event("food", kcal=10.0))
    day = only()
    renumbered = day.model_copy(update={"debug_event_refs": [1, 2, 3]})
    assert renumbered.with_hash().content_hash == day.content_hash


@pytest.mark.parametrize("change", [
    {"food_kcal": 99.0},
    {"vomiting_asserted_absent": True},
    {"urinations_observed": 3},
    {"partial": True},
    {"food_kcal_fully_quantified": False},
])
def test_the_hash_changes_when_the_record_means_something_different(chat, change):
    record(chat, event("food", kcal=10.0), event("toilet", at="13:00", description="пописал"))
    day = only()
    assert day.model_copy(update=change).with_hash().content_hash != day.content_hash


def test_quantified_does_not_claim_the_owner_saw_everything(chat):
    """One noticed feeding with a calorie value reports true. It is still one feeding."""
    record(chat, event("food", kcal=10.0))
    day = only()
    assert day.food_kcal_fully_quantified and day.food_events_recorded == 1
    assert day.food_kcal == 10.0
    assert not any("observed" in name or "total" in name
                   for name in day.model_dump() if name.endswith("quantified"))


def test_row_ids_are_absent_from_the_default_contract(chat):
    record(chat, event("food", kcal=10.0))
    assert only().debug_event_refs is None
    debugged = care_export.export("chipunya", DAY, DAY, now=AFTER, debug=True)[0]
    assert debugged.debug_event_refs and debugged.content_hash == only().content_hash


def test_a_running_day_does_not_hash_like_a_closed_one(chat):
    """Same events, same numbers: still a different thing to say about the patient."""
    record(chat, event("food", kcal=10.0))
    during = care_export.export("chipunya", DAY, DAY, now=datetime(2026, 9, 25, 14, 0, tzinfo=BERLIN))[0]
    closed = only()
    assert during.partial and not closed.partial
    assert during.food_kcal == closed.food_kcal
    assert during.content_hash != closed.content_hash


def test_a_legacy_naive_timestamp_keeps_its_care_day_wherever_the_export_runs(chat, monkeypatch):
    """Read as UTC by a container clock, 00:30 local would fall on the previous day."""
    monkeypatch.setattr(db, "_DAY_START_HOUR", 0)
    row = {"occurred_at": "2026-09-25T00:30:00"}
    assert care_export.care_day_of(row, BERLIN) == date(2026, 9, 25)
    assert care_export.occurred_local(row, BERLIN).utcoffset() == timedelta(hours=2)


def test_notes_carry_their_source_kind_and_stay_owner_reported(chat):
    record(chat, event("state", at="14:14", description="отказался от жидкого корма"))
    note = only().notes[0]
    assert note.kind == "state" and note.text == "отказался от жидкого корма"


def test_a_refusal_is_exported_apart_from_food_and_notes(chat):
    record(
        chat,
        event("refusal", at="09:30", name="royal canin urinary care", description="отказался от Urinary Care"),
        event("refusal", at="12:00", description="отказался от корма"),
    )
    day = only()
    assert [(r.at.strftime("%H:%M"), r.product, r.note) for r in day.food_refusals] == [
        ("09:30", "royal canin urinary care", "отказался от Urinary Care"),
        ("12:00", None, "отказался от корма"),
    ]
    assert (day.food_events_recorded, day.food_kcal, day.notes) == (0, None, [])


def test_appointments_and_admin_events_are_not_notes(chat):
    record(chat, event("other", at="15:00", description="в пн в 15:00 — консультация в МЦД"))
    assert only().notes == []


def test_the_export_carries_no_telegram_identifiers_or_raw_text(chat):
    record(chat, event("food", kcal=10.0, description="съел 3 г"),
           text="Чипуня покушал 3 грамма, писала мама в 23:59")
    payload = json.dumps(only().model_dump(mode="json"), ensure_ascii=False)
    assert "писала мама" not in payload and str(chat) not in payload
    assert "chat_id" not in payload and "message_id" not in payload and "sender" not in payload
    assert "съел 3 г" not in payload


def test_the_export_states_the_boundary_it_used(chat):
    record(chat, event("food", kcal=10.0))
    day = only()
    assert day.day_start == "00:00" and day.timezone == "Europe/Berlin"
    assert day.window_start.date() == DAY and day.window_end.date() == DAY + timedelta(days=1)
    assert day.schema_version == "care-day/1" and day.source == "cat-care"
