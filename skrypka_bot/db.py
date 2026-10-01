import json
import logging
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from . import profiles

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get("DB_PATH", "data/skrypka.db"))
FOOD_DEDUP_WINDOW = timedelta(minutes=5)
MEDICATION_DEDUP_WINDOW = timedelta(minutes=10)
WATER_DEDUP_WINDOW = timedelta(minutes=5)
_AMOUNT_ML_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*мл", re.IGNORECASE)
_AMOUNT_G_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:г|гр|грамм\w*)\b", re.IGNORECASE)

TUBE_MAX_SINGLE_ML = float(os.environ.get("TUBE_MAX_SINGLE_ML", "100"))
LIQUID_FOOD_WATER_FRACTION = float(os.environ.get("LIQUID_FOOD_WATER_FRACTION", "0.85"))
_RECAP_RE = re.compile(
    r"если считать|суммарно|в сумме|за день|за сутки|минимум\s+\d+\s*мл|всего\b.{0,30}\bпоступил",
    re.IGNORECASE,
)
_STOOL_RE = re.compile(
    r"покака|покак|какаш|дефекац|стул|диаре|диарре|понос|\bкал\b", re.IGNORECASE
)


def is_stool(description: str) -> bool:
    return bool(_STOOL_RE.search(description or ""))


def is_liquid_food(row: sqlite3.Row) -> bool:
    return row["type"] == "food" and bool(row["feeding"] == "tube" or row["liquid"])


def food_water_ml(row: sqlite3.Row) -> float:
    if not is_liquid_food(row):
        return 0.0
    return (row["amount_ml"] or 0) * (row["water_fraction"] or LIQUID_FOOD_WATER_FRACTION)

DAY_START = os.environ.get("DAY_START", "11:00")
_DAY_START_HOUR, _DAY_START_MINUTE = (int(part) for part in DAY_START.split(":"))


def care_day(dt: datetime) -> date:
    return (dt - timedelta(hours=_DAY_START_HOUR, minutes=_DAY_START_MINUTE)).date()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                title   TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id    INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                sender     TEXT,
                sent_at    TEXT NOT NULL,
                text       TEXT NOT NULL,
                UNIQUE (chat_id, message_id)
            );
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     INTEGER NOT NULL,
                message_id  INTEGER,
                occurred_at TEXT NOT NULL,
                day         TEXT NOT NULL,
                type        TEXT NOT NULL,
                name        TEXT,
                dose        TEXT,
                water_ml    REAL,
                description TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_chat_day ON events (chat_id, day);
            CREATE TABLE IF NOT EXISTS event_edits (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id  INTEGER NOT NULL,
                edited_at TEXT NOT NULL,
                action    TEXT NOT NULL,
                before    TEXT NOT NULL,
                after     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_event_edits_event ON event_edits (event_id);
            """
        )
        chat_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chats)")}
        if "profile" not in chat_columns:
            conn.execute("ALTER TABLE chats ADD COLUMN profile TEXT")
            conn.execute("UPDATE chats SET profile = ?", (profiles.DEFAULT_KEY,))
        if "paused_at" not in chat_columns:
            conn.execute("ALTER TABLE chats ADD COLUMN paused_at TEXT")
        message_columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
        if "parsed" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN parsed INTEGER")
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
        if "kcal" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN kcal REAL")
        if "feeding" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN feeding TEXT")
        if "amount_ml" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN amount_ml REAL")
        if "temp_c" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN temp_c REAL")
        if "liquid" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN liquid INTEGER")
        if "water_fraction" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN water_fraction REAL")
        if "subject" not in columns:
            conn.execute("ALTER TABLE events ADD COLUMN subject TEXT")
            conn.execute(
                "UPDATE events SET subject = "
                "(SELECT profile FROM chats WHERE chats.chat_id = events.chat_id)"
            )


def upsert_chat(chat_id: int, title: str | None) -> profiles.Profile:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO chats (chat_id, title, profile) VALUES (?, ?, ?) "
            "ON CONFLICT (chat_id) DO UPDATE SET title = excluded.title",
            (chat_id, title, profiles.guess(title)),
        )
        row = conn.execute(
            "SELECT profile FROM chats WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return profiles.get(row["profile"] if row else None)


def profile_for(chat_id: int) -> profiles.Profile:
    with _connect() as conn:
        row = conn.execute(
            "SELECT profile FROM chats WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    return profiles.get(row["profile"] if row else None)


def set_profile(chat_id: int, key: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO chats (chat_id, profile) VALUES (?, ?) "
            "ON CONFLICT (chat_id) DO UPDATE SET profile = excluded.profile",
            (chat_id, key),
        )


def all_chats() -> list[tuple[int, profiles.Profile]]:
    with _connect() as conn:
        rows = list(conn.execute("SELECT chat_id, profile FROM chats"))
    return [(row["chat_id"], profiles.get(row["profile"])) for row in rows]


def active_chats() -> list[tuple[int, profiles.Profile]]:
    with _connect() as conn:
        rows = list(
            conn.execute("SELECT chat_id, profile FROM chats WHERE paused_at IS NULL")
        )
    return [(row["chat_id"], profiles.get(row["profile"])) for row in rows]


def paused_since(chat_id: int) -> datetime | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT paused_at FROM chats WHERE chat_id = ?", (chat_id,)
        ).fetchone()
    if row is None or not row["paused_at"]:
        return None
    return datetime.fromisoformat(row["paused_at"])


def set_paused(chat_id: int, at: datetime | None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO chats (chat_id, paused_at) VALUES (?, ?) "
            "ON CONFLICT (chat_id) DO UPDATE SET paused_at = excluded.paused_at",
            (chat_id, at.isoformat() if at else None),
        )


def recent_messages(
    chat_id: int, before: datetime, window: timedelta, limit: int = 6
) -> list[tuple[str, str]]:
    since = (before - window).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT sent_at, text FROM messages "
            "WHERE chat_id = ? AND sent_at < ? AND sent_at >= ? ORDER BY sent_at DESC LIMIT ?",
            (chat_id, before.isoformat(), since, limit),
        ).fetchall()
    return [(r["sent_at"], r["text"]) for r in reversed(rows)]


def message_seen(chat_id: int, message_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM messages WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        ).fetchone()
        return row is not None


def _event_time(sent_at: datetime, event) -> datetime:
    mentioned = getattr(event, "time", None)
    if not mentioned:
        return sent_at
    try:
        hour, minute = (int(part) for part in mentioned.split(":"))
        occurred = sent_at.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return sent_at
    if occurred > sent_at + timedelta(minutes=5):
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


def _is_separate_portion(existing_ml, new_ml) -> bool:
    return existing_ml is not None and new_ml is not None and existing_ml != new_ml


def _same_form(row: sqlite3.Row, event) -> bool:
    return bool(row["liquid"] or row["feeding"] == "tube") == bool(
        event.liquid or event.feeding == "tube"
    )


def _dedup_food(conn: sqlite3.Connection, chat_id: int, occurred_at: datetime, event) -> bool:
    lo = (occurred_at - FOOD_DEDUP_WINDOW).isoformat()
    hi = (occurred_at + FOOD_DEDUP_WINDOW).isoformat()
    existing = [
        row
        for row in conn.execute(
            "SELECT id, kcal, feeding, amount_ml, liquid, description FROM events "
            "WHERE chat_id = ? AND type = 'food' AND occurred_at BETWEEN ? AND ?",
            (chat_id, lo, hi),
        )
        if _same_form(row, event) and not _is_separate_portion(row["amount_ml"], event.amount_ml)
    ]
    if not existing:
        return True
    best = max(_detail_score(row["kcal"], row["feeding"]) for row in existing)
    if _detail_score(event.kcal, event.feeding) <= best:
        logger.info("Skipping duplicate feeding: %r", event.description)
        return False
    ids = [row["id"] for row in existing]
    conn.execute(
        f"DELETE FROM events WHERE id IN ({','.join('?' * len(ids))})", ids
    )
    logger.info("Replacing %d less detailed feeding(s) with: %r", len(ids), event.description)
    return True


def _dedup_toilet(conn: sqlite3.Connection, chat_id: int, occurred_at: datetime, event) -> bool:
    lo = (occurred_at - FOOD_DEDUP_WINDOW).isoformat()
    hi = (occurred_at + FOOD_DEDUP_WINDOW).isoformat()
    stool = is_stool(event.description)
    same_kind = [
        row
        for row in conn.execute(
            "SELECT id, description FROM events "
            "WHERE chat_id = ? AND type = 'toilet' AND occurred_at BETWEEN ? AND ?",
            (chat_id, lo, hi),
        )
        if is_stool(row["description"]) == stool
    ]
    if not same_kind:
        return True
    if len(event.description or "") <= max(len(row["description"] or "") for row in same_kind):
        logger.info("Skipping duplicate toilet: %r", event.description)
        return False
    ids = [row["id"] for row in same_kind]
    conn.execute(f"DELETE FROM events WHERE id IN ({','.join('?' * len(ids))})", ids)
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
            "SELECT id, name, dose, description FROM events "
            "WHERE chat_id = ? AND type = 'medication' AND occurred_at BETWEEN ? AND ?",
            (chat_id, lo, hi),
        )
        if (row["name"] or "").strip().lower() == name
    ]
    if not same_drug:
        return True
    best = max(_med_detail(row["dose"], row["description"]) for row in same_drug)
    if _med_detail(event.dose, event.description) <= best:
        logger.info("Skipping duplicate medication: %r", event.description)
        return False
    ids = [row["id"] for row in same_drug]
    conn.execute(f"DELETE FROM events WHERE id IN ({','.join('?' * len(ids))})", ids)
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
            "WHERE e.chat_id = ? AND e.type = 'water' AND e.occurred_at BETWEEN ? AND ?",
            (chat_id, lo, hi),
        )
        if not _states_ml(row["source"])
    ]
    if not stale:
        return
    conn.execute(f"DELETE FROM events WHERE id IN ({','.join('?' * len(stale))})", stale)
    logger.info("Replacing %d estimated water event(s) with exact %r", len(stale), text[:60])


def note_bot_report(chat_id: int, message_id: int, sent_at: datetime, marker: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO messages (chat_id, message_id, sender, sent_at, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, message_id, "bot", sent_at.isoformat(), marker),
        )


def save_message(
    chat_id: int,
    message_id: int,
    sender: str,
    sent_at: datetime,
    text: str,
    events: list,
    parsed: bool = True,
) -> None:
    with _connect() as conn:
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
    with _connect() as conn:
        _insert_events(conn, chat_id, message_id, sent_at, text, events)
        conn.execute(
            "UPDATE messages SET parsed = 1 WHERE chat_id = ? AND message_id = ?",
            (chat_id, message_id),
        )


def unparsed_messages(limit: int = 20) -> list[sqlite3.Row]:
    with _connect() as conn:
        return list(
            conn.execute(
                "SELECT chat_id, message_id, sent_at, text FROM messages "
                "WHERE parsed = 0 ORDER BY sent_at LIMIT ?",
                (limit,),
            )
        )


def _subject_of(conn: sqlite3.Connection, chat_id: int) -> str:
    """The animal an event belongs to, named as external contracts name it.

    Deliberately the profile's subject_id and not its key: renaming a profile internally
    must not change what a stored event says about whose history it is.
    """
    row = conn.execute("SELECT profile FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
    return profiles.get(row["profile"] if row else None).subject_id


def _insert_events(
    conn: sqlite3.Connection,
    chat_id: int,
    message_id: int,
    sent_at: datetime,
    text: str,
    events: list,
) -> None:
    is_recap = bool(_RECAP_RE.search(text))
    subject = _subject_of(conn, chat_id)
    for event in events:
        if is_recap and event.type in ("water", "food"):
            logger.info("Skipping recap-derived %s event: %r", event.type, event.description)
            continue
        occurred_at = _event_time(sent_at, event)
        if event.type == "food":
            _backfill_amount_ml(event)
            if (
                event.feeding == "tube"
                and event.amount_ml
                and event.amount_ml > TUBE_MAX_SINGLE_ML
            ):
                logger.info(
                    "Skipping implausible tube feeding %g ml (>%g): %r",
                    event.amount_ml,
                    TUBE_MAX_SINGLE_ML,
                    event.description,
                )
                continue
            if not _dedup_food(conn, chat_id, occurred_at, event):
                continue
        elif event.type == "water":
            _drop_water_estimates(conn, chat_id, occurred_at, text)
        elif event.type == "toilet":
            if not _dedup_toilet(conn, chat_id, occurred_at, event):
                continue
        elif event.type == "medication":
            if not _dedup_medication(conn, chat_id, occurred_at, event):
                continue
        conn.execute(
            "INSERT INTO events "
            "(chat_id, subject, message_id, occurred_at, day, type, name, dose, water_ml, kcal, feeding, amount_ml, temp_c, liquid, water_fraction, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                subject,
                message_id,
                occurred_at.isoformat(),
                care_day(occurred_at).isoformat(),
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
                event.description,
            ),
        )


def events_for_day(chat_id: int, day: date) -> list[sqlite3.Row]:
    with _connect() as conn:
        return list(
            conn.execute(
                "SELECT * FROM events WHERE chat_id = ? AND day = ? ORDER BY occurred_at",
                (chat_id, day.isoformat()),
            )
        )


def events_in_days(chat_id: int, day_from: date, day_to: date) -> list[sqlite3.Row]:
    with _connect() as conn:
        return list(
            conn.execute(
                "SELECT * FROM events WHERE chat_id = ? AND day BETWEEN ? AND ? ORDER BY occurred_at",
                (chat_id, day_from.isoformat(), day_to.isoformat()),
            )
        )


def events_in_range(chat_id: int, start: datetime, end: datetime) -> list[sqlite3.Row]:
    lo_day = care_day(start)
    hi_day = end.date()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE chat_id = ? AND day BETWEEN ? AND ? ORDER BY occurred_at",
            (chat_id, lo_day.isoformat(), hi_day.isoformat()),
        )
        return [r for r in rows if start <= datetime.fromisoformat(r["occurred_at"]) < end]


EDITABLE_COLUMNS = (
    "description",
    "kcal",
    "water_ml",
    "amount_ml",
    "water_fraction",
    "name",
    "liquid",
    "feeding",
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


def _log_edit(
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
    with _connect() as conn:
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
    with _connect() as conn:
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
    with _connect() as conn:
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
            _log_edit(conn, event_id, edited_at, "update", before, changed)
        return _event_with_source(conn, event_id)


def delete_event(event_id: int, edited_at: datetime) -> sqlite3.Row | None:
    with _connect() as conn:
        row = _event_with_source(conn, event_id)
        if row is None:
            return None
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        stored = {key: row[key] for key in row.keys() if key != "message_text"}
        _log_edit(conn, event_id, edited_at, "delete", stored, None)
        return row


def edits_for_event(event_id: int) -> list[sqlite3.Row]:
    with _connect() as conn:
        return list(
            conn.execute(
                "SELECT * FROM event_edits WHERE event_id = ? ORDER BY id DESC",
                (event_id,),
            )
        )
