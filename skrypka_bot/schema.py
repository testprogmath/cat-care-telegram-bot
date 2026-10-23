"""The diary's tables and the columns added to them since, applied to the database on every start."""

import sqlite3


def apply(conn: sqlite3.Connection) -> None:
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
        CREATE TABLE IF NOT EXISTS pieces_questions (
            chat_id     INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            event_id    INTEGER NOT NULL,
            asked_at    TEXT NOT NULL,
            PRIMARY KEY (chat_id, question_id)
        );
        CREATE TABLE IF NOT EXISTS stool_questions (
            chat_id     INTEGER NOT NULL,
            question_id INTEGER NOT NULL,
            message_id  INTEGER NOT NULL,
            asked_at    TEXT NOT NULL,
            PRIMARY KEY (chat_id, question_id)
        );
        """
    )
    chat_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chats)")}
    if "profile" not in chat_columns:
        conn.execute("ALTER TABLE chats ADD COLUMN profile TEXT")
    if "paused_at" not in chat_columns:
        conn.execute("ALTER TABLE chats ADD COLUMN paused_at TEXT")
    if "auto_left" not in chat_columns:
        conn.execute("ALTER TABLE chats ADD COLUMN auto_left INTEGER NOT NULL DEFAULT 1")
    if "tube_out_at" not in chat_columns:
        conn.execute("ALTER TABLE chats ADD COLUMN tube_out_at TEXT")
    for column in ("kcal_goal", "water_goal_ml"):
        if column not in chat_columns:
            conn.execute(f"ALTER TABLE chats ADD COLUMN {column} REAL")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_chats_profile ON chats (profile) "
        "WHERE profile IS NOT NULL"
    )
    question_columns = {row["name"] for row in conn.execute("PRAGMA table_info(stool_questions)")}
    if "answered_at" not in question_columns:
        conn.execute("ALTER TABLE stool_questions ADD COLUMN answered_at TEXT")
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
    for column, kind in (
        ("weight_kg", "REAL"), ("breaths", "REAL"), ("asleep", "INTEGER"), ("stool_score", "INTEGER"),
        ("pieces", "TEXT"),
    ):
        if column not in columns:
            conn.execute(f"ALTER TABLE events ADD COLUMN {column} {kind}")
    if "subject" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN subject TEXT")
        conn.execute(
            "UPDATE events SET subject = "
            "(SELECT profile FROM chats WHERE chats.chat_id = events.chat_id)"
        )
