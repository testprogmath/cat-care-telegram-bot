import json
import logging
import os
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import profiles, schema

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("DB_PATH", "data/skrypka.db"))


DAY_START = os.environ.get("DAY_START", "00:00")
_DAY_START_HOUR, _DAY_START_MINUTE = (int(part) for part in DAY_START.split(":"))


def boundary() -> tuple[int, int]:
    return _DAY_START_HOUR, _DAY_START_MINUTE


def timezone() -> ZoneInfo:
    return ZoneInfo(os.environ.get("TIMEZONE", "Europe/Berlin"))


def care_day(moment: datetime) -> date:
    """The care day a moment falls in, on the wall clock of TIMEZONE.

    A moment without an offset is read as that wall clock. Shifting wall-clock time rather
    than the instant keeps a day starting at DAY_START across a daylight-saving change.
    """
    local = moment.astimezone(timezone()).replace(tzinfo=None) if moment.tzinfo else moment
    return (local - timedelta(hours=_DAY_START_HOUR, minutes=_DAY_START_MINUTE)).date()


def care_day_start(day: date, tz) -> datetime:
    return datetime(day.year, day.month, day.day, _DAY_START_HOUR, _DAY_START_MINUTE, tzinfo=tz)


def connect() -> sqlite3.Connection:
    if os.environ.get("DB_READ_ONLY"):
        conn = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as conn:
        schema.apply(conn)


_CHAT_ANIMAL = "SELECT chat_id, profile, tube_out_at, kcal_goal, water_goal_ml FROM chats WHERE chat_id = ?"


def _animal(row: sqlite3.Row | None) -> profiles.Profile | None:
    profile = profiles.get(row["profile"]) if row else None
    if profile is None:
        return None
    if profile.tube and row["tube_out_at"]:
        profile = replace(profile, tube=None)
    return profile.with_goals(kcal=row["kcal_goal"], water_ml=row["water_goal_ml"])


class ProfileTaken(Exception):
    """Another chat already keeps this animal's diary."""


def upsert_chat(chat_id: int, title: str | None) -> profiles.Profile | None:
    with connect() as conn:
        taken = frozenset(
            row["profile"]
            for row in conn.execute(
                "SELECT profile FROM chats WHERE profile IS NOT NULL AND chat_id != ?", (chat_id,)
            )
        )
        conn.execute(
            "INSERT INTO chats (chat_id, title, profile) VALUES (?, ?, ?) "
            "ON CONFLICT (chat_id) DO UPDATE SET title = excluded.title",
            (chat_id, title, profiles.guess(title, taken)),
        )
        row = conn.execute(_CHAT_ANIMAL, (chat_id,)).fetchone()
    return _animal(row)


def animal_in(conn: sqlite3.Connection, chat_id: int) -> profiles.Profile | None:
    return _animal(conn.execute(_CHAT_ANIMAL, (chat_id,)).fetchone())


def profile_for(chat_id: int) -> profiles.Profile | None:
    with connect() as conn:
        return animal_in(conn, chat_id)


def set_profile(chat_id: int, key: str | None) -> None:
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO chats (chat_id, profile) VALUES (?, ?) "
                "ON CONFLICT (chat_id) DO UPDATE SET profile = excluded.profile",
                (chat_id, key),
            )
    except sqlite3.IntegrityError as exc:
        raise ProfileTaken(key) from exc


def chats() -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute("SELECT chat_id, title, profile FROM chats ORDER BY chat_id"))


def chat(chat_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT chat_id, title, profile FROM chats WHERE chat_id = ?", (chat_id,)
        ).fetchone()


def _with_profiles(rows) -> list[tuple[int, profiles.Profile]]:
    known = [(row["chat_id"], _animal(row)) for row in rows]
    return [(chat_id, profile) for chat_id, profile in known if profile is not None]


def all_chats() -> list[tuple[int, profiles.Profile]]:
    with connect() as conn:
        return _with_profiles(conn.execute("SELECT chat_id, profile, tube_out_at, kcal_goal, water_goal_ml FROM chats"))


def active_chats() -> list[tuple[int, profiles.Profile]]:
    with connect() as conn:
        return _with_profiles(
            conn.execute(
                "SELECT chat_id, profile, tube_out_at, kcal_goal, water_goal_ml FROM chats WHERE paused_at IS NULL"
            )
        )


def tube_out_since(chat_id: int) -> datetime | None:
    with connect() as conn:
        row = conn.execute("SELECT tube_out_at FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
    if row is None or not row["tube_out_at"]:
        return None
    return datetime.fromisoformat(row["tube_out_at"])


def set_tube_out(chat_id: int, at: datetime | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE chats SET tube_out_at = ? WHERE chat_id = ?",
            (at.isoformat() if at else None, chat_id),
        )


GOAL_COLUMNS = {"food": "kcal_goal", "water": "water_goal_ml"}


def set_goal(chat_id: int, kind: str, value: float | None) -> None:
    """A chat's own goal for food or water; None goes back to the animal's configured one."""
    with connect() as conn:
        conn.execute(f"UPDATE chats SET {GOAL_COLUMNS[kind]} = ? WHERE chat_id = ?", (value, chat_id))


def paused_since(chat_id: int) -> datetime | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT paused_at FROM chats WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    if row is None or not row["paused_at"]:
        return None
    return datetime.fromisoformat(row["paused_at"])


def set_paused(chat_id: int, at: datetime | None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO chats (chat_id, paused_at) VALUES (?, ?) "
            "ON CONFLICT (chat_id) DO UPDATE SET paused_at = excluded.paused_at",
            (chat_id, at.isoformat() if at else None),
        )


def auto_left(chat_id: int) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT auto_left FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
    return row is None or bool(row["auto_left"])


def set_auto_left(chat_id: int, on: bool) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO chats (chat_id, auto_left) VALUES (?, ?) "
            "ON CONFLICT (chat_id) DO UPDATE SET auto_left = excluded.auto_left",
            (chat_id, 1 if on else 0),
        )


def recent_messages(
    chat_id: int, before: datetime, window: timedelta, limit: int = 6
) -> list[tuple[str, str]]:
    since = (before - window).isoformat()
    with connect() as conn:
        rows = conn.execute(
            "SELECT sent_at, text FROM messages "
            "WHERE chat_id = ? AND sent_at < ? AND sent_at >= ? ORDER BY sent_at DESC LIMIT ?",
            (chat_id, before.isoformat(), since, limit),
        ).fetchall()
    return [(r["sent_at"], r["text"]) for r in reversed(rows)]


def message_seen(chat_id: int, message_id: int) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM messages WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        ).fetchone()
        return row is not None


def note_bot_report(chat_id: int, message_id: int, sent_at: datetime, marker: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO messages (chat_id, message_id, sender, sent_at, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, message_id, "bot", sent_at.isoformat(), marker),
        )


def last_message_at(chat_id: int) -> datetime | None:
    with connect() as conn:
        row = conn.execute("SELECT MAX(sent_at) AS at FROM messages WHERE chat_id = ?", (chat_id,)).fetchone()
    return datetime.fromisoformat(row["at"]) if row["at"] else None


def toilet_events(chat_id: int, message_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute(
            "SELECT * FROM events WHERE chat_id = ? AND message_id = ? AND type = 'toilet' ORDER BY id",
            (chat_id, message_id),
        ))


def note_stool_question(chat_id: int, question_id: int, message_id: int, asked_at: datetime) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO stool_questions (chat_id, question_id, message_id, asked_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, question_id, message_id, asked_at.isoformat()),
        )


def open_stool_question(chat_id: int, since: datetime) -> int | None:
    """The latest unanswered stool question asked since then, by its question id."""
    with connect() as conn:
        row = conn.execute(
            "SELECT question_id FROM stool_questions "
            "WHERE chat_id = ? AND answered_at IS NULL AND asked_at >= ? "
            "ORDER BY asked_at DESC LIMIT 1",
            (chat_id, since.isoformat()),
        ).fetchone()
    return row["question_id"] if row else None


def mark_stool_answered(chat_id: int, question_id: int, at: datetime) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE stool_questions SET answered_at = ? WHERE chat_id = ? AND question_id = ?",
            (at.isoformat(), chat_id, question_id),
        )


def message_figures(chat_id: int, message_id: int) -> list[tuple]:
    """What a message adds to the day's totals, to tell whether an edit changed them."""
    with connect() as conn:
        return [tuple(row) for row in conn.execute(
            "SELECT type, kcal, water_ml, amount_ml, water_fraction, liquid, feeding FROM events "
            "WHERE chat_id = ? AND message_id = ? AND type IN ('food', 'water') "
            "ORDER BY type, kcal, water_ml, amount_ml",
            (chat_id, message_id),
        )]


def food_events(chat_id: int, message_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute(
            "SELECT * FROM events WHERE chat_id = ? AND message_id = ? AND type = 'food' ORDER BY id",
            (chat_id, message_id),
        ))


def note_pieces_question(chat_id: int, question_id: int, event_id: int, asked_at: datetime) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pieces_questions (chat_id, question_id, event_id, asked_at) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, question_id, event_id, asked_at.isoformat()),
        )


def pieces_question(chat_id: int, question_id: int) -> int | None:
    """The feeding the bot asked about the pieces of with this question."""
    with connect() as conn:
        row = conn.execute(
            "SELECT event_id FROM pieces_questions WHERE chat_id = ? AND question_id = ?",
            (chat_id, question_id),
        ).fetchone()
    return row["event_id"] if row else None


def open_pieces_question(chat_id: int, since: datetime) -> int | None:
    """The one unanswered pieces question asked since then; None when there are none or several."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT question_id FROM pieces_questions "
            "WHERE chat_id = ? AND answered_at IS NULL AND asked_at >= ? LIMIT 2",
            (chat_id, since.isoformat()),
        ).fetchall()
    return rows[0]["question_id"] if len(rows) == 1 else None


def mark_pieces_answered(chat_id: int, question_id: int, at: datetime) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE pieces_questions SET answered_at = ? WHERE chat_id = ? AND question_id = ?",
            (at.isoformat(), chat_id, question_id),
        )


def stool_question(chat_id: int, question_id: int) -> int | None:
    """The message whose stool the bot asked about with this question."""
    with connect() as conn:
        row = conn.execute(
            "SELECT message_id FROM stool_questions WHERE chat_id = ? AND question_id = ?",
            (chat_id, question_id),
        ).fetchone()
    return row["message_id"] if row else None


def message_added_kcal(chat_id: int, message_id: int) -> bool:
    with connect() as conn:
        return conn.execute(
            "SELECT 1 FROM events WHERE chat_id = ? AND message_id = ? AND type = 'food' AND kcal > 0",
            (chat_id, message_id),
        ).fetchone() is not None


def unparsed_messages(limit: int = 20) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT chat_id, message_id, sent_at, text FROM messages "
                "WHERE parsed = 0 ORDER BY sent_at LIMIT ?",
                (limit,),
            )
        )


def events_for_day(subject: str, day: date) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT * FROM events WHERE subject = ? AND day = ? ORDER BY occurred_at",
                (subject, day.isoformat()),
            )
        )


def events_in_days(subject: str, day_from: date, day_to: date) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT * FROM events WHERE subject = ? AND day BETWEEN ? AND ? ORDER BY occurred_at",
                (subject, day_from.isoformat(), day_to.isoformat()),
            )
        )


def medications_in_days(subject: str, day_from: date, day_to: date) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT * FROM events WHERE subject = ? AND type = 'medication' "
                "AND day BETWEEN ? AND ? ORDER BY occurred_at",
                (subject, day_from.isoformat(), day_to.isoformat()),
            )
        )


def last_weight(subject: str) -> tuple[date, float] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT day, weight_kg FROM events WHERE subject = ? AND type = 'weight' AND weight_kg > 0 "
            "ORDER BY occurred_at DESC LIMIT 1",
            (subject,),
        ).fetchone()
    return None if row is None else (date.fromisoformat(row["day"]), row["weight_kg"])


def first_event_day(subject: str) -> date | None:
    with connect() as conn:
        (day,) = conn.execute("SELECT min(day) FROM events WHERE subject = ?", (subject,)).fetchone()
    return None if day is None else date.fromisoformat(day)


def events_with_messages(subject: str, day_from: date, day_to: date) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT e.*, m.text AS message_text FROM events e LEFT JOIN messages m "
                "ON m.chat_id = e.chat_id AND m.message_id = e.message_id "
                "WHERE e.subject = ? AND e.day BETWEEN ? AND ? ORDER BY e.occurred_at, e.id",
                (subject, day_from.isoformat(), day_to.isoformat()),
            )
        )


def events_in_range(subject: str, start: datetime, end: datetime) -> list[sqlite3.Row]:
    lo_day = care_day(start)
    hi_day = end.date()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE subject = ? AND day BETWEEN ? AND ? ORDER BY occurred_at",
            (subject, lo_day.isoformat(), hi_day.isoformat()),
        )
        return [r for r in rows if start <= datetime.fromisoformat(r["occurred_at"]) < end]


EDITABLE_COLUMNS = (
    "type",
    "description",
    "kcal",
    "water_ml",
    "amount_ml",
    "water_fraction",
    "name",
    "dose",
    "liquid",
    "feeding",
    "weight_kg",
    "breaths",
    "asleep",
    "stool_score",
    "pieces",
    "occurred_at",
    "day",
)

_EVENT_WITH_SOURCE = (
    "SELECT e.*, m.text AS message_text FROM events e "
    "LEFT JOIN messages m ON m.chat_id = e.chat_id AND m.message_id = e.message_id "
    "WHERE e.id = ?"
)


def _event_with_source(conn: sqlite3.Connection, event_id: int) -> sqlite3.Row | None:
    return conn.execute(_EVENT_WITH_SOURCE, (event_id,)).fetchone()


def log_edit(
    conn: sqlite3.Connection,
    event_id: int,
    edited_at: datetime,
    action: str,
    before: dict,
    after: dict | None,
) -> None:
    conn.execute(
        "INSERT INTO event_edits (event_id, edited_at, action, before, after) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            event_id,
            edited_at.isoformat(),
            action,
            json.dumps(before, ensure_ascii=False),
            None if after is None else json.dumps(after, ensure_ascii=False),
        ),
    )


def event_by_id(event_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return _event_with_source(conn, event_id)


def list_events(
    day: date, subject: str | None = None, event_type: str | None = None
) -> list[sqlite3.Row]:
    filters = [("day = ?", day.isoformat())]
    if subject is not None:
        filters.append(("subject = ?", subject))
    if event_type is not None:
        filters.append(("type = ?", event_type))
    where = " AND ".join(clause for clause, _ in filters)
    with connect() as conn:
        return list(
            conn.execute(
                f"SELECT * FROM events WHERE {where} ORDER BY occurred_at, id",
                [value for _, value in filters],
            )
        )


def update_event(
    event_id: int, changes: dict[str, object], edited_at: datetime
) -> sqlite3.Row | None:
    unknown = set(changes) - set(EDITABLE_COLUMNS)
    if unknown:
        raise ValueError(f"not editable: {', '.join(sorted(unknown))}")
    with connect() as conn:
        current = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if current is None:
            return None
        changed = {key: value for key, value in changes.items() if current[key] != value}
        if changed:
            assignments = ", ".join(f"{column} = ?" for column in changed)
            conn.execute(
                f"UPDATE events SET {assignments} WHERE id = ?",
                [*changed.values(), event_id],
            )
            before = {column: current[column] for column in changed}
            log_edit(conn, event_id, edited_at, "update", before, changed)
        return _event_with_source(conn, event_id)


def chat_for_subject(subject: str) -> int | None:
    return next((chat_id for chat_id, profile in all_chats() if profile.subject_id == subject), None)


def create_event(chat_id: int, subject: str, fields: dict[str, object], edited_at: datetime) -> sqlite3.Row:
    unknown = set(fields) - set(EDITABLE_COLUMNS)
    if unknown:
        raise ValueError(f"not editable: {', '.join(sorted(unknown))}")
    values = {"chat_id": chat_id, "subject": subject, **fields}
    columns = ", ".join(values)
    with connect() as conn:
        cursor = conn.execute(
            f"INSERT INTO events ({columns}) VALUES ({', '.join('?' * len(values))})",
            list(values.values()),
        )
        log_edit(conn, cursor.lastrowid, edited_at, "create", {}, values)
        return _event_with_source(conn, cursor.lastrowid)


def delete_event(event_id: int, edited_at: datetime) -> sqlite3.Row | None:
    with connect() as conn:
        row = _event_with_source(conn, event_id)
        if row is None:
            return None
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        stored = {key: row[key] for key in row.keys() if key != "message_text"}  # noqa: SIM118 sqlite3.Row `in` checks values, not keys
        log_edit(conn, event_id, edited_at, "delete", stored, None)
        return row


def edits_for_event(event_id: int) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT * FROM event_edits WHERE event_id = ? ORDER BY id DESC",
                (event_id,),
            )
        )
