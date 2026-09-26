"""Read-only CareDay v1 export: the integration contract with downstream clinical tools.

This module owns the definition of a care day. A consumer must never need to know
DAY_START, the timezone, which fraction of a wet food is water, or how cat-care
deduplicates. It must also never need to guess whether a zero means "none happened"
or "nobody wrote it down": every quantity here is either recorded, explicitly
asserted absent, or null.

Legacy rows written without a UTC offset are read as wall-clock time in the configured
care timezone, never in the timezone of whatever machine runs the export.

Known debt, deliberately not addressed here: cat-care computes a care day in two
places, this module and db.care_day, from configuration parsed at two different
moments, and neither reads TIMEZONE. They agree today because both take the boundary
from db._DAY_START_HOUR. They should eventually sit behind one timezone-aware
primitive. See README, "Care day: known debt".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sqlite3
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from . import db, summary

SCHEMA_VERSION = "care-day/1"
SOURCE = "cat-care"

HASH_EXCLUDED = ("exported_at", "content_hash", "debug_event_refs")


def timezone() -> ZoneInfo:
    """The zone the care-day boundary is applied in.

    db.care_day() applies DAY_START to whatever datetime it is handed and never reads
    TIMEZONE itself, so the zone is implicit in the running bot. The export cannot
    afford that: it may run anywhere, and the container's own clock is UTC.
    """
    return ZoneInfo(os.environ.get("TIMEZONE", "Europe/Berlin"))


def source_instance() -> str:
    return os.environ.get("CARE_EXPORT_INSTANCE") or socket.gethostname()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TemperatureReading(Strict):
    at: datetime
    value_c: float


class VomitingEpisode(Strict):
    at: datetime
    note: str | None = None


class MedicationAdministration(Strict):
    at: datetime
    name: str | None = None
    dose_text: str | None = None
    note: str | None = None


class OwnerNote(Strict):
    """An owner-reported observation, normalised by cat-care's parser.

    Never a clinician finding, and never the raw message the owner typed.
    """

    at: datetime
    kind: str
    text: str


class CareDay(Strict):
    """One subject, one care day.

    Identity is (source, subject_id, care_day). Nothing else in here is an identifier.

    A null quantity means nothing was recorded, never that the quantity was zero.
    A number is the sum over what was recorded, which is a floor, not a total: the
    owner writes down what they see.

    The *_fully_quantified flags answer one narrow question, "did every recorded event
    of this kind carry a usable number", and nothing at all about whether the owner
    saw everything the cat ate or drank. cat-care cannot establish that and does not
    claim to. A day with a single quantified feeding reports food_kcal_fully_quantified
    true; it is still one feeding somebody happened to notice.

    Times are in the timezone named by the timezone field and the day runs from
    day_start local to day_start local. window_start and window_end carry their real
    offsets, so a day crossing a daylight-saving change is 23 or 25 hours long.
    """

    schema_version: str = SCHEMA_VERSION
    source: str = SOURCE
    source_instance: str
    subject_id: str

    care_day: date
    day_start: str
    timezone: str
    window_start: datetime
    window_end: datetime

    exported_at: datetime
    partial: bool

    food_kcal: float | None
    food_kcal_fully_quantified: bool
    food_events_recorded: int

    water_drinking_ml: float | None
    water_drinking_fully_quantified: bool
    water_from_food_ml: float | None
    water_from_food_fully_quantified: bool

    urinations_observed: int | None
    stools_observed: int | None

    temperatures: list[TemperatureReading]
    vomiting_episodes: list[VomitingEpisode]
    vomiting_asserted_absent: bool
    medications: list[MedicationAdministration]
    notes: list[OwnerNote]

    debug_event_refs: list[int] | None = None
    content_hash: str = ""

    def hashed_payload(self) -> dict:
        """Everything the hash covers: the whole record except HASH_EXCLUDED.

        exported_at changes on every run. debug_event_refs are database row ids,
        which cat-care's deduplication reassigns without anything having happened
        differently. Lists are sorted, so the hash does not depend on row order.
        Everything else participates, partial included: a day that is still running
        does not mean the same thing as the closed day with the same numbers.
        """
        payload = self.model_dump(mode="json", exclude=set(HASH_EXCLUDED))
        for key in ("temperatures", "vomiting_episodes", "medications", "notes"):
            payload[key] = sorted(payload[key], key=lambda item: json.dumps(item, sort_keys=True))
        return payload

    def with_hash(self) -> "CareDay":
        digest = hashlib.sha256(
            json.dumps(self.hashed_payload(), sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return self.model_copy(update={"content_hash": f"sha256:{digest}"})


def _boundary() -> tuple[int, int]:
    """The care-day boundary db itself applies, not a second reading of the setting."""
    return db._DAY_START_HOUR, db._DAY_START_MINUTE


def day_start() -> str:
    hour, minute = _boundary()
    return f"{hour:02d}:{minute:02d}"


def occurred_local(row: sqlite3.Row, tz: ZoneInfo) -> datetime:
    """Local time of an event.

    A handful of early rows were written without an offset. Reading those as system
    local time would make the export depend on where it runs, so they are read as the
    configured zone, which is what they were recorded in.
    """
    moment = datetime.fromisoformat(row["occurred_at"])
    if moment.tzinfo is None:
        return moment.replace(tzinfo=tz)
    return moment.astimezone(tz)


def care_day_of(row: sqlite3.Row, tz: ZoneInfo) -> date:
    """Which care day an event falls in.

    The shift is done on wall-clock time rather than on the instant, so a day keeps
    starting at DAY_START local across a daylight-saving change.
    """
    hour, minute = _boundary()
    local = occurred_local(row, tz)
    return (local.replace(tzinfo=None) - timedelta(hours=hour, minutes=minute)).date()


def window_of(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    hour, minute = _boundary()
    start = datetime.combine(day, time(hour, minute), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(hour, minute), tzinfo=tz)
    return start, end


def _rows(conn: sqlite3.Connection, subject: str, since: date, until: date) -> list[sqlite3.Row]:
    """Rows for the window, widened by a day so a boundary shift cannot drop events."""
    return list(
        conn.execute(
            "SELECT * FROM events WHERE subject = ? AND day BETWEEN ? AND ? ORDER BY occurred_at, id",
            (subject, (since - timedelta(days=1)).isoformat(), (until + timedelta(days=1)).isoformat()),
        )
    )


def assert_subjects_present(conn: sqlite3.Connection, since: date, until: date) -> None:
    """Refuse to export a window containing an event whose animal is not recorded.

    The check covers every subject, not only the one requested: an event with no
    subject cannot be shown to belong to someone else.
    """
    missing = conn.execute(
        "SELECT count(*) FROM events WHERE subject IS NULL AND day BETWEEN ? AND ?",
        ((since - timedelta(days=1)).isoformat(), (until + timedelta(days=1)).isoformat()),
    ).fetchone()[0]
    if missing:
        raise SystemExit(
            f"care-export: {missing} event(s) in {since}..{until} have no subject. "
            "Exporting them would attribute one animal's history to another. "
            "Run the bot once to apply the subject migration, then re-check."
        )


def _food(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    return [r for r in rows if r["type"] == "food"]


def _kcal(rows: list[sqlite3.Row]) -> tuple[float | None, bool, int]:
    """Calories for the day, and whether every recorded feeding contributed one.

    No feeding recorded is not a fasted day, and feedings whose calories are unknown
    do not sum to zero: both are null, flagged incomplete.
    """
    food = _food(rows)
    counted = [r for r in food if r["kcal"]]
    if not counted:
        return None, False, len(food)
    return round(summary.kcal_total(counted), 1), len(counted) == len(food), len(food)


def _drinking(rows: list[sqlite3.Row]) -> tuple[float | None, bool]:
    water = [r for r in rows if r["type"] == "water"]
    measured = [r for r in water if r["water_ml"] is not None]
    if not measured:
        return None, False
    return round(sum(r["water_ml"] for r in measured), 1), len(measured) == len(water)


def _water_from_food(rows: list[sqlite3.Row]) -> tuple[float | None, bool]:
    food = _food(rows)
    if not food:
        return None, False
    wet_without_amount = summary.uncounted_wet(rows)
    return round(summary.water_from_food(food), 1), wet_without_amount == 0


def _toilet(rows: list[sqlite3.Row]) -> tuple[int | None, int | None]:
    """Counts of what was recorded, never a claim about what did not happen.

    Each kind is counted on its own. Logging a urination says nothing about whether
    the cat also defecated unobserved, so no stool event means unknown, not zero, even
    on a day full of other toilet records. cat-care has no way to express "the owner
    watched all day and there was none", so no asserted-absence field exists here.
    """
    toilet = [r for r in rows if r["type"] == "toilet"]
    stools = sum(1 for r in toilet if db.is_stool(r["description"]))
    urinations = len(toilet) - stools
    return (urinations or None), (stools or None)


def _narrative(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    return [r for r in rows if r["type"] in ("state", "other")]


def _vomiting(rows: list[sqlite3.Row], tz: ZoneInfo) -> tuple[list[VomitingEpisode], bool]:
    episodes, asserted_absent = [], False
    for row in _narrative(rows):
        text = row["description"] or ""
        if summary._NO_VOMIT_RE.search(text):
            asserted_absent = True
        elif summary._VOMIT_RE.search(text):
            episodes.append(VomitingEpisode(at=occurred_local(row, tz), note=text or None))
    return episodes, asserted_absent


def build_day(subject: str, day: date, rows: list[sqlite3.Row], tz: ZoneInfo, now: datetime,
              debug: bool = False) -> CareDay:
    start, end = window_of(day, tz)
    kcal, kcal_complete, food_events = _kcal(rows)
    drinking, drinking_complete = _drinking(rows)
    from_food, from_food_complete = _water_from_food(rows)
    urinations, stools = _toilet(rows)
    episodes, asserted_absent = _vomiting(rows, tz)
    return CareDay(
        source_instance=source_instance(),
        subject_id=subject,
        care_day=day,
        day_start=day_start(),
        timezone=str(tz),
        window_start=start,
        window_end=end,
        exported_at=now,
        partial=now < end,
        food_kcal=kcal,
        food_kcal_fully_quantified=kcal_complete,
        food_events_recorded=food_events,
        water_drinking_ml=drinking,
        water_drinking_fully_quantified=drinking_complete,
        water_from_food_ml=from_food,
        water_from_food_fully_quantified=from_food_complete,
        urinations_observed=urinations,
        stools_observed=stools,
        temperatures=[
            TemperatureReading(at=occurred_local(r, tz), value_c=r["temp_c"])
            for r in rows
            if r["type"] == "temperature" and r["temp_c"] is not None
        ],
        vomiting_episodes=episodes,
        vomiting_asserted_absent=asserted_absent,
        medications=[
            MedicationAdministration(
                at=occurred_local(r, tz), name=r["name"], dose_text=r["dose"], note=r["description"] or None
            )
            for r in rows
            if r["type"] == "medication"
        ],
        notes=[
            OwnerNote(at=occurred_local(r, tz), kind=r["type"], text=r["description"])
            for r in rows
            if r["type"] == "state" and r["description"]
        ],
        debug_event_refs=sorted(r["id"] for r in rows) if debug else None,
    ).with_hash()


def export(subject: str, since: date, until: date, now: datetime | None = None,
           debug: bool = False) -> list[CareDay]:
    tz = timezone()
    now = now or datetime.now(tz)
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        assert_subjects_present(conn, since, until)
        rows = _rows(conn, subject, since, until)
    buckets: dict[date, list[sqlite3.Row]] = {}
    for row in rows:
        buckets.setdefault(care_day_of(row, tz), []).append(row)
    days = []
    day = since
    while day <= until:
        days.append(build_day(subject, day, buckets.get(day, []), tz, now, debug))
        day += timedelta(days=1)
    return days


def _date(text: str) -> date:
    return date.fromisoformat(text)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="care-export",
        description="Export CareDay v1 records as JSONL. Reads the database; writes nothing.",
    )
    parser.add_argument("--subject", required=True, help="subject id, e.g. chipunya")
    parser.add_argument("--since", required=True, type=_date, help="first care day, YYYY-MM-DD")
    parser.add_argument("--until", required=True, type=_date, help="last care day, YYYY-MM-DD")
    parser.add_argument("--json", action="store_true", help="output JSONL (the default; accepted for symmetry)")
    parser.add_argument("--pretty", action="store_true", help="indent each record, for reading by eye")
    parser.add_argument("--debug", action="store_true",
                        help="add debug_event_refs: database row ids, unstable and not part of the contract")
    args = parser.parse_args()
    if args.since > args.until:
        parser.error(f"--since {args.since} is after --until {args.until}")
    hidden = set() if args.debug else {"debug_event_refs"}
    for day in export(args.subject, args.since, args.until, debug=args.debug):
        payload = day.model_dump(mode="json", exclude=hidden)
        print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
