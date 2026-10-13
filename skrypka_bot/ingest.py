"""Turning parsed events into diary rows: their time, and what a repeated report replaces."""

import logging
import re
import sqlite3
from datetime import date, datetime, timedelta

from . import classify, db, figures, foods, profiles

logger = logging.getLogger(__name__)

FOOD_DEDUP_WINDOW = timedelta(minutes=5)


MEDICATION_DEDUP_WINDOW = timedelta(minutes=10)


LATE_REPORT_DAYS = 31


WATER_DEDUP_WINDOW = timedelta(minutes=5)


_AMOUNT_ML_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*мл", re.IGNORECASE)


_AMOUNT_G_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:г|гр|грамм\w*)\b", re.IGNORECASE)


def _event_day(sent_at: datetime, event) -> date | None:
    named = getattr(event, "date", None)
    if named:
        try:
            day, month = (int(part) for part in named.split(".")[:2])
            stated = date(sent_at.year, month, day)
            if stated > sent_at.date():
                stated = date(sent_at.year - 1, month, day)
        except ValueError:
            return None
        return stated if (sent_at.date() - stated).days <= LATE_REPORT_DAYS else None
    days_ago = getattr(event, "days_ago", None)
    if isinstance(days_ago, int) and 0 < days_ago <= 7:
        return sent_at.date() - timedelta(days=days_ago)
    return None


def _event_time(sent_at: datetime, event) -> datetime:
    day = _event_day(sent_at, event)
    base = sent_at if day is None else sent_at.replace(year=day.year, month=day.month, day=day.day)
    mentioned = getattr(event, "time", None)
    if not mentioned:
        return base
    try:
        hour, minute = (int(part) for part in mentioned.split(":"))
        occurred = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return base
    if day is None and occurred > sent_at + timedelta(minutes=5):
        occurred -= timedelta(days=1)
    return occurred


def _detail_score(kcal, feeding) -> int:
    return (2 if kcal else 0) + (1 if feeding else 0)


def _backfill_amount_ml(event) -> None:
    if event.amount_ml is not None or not event.description:
        return
    match = _AMOUNT_ML_RE.search(event.description)
    if match is None and (event.liquid or event.feeding == "tube"):
        match = _AMOUNT_G_RE.search(event.description)
    if match:
        event.amount_ml = float(match.group(1).replace(",", "."))


def _replace_rows(conn: sqlite3.Connection, ids: list[int], replacement: str) -> None:
    edited_at = datetime.now().astimezone()
    for event_id in ids:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        db.log_edit(conn, event_id, edited_at, "dedup", dict(row), {"replaced_by": replacement})
    conn.execute(f"DELETE FROM events WHERE id IN ({','.join('?' * len(ids))})", ids)


def _keeps_manual(rows: list[sqlite3.Row], kind: str, event) -> bool:
    if any(row["message_id"] is None for row in rows):
        logger.info("Keeping a manually added %s over: %r", kind, event.description)
        return True
    return False


def _is_separate_portion(existing_ml, new_ml) -> bool:
    return existing_ml is not None and new_ml is not None and existing_ml != new_ml


def _same_form(row: sqlite3.Row, event) -> bool:
    return bool(row["liquid"] or figures.is_given(row)) == bool(
        event.liquid or event.feeding == "tube"
    )


def _dedup_food(conn: sqlite3.Connection, chat_id: int, occurred_at: datetime, event) -> bool:
    lo = (occurred_at - FOOD_DEDUP_WINDOW).isoformat()
    hi = (occurred_at + FOOD_DEDUP_WINDOW).isoformat()
    existing = [
        row
        for row in conn.execute(
            "SELECT id, message_id, kcal, feeding, amount_ml, liquid, description FROM events "
            "WHERE chat_id = ? AND type = 'food' AND occurred_at BETWEEN ? AND ?",
            (chat_id, lo, hi),
        )
        if _same_form(row, event) and not _is_separate_portion(row["amount_ml"], event.amount_ml)
    ]
    if not existing:
        return True
    if _keeps_manual(existing, "feeding", event):
        return False
    best = max(_detail_score(row["kcal"], row["feeding"]) for row in existing)
    if _detail_score(event.kcal, event.feeding) <= best:
        logger.info("Skipping duplicate feeding: %r", event.description)
        return False
    ids = [row["id"] for row in existing]
    _replace_rows(conn, ids, event.description)
    logger.info("Replacing %d less detailed feeding(s) with: %r", len(ids), event.description)
    return True


def _dedup_toilet(
    conn: sqlite3.Connection, chat_id: int, message_id: int, occurred_at: datetime, event
) -> bool:
    lo = (occurred_at - FOOD_DEDUP_WINDOW).isoformat()
    hi = (occurred_at + FOOD_DEDUP_WINDOW).isoformat()
    kind = classify.toilet_kind(event.description)
    same_kind = [
        row
        for row in conn.execute(
            "SELECT id, message_id, description FROM events "
            "WHERE chat_id = ? AND type = 'toilet' AND occurred_at BETWEEN ? AND ? "
            "AND message_id IS NOT ?",
            (chat_id, lo, hi, message_id),
        )
        if classify.toilet_kind(row["description"]) == kind
    ]
    if not same_kind:
        return True
    if _keeps_manual(same_kind, "toilet visit", event):
        return False
    if len(event.description or "") <= max(len(row["description"] or "") for row in same_kind):
        logger.info("Skipping duplicate toilet: %r", event.description)
        return False
    ids = [row["id"] for row in same_kind]
    _replace_rows(conn, ids, event.description)
    return True


def _med_detail(dose, description) -> tuple[int, int]:
    return (1 if dose else 0, len(description or ""))


def _dedup_medication(
    conn: sqlite3.Connection, chat_id: int, occurred_at: datetime, event
) -> bool:
    name = (event.name or "").strip().lower()
    if not name:
        return True
    lo = (occurred_at - MEDICATION_DEDUP_WINDOW).isoformat()
    hi = (occurred_at + MEDICATION_DEDUP_WINDOW).isoformat()
    same_drug = [
        row
        for row in conn.execute(
            "SELECT id, message_id, name, dose, description FROM events "
            "WHERE chat_id = ? AND type = 'medication' AND occurred_at BETWEEN ? AND ?",
            (chat_id, lo, hi),
        )
        if (row["name"] or "").strip().lower() == name
    ]
    if not same_drug:
        return True
    if _keeps_manual(same_drug, "medication", event):
        return False
    best = max(_med_detail(row["dose"], row["description"]) for row in same_drug)
    if _med_detail(event.dose, event.description) <= best:
        logger.info("Skipping duplicate medication: %r", event.description)
        return False
    ids = [row["id"] for row in same_drug]
    _replace_rows(conn, ids, event.description)
    logger.info("Replacing %d less detailed medication(s) with: %r", len(ids), event.description)
    return True


def _states_ml(text: str | None) -> bool:
    return bool(_AMOUNT_ML_RE.search(text or ""))


def _drop_water_estimates(
    conn: sqlite3.Connection, chat_id: int, occurred_at: datetime, text: str
) -> None:
    if not _states_ml(text):
        return
    lo = (occurred_at - WATER_DEDUP_WINDOW).isoformat()
    hi = (occurred_at + WATER_DEDUP_WINDOW).isoformat()
    stale = [
        row["id"]
        for row in conn.execute(
            "SELECT e.id AS id, m.text AS source FROM events e "
            "LEFT JOIN messages m ON m.chat_id = e.chat_id AND m.message_id = e.message_id "
            "WHERE e.chat_id = ? AND e.type = 'water' AND e.occurred_at BETWEEN ? AND ? "
            "AND e.message_id IS NOT NULL",
            (chat_id, lo, hi),
        )
        if not _states_ml(row["source"])
    ]
    if not stale:
        return
    _replace_rows(conn, stale, text)
    logger.info("Replacing %d estimated water event(s) with exact %r", len(stale), text[:60])


def save_message(
    chat_id: int,
    message_id: int,
    sender: str,
    sent_at: datetime,
    text: str,
    events: list,
    parsed: bool = True,
) -> None:
    with db.connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO messages (chat_id, message_id, sender, sent_at, text, parsed) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, message_id, sender, sent_at.isoformat(), text, 1 if parsed else 0),
        )
        if cursor.rowcount == 0:
            logger.info("Message %s already processed, skipping events", message_id)
            return
        _insert_events(conn, chat_id, message_id, sent_at, text, events)


def store_reparsed(
    chat_id: int, message_id: int, sent_at: datetime, text: str, events: list
) -> None:
    with db.connect() as conn:
        _insert_events(conn, chat_id, message_id, sent_at, text, events)
        conn.execute(
            "UPDATE messages SET parsed = 1 WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        )


def replace_message_events(
    chat_id: int, message_id: int, text: str, events: list, edited_at: datetime
) -> None:
    with db.connect() as conn:
        sent_at = datetime.fromisoformat(conn.execute(
            "SELECT sent_at FROM messages WHERE chat_id = ? AND message_id = ?", (chat_id, message_id)
        ).fetchone()["sent_at"])
        old = conn.execute(
            "SELECT * FROM events WHERE chat_id = ? AND message_id = ?", (chat_id, message_id)
        ).fetchall()
        for row in old:
            db.log_edit(conn, row["id"], edited_at, "reparse", dict(row), {"message_text": text})
        conn.execute("DELETE FROM events WHERE chat_id = ? AND message_id = ?", (chat_id, message_id))
        conn.execute(
            "UPDATE messages SET text = ?, parsed = 1 WHERE chat_id = ? AND message_id = ?",
            (text, chat_id, message_id),
        )
        _insert_events(conn, chat_id, message_id, sent_at, text, events)


def _profile_of(conn: sqlite3.Connection, chat_id: int) -> profiles.Profile:
    profile = db.animal_in(conn, chat_id)
    if profile is None:
        raise ValueError(f"chat {chat_id} has no profile, its events belong to no animal")
    return profile


def _insert_events(
    conn: sqlite3.Connection,
    chat_id: int,
    message_id: int,
    sent_at: datetime,
    text: str,
    events: list,
) -> None:
    is_recap = classify.is_recap(text)
    profile = _profile_of(conn, chat_id)
    subject = profile.subject_id
    for event in events:
        if is_recap and event.type in ("water", "food"):
            logger.info("Skipping recap-derived %s event: %r", event.type, event.description)
            continue
        occurred_at = _event_time(sent_at, event)
        if event.type == "food":
            _backfill_amount_ml(event)
            foods.fill_gravy(event)
            if (
                event.feeding == "tube"
                and profile.tube
                and event.amount_ml
                and event.amount_ml > profile.tube.max_feed_ml
            ):
                logger.info(
                    "Skipping implausible tube feeding %g ml (>%g): %r",
                    event.amount_ml,
                    profile.tube.max_feed_ml,
                    event.description,
                )
                continue
            if not _dedup_food(conn, chat_id, occurred_at, event):
                continue
        elif event.type == "water":
            _drop_water_estimates(conn, chat_id, occurred_at, text)
        elif event.type == "toilet":
            if not _dedup_toilet(conn, chat_id, message_id, occurred_at, event):
                continue
        elif event.type == "medication":
            if not _dedup_medication(conn, chat_id, occurred_at, event):
                continue
        conn.execute(
            "INSERT INTO events "
            "(chat_id, subject, message_id, occurred_at, day, type, name, dose, water_ml, kcal, feeding, amount_ml, temp_c, liquid, water_fraction, weight_kg, breaths, asleep, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                subject,
                message_id,
                occurred_at.isoformat(),
                db.care_day(occurred_at).isoformat(),
                event.type,
                event.name,
                event.dose,
                event.water_ml,
                event.kcal,
                event.feeding,
                event.amount_ml,
                event.temp_c,
                1 if event.liquid else None,
                event.water_fraction,
                getattr(event, "weight_kg", None),
                getattr(event, "breaths_per_min", None),
                {True: 1, False: 0}.get(getattr(event, "asleep", None)),
                event.description,
            ),
        )

